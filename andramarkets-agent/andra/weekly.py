"""Weekly market review, built from the week's archived daily fact packs.

Nothing is fetched from a market data vendor: every figure comes from the
daily notes' verified facts (the archive releases, archive-YYYY-MM-DD) or
from the site's economic calendar, so the weekly note can say nothing the
daily notes could not.

    snapshots   one per archived run: its fact pack and the session it was
                really for. Archive labels from before 23 October 2026 are
                the run's date, not the session's (a Saturday run labelled
                Saturday, a morning run labelled with the day it reported
                nothing for), so the session is worked out from the prices
                themselves: a snapshot whose previous S&P 500 close is
                another snapshot's close is the session after it.
    week_facts  the weekly fact pack: weekly moves for every instrument
                (last close of the week against the last close of the week
                before), the S&P 500 day by day, the risk score day by day,
                the week's macro releases and earnings, and next week's
                events, from the site calendar when it can be read.
    write       the model writes from that pack only, and the same figure
                check as the daily note (narrative.audit) runs on the text.
                Without the model, write_without_model() sets a short note
                from the figures alone.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .narrative import MAX_TOKENS, MODEL, SYSTEM, Note, audit, parse_reply
from .universe import all_instruments

log = logging.getLogger("andra.weekly")

BLOCKS = (("us_equity", "US equities"), ("sectors", "S&P 500 sectors"),
          ("europe", "Europe"), ("apac", "Asia-Pacific"), ("americas", "Americas"),
          ("treasury_curve", "US Treasury curve"), ("breakevens", "Inflation"),
          ("credit", "Credit"), ("fx", "Currencies"), ("commodities", "Commodities"),
          ("volatility", "Volatility"), ("digital", "Digital assets"))
INDEX_BLOCKS = ("us_equity", "europe", "apac", "americas")
# Markets with one official close a day. Currencies, commodity futures and
# digital assets trade around the clock: a note's "previous close" for them
# is the provider's daily bar, not the previous run's snapshot, so their
# prints are not expected to chain from one note to the next.
CLOSING_BLOCKS = ("us_equity", "sectors", "europe", "apac", "americas",
                  "treasury_curve", "breakevens", "credit", "volatility")
# How close an implied previous close must be to another snapshot's close
# for the two to be consecutive sessions. Changes are stored to 3 decimals,
# so the implied close is good to about 5 parts in a million.
CHAIN_TOL = 2e-5
SITE_URL = os.getenv("ANDRA_SITE_URL",
                     "https://pabloballesteros1412.github.io/andramarkets-site").rstrip("/")
_FILE = re.compile(r"facts_(\d{8})(?:_r(\d+))?\.json")


# ------------------------------------------------------------- snapshots
@dataclass
class Snapshot:
    label: dt.date            # the date the archive filed it under
    run: int
    facts: dict
    session: dt.date | None = None

    def row(self, key: str) -> dict | None:
        for b, _ in BLOCKS:
            for r in self.facts.get(b, []):
                if r.get("key") == key:
                    return r
        return None

    @property
    def spx(self) -> tuple[float, float] | None:
        r = self.row("spx")
        return (r["last"], r["chg"]) if r and r.get("last") and r.get("chg") is not None else None


def load_snapshots(folder: Path) -> list[Snapshot]:
    out = []
    for p in sorted(Path(folder).glob("facts_*.json")):
        m = _FILE.fullmatch(p.name)
        if not m:
            continue
        d = m.group(1)
        out.append(Snapshot(dt.date(int(d[:4]), int(d[4:6]), int(d[6:])),
                            int(m.group(2) or 0),
                            json.loads(p.read_text(encoding="utf-8"))))
    return out


def nyse_sessions(start: dt.date, end: dt.date) -> list[dt.date]:
    from .session import _schedule
    return [d.date() for d in _schedule(start, end).index]


def resolve_sessions(snaps: list[Snapshot], sessions: list[dt.date]) -> dict[dt.date, Snapshot]:
    """The snapshot for each session, worked out from the prices.

    1. A snapshot whose S&P 500 row carries its own print date (runs from
       22 October 2026 on) is for that date.
    2. Otherwise, if its implied previous close (close / (1 + change)) is the
       close of a snapshot already placed, it is the session after that one.
    3. Otherwise it is the last session on or before its archive label.
    Identical snapshots (one session archived twice) count once; two
    different snapshots for one session keep the later run.
    """
    seen, distinct = set(), []
    for s in sorted(snaps, key=lambda s: (s.label, s.run)):
        sig = s.spx
        if sig is None or sig in seen:
            continue
        seen.add(sig)
        distinct.append(s)

    def after(d):
        later = [x for x in sessions if x > d]
        return later[0] if later else None

    def on_or_before(d):
        earlier = [x for x in sessions if x <= d]
        return earlier[-1] if earlier else None

    placed: list[Snapshot] = []
    for s in distinct:
        last, chg = s.spx
        own = (s.row("spx") or {}).get("date")
        if own:
            s.session = dt.date.fromisoformat(own)
        else:
            prev = last / (1 + chg / 100)
            link = next((p for p in reversed(placed)
                         if abs(p.spx[0] - prev) <= CHAIN_TOL * prev), None)
            s.session = after(link.session) if link else on_or_before(s.label)
        if s.session is not None:
            placed.append(s)

    out: dict[dt.date, Snapshot] = {}
    for s in placed:
        if s.session not in out or s.run >= out[s.session].run:
            out[s.session] = s
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ facts
def _units() -> dict[str, str]:
    return {i.key: i.unit for i in all_instruments()}


def _prior_rows(snap: Snapshot) -> dict[str, dict]:
    """Previous closes implied by a snapshot's own session changes."""
    units, out = _units(), {}
    for b, _ in BLOCKS:
        for r in snap.facts.get(b, []):
            last, chg = r.get("last"), r.get("chg")
            if last is None or chg is None:
                continue
            rate = units.get(r["key"]) == "pct"
            out[r["key"]] = {**r, "last": last - chg / 100 if rate else last / (1 + chg / 100)}
    return out


def broken_chains(pairs: list[tuple[Snapshot, Snapshot]]) -> dict[str, str]:
    """Instruments whose close in a note does not follow from the note of the
    session before: the close a note implies before its own change (close
    less the change) should be the earlier note's close, or the same print
    repeated when that market had not traded again. Checked on the two
    closes a weekly figure rests on (the week's last and the previous
    week's), for markets with an official close only. A break means the
    provider revised or mixed up the series between runs, so the weekly
    figure cannot be trusted. A print the earlier note marked as not yet
    published, or as from another session, is not checked: that note quoted
    an older close, so the next change starts from a close it never printed
    (Asian indices and FRED series, most days). Returns key -> name."""
    units, out = _units(), {}
    for before, after in pairs:
        late = set(before.facts.get("series_not_yet_published", []))
        prev = {r["key"]: r for b in CLOSING_BLOCKS for r in before.facts.get(b, [])
                if r["key"] not in late and not r.get("off_session")}
        for b in CLOSING_BLOCKS:
            for r in after.facts.get(b, []):
                p = prev.get(r["key"])
                last, chg = r.get("last"), r.get("chg")
                if not p or last is None or chg is None or p.get("last") is None:
                    continue
                rate = units.get(r["key"]) == "pct"
                implied = last - chg / 100 if rate else last / (1 + chg / 100)
                tol = 0.006 if rate else 0.001 * abs(p["last"])
                same = abs(last - p["last"]) <= (0.0005 if rate else 1e-6 * abs(last))
                if not same and abs(implied - p["last"]) > tol:
                    out[r["key"]] = r["name"]
    return out


def _move(end: float, base: float, rate: bool) -> float | None:
    if base is None or end is None:
        return None
    if rate:
        return round((end - base) * 100, 1)
    return round(100 * (end / base - 1), 3) if base else None


def week_facts(by_session: dict[dt.date, Snapshot], friday: dt.date,
               calendar: dict | None = None) -> dict:
    """The weekly fact pack for the NYSE week ending `friday`."""
    monday = friday - dt.timedelta(days=friday.weekday())
    sessions = nyse_sessions(monday - dt.timedelta(days=10), friday)
    week = [d for d in sessions if monday <= d <= friday]
    if not week:
        raise ValueError(f"NYSE did not trade in the week of {monday}.")
    have = [d for d in week if d in by_session]
    if not have:
        raise ValueError(f"no archived note for any session of the week of {monday}.")
    end = by_session[have[-1]]

    before = [d for d in sessions if d < week[0]]
    base_day = before[-1] if before else None
    if base_day in by_session:
        base_rows = {r["key"]: r for b, _ in BLOCKS for r in by_session[base_day].facts.get(b, [])}
        base_from = "archived"
    else:
        # The prior week's last note is missing: the week's first archived
        # note gives that close back through its own session change, when it
        # is the week's first session.
        first = by_session[have[0]]
        base_rows = _prior_rows(first) if have[0] == week[0] else {}
        base_from = "implied by the first session's change" if base_rows else "unavailable"

    def with_prior(day):
        i = sessions.index(day)
        return (by_session[sessions[i - 1]], by_session[day]) \
            if i and sessions[i - 1] in by_session and day in by_session else None
    pairs = [p for p in (with_prior(have[-1]),
                         with_prior(base_day) if base_day in by_session else None) if p]
    broken = broken_chains(pairs)
    if broken:
        log.warning("Prints that do not chain across the week, left out: %s",
                    ", ".join(sorted(broken.values())))

    units = _units()
    moves = {}
    for b, _ in BLOCKS:
        rows = []
        for r in end.facts.get(b, []):
            if r["key"] in broken:
                continue
            base = base_rows.get(r["key"], {}).get("last")
            rate = units.get(r["key"]) == "pct"
            mv = _move(r.get("last"), base, rate)
            if mv is None:
                continue
            rows.append({"key": r["key"], "name": r["name"], "last": r["last"],
                         "prior_week": round(base, 3), "week": mv,
                         "ytd": r.get("ytd"), "unit": "bp" if rate else "%"})
        moves[b] = rows

    indices = [r for b in INDEX_BLOCKS for r in moves[b]]
    ranked = sorted(indices, key=lambda r: r["week"], reverse=True)
    spx_path, risk_path = [], []
    for d in have:
        s = by_session[d]
        if s.spx:
            spx_path.append({"date": d.isoformat(), "last": s.spx[0], "chg": s.spx[1]})
        bar = s.facts.get("risk_barometer") or {}
        if bar.get("score") is not None:
            risk_path.append({"date": d.isoformat(), "score": bar["score"],
                              "label": bar.get("label")})

    cal = calendar or {}
    return {
        "week": {
            "start": monday.isoformat(), "end": friday.isoformat(),
            "sessions": [d.isoformat() for d in week],
            "archived": [d.isoformat() for d in have],
            "missing": [d.isoformat() for d in week if d not in by_session],
            "last_session": have[-1].isoformat(),
            "prior_close": base_day.isoformat() if base_day else None,
            "prior_close_from": base_from,
            "left_out": sorted(broken.values()),
        },
        "moves": moves,
        "indices_best": ranked[:3], "indices_worst": ranked[::-1][:3],
        "sectors_ranked": sorted(moves["sectors"], key=lambda r: r["week"], reverse=True),
        "spx_path": spx_path,
        "risk_path": risk_path,
        "macro": cal.get("macro", []),
        "earnings": cal.get("earnings", []),
        "week_ahead": cal.get("week_ahead", []),
        "calendar_source": cal.get("source"),
    }


# --------------------------------------------------------- site calendar
_NUM = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")


def _values(text: str) -> list[float]:
    """The figures in a calendar cell ("+0.3%", "254K", "$2.35", a fall printed
    with a true minus sign), as numbers, so the figure check can find them in
    the fact pack."""
    t = (text or "").replace("\u2212", "-")
    return [float(m.replace(",", "")) for m in _NUM.findall(t)]


class _CalendarPage(HTMLParser):
    """Rows of a calendar page built by the site (tools/build_site.py,
    cal_table and cal_row): one tbody per New York day, one tr.cl__row per
    event, with the type, region and importance as data attributes and the
    event, previous and actual figures in their own cells. A cell's text is
    everything inside the element that opened it, nested links and spans
    included."""

    CELLS = {"cl__ev": "title", "cl__region": "country", "cl__ny": "time",
             "cl__prior": "previous", "cl__act": "actual", "cl__react": "reaction"}
    VOID = {"br", "img", "use", "input", "meta", "link", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.day, self.cur = [], None, None
        self.depth, self.cell = 0, None     # cell: (name, depth it opened at)

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        self.depth += 1
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "tbody" and "cl__day-group" in cls:
            self.day = a.get("data-day")
        elif tag == "tr" and "cl__row" in cls:
            self.cur = {"date": self.day, "type": a.get("data-type"),
                        "imp": a.get("data-imp"), "title": "", "country": "",
                        "time": "", "previous": "", "actual": "", "reaction": ""}
        elif self.cur is not None and self.cell is None:
            name = next((self.CELLS[c] for c in cls if c in self.CELLS), None)
            if name:
                self.cell = (name, self.depth)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.cell and self.cell[1] == self.depth:
            self.cell = None
        if tag == "tr" and self.cur is not None:
            self.rows.append({k: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v
                              for k, v in self.cur.items()})
            self.cur = None
        self.depth -= 1

    def handle_data(self, data):
        if self.cur is not None and self.cell:
            self.cur[self.cell[0]] += data


def parse_calendar(page: str) -> list[dict]:
    p = _CalendarPage()
    p.feed(page)
    rows = []
    for r in p.rows:
        if not r["title"]:
            continue
        r["previous"] = r["previous"].replace("\u2212", "-")
        r["actual"] = r["actual"].replace("\u2212", "-")
        r["reaction"] = r["reaction"].replace("\u2212", "-").replace("First session", "").strip()
        r["values"] = _values(r["previous"]) + _values(r["actual"]) + _values(r["reaction"])
        rows.append(r)
    return rows


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "andramarkets-agent weekly"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
        return r.read().decode("utf-8", "replace")


def site_calendar(friday: dt.date, pages: dict[str, str] | None = None,
                  max_earnings: int = 12) -> dict:
    """This week's macro releases and earnings, and next week's events, from
    the site's calendar week pages (calendar/week/<monday>/). `pages` maps a
    Monday's ISO date to the page's HTML, for tests and offline runs.
    Returns {} when the calendar cannot be read: the note then goes out
    without those sections, and says so."""
    monday = friday - dt.timedelta(days=friday.weekday())
    nxt = monday + dt.timedelta(days=7)
    got = {}
    for d in (monday, nxt):
        key = d.isoformat()
        if pages is not None:
            if key in pages:
                got[key] = parse_calendar(pages[key])
            continue
        url = f"{SITE_URL}/calendar/week/{key}/"
        try:
            got[key] = parse_calendar(_fetch(url))
        except Exception as e:  # noqa: BLE001
            log.warning("Site calendar unavailable for the week of %s: %s", key, e)
    if monday.isoformat() not in got and nxt.isoformat() not in got:
        return {}

    this = got.get(monday.isoformat(), [])
    macro = [r for r in this if r["type"] == "macro" and r["imp"] == "High" and r["actual"]]
    earnings = [r for r in this if r["type"] == "earnings" and (r["actual"] or r["reaction"])]
    ahead = [r for r in got.get(nxt.isoformat(), [])
             if r["imp"] == "High" and r["type"] in ("macro", "earnings", "market")]
    return {"macro": macro, "earnings": earnings[:max_earnings], "week_ahead": ahead,
            "source": f"{SITE_URL}/calendar/week/{monday.isoformat()}/"}


# ---------------------------------------------------------------- writing
WEEKLY_FIELDS = ("headline", "standfirst", "takeaways", "narrative", "macro",
                 "week_ahead", "linkedin")
WEEKLY_LISTS = ("takeaways",)

WEEKLY_SYSTEM = SYSTEM.replace(
    "You write the daily US market close note for Andra Markets",
    "You write the weekly market review for Andra Markets").replace(
    "Write like a strategist typing a note at 4:30pm",
    "Write like a strategist closing the book on a Friday")

WEEKLY_SCHEMA = """Output format. Write each section after its tag, on the lines
below it. Use the tags exactly as written, one per line, in this order. No
JSON, no markdown, no wrapper.

The fact pack covers one trading week. "week" in each row of "moves" is the
change from the last close of the previous week to the last close of this
one: percent for prices, basis points where "unit" is "bp". "spx_path" is the
S&P 500 day by day, "risk_path" the daily cross-asset risk score, "macro" and
"earnings" the week's releases and reports from the economic calendar,
"week_ahead" next week's high-importance events. If "macro", "earnings" or
"week_ahead" is empty, say nothing about them and do not invent any.

===headline===
8 to 13 words. What the week was about, as a claim.

===standfirst===
Two sentences. The week's move and what drove it.

===takeaways===
Four one-sentence conclusions, ordered by importance. One per line.

===narrative===
Three short paragraphs: equities and sectors; rates, credit and the dollar;
commodities, volatility and digital assets. Say what the week changed.

===macro===
One paragraph on the week's macro releases and earnings and how the market
took them. Only what is in "macro" and "earnings".

===week_ahead===
One paragraph on next week's events from "week_ahead" and why they matter.

===linkedin===
LinkedIn caption, 700 to 1100 characters. Plain text. Open with the week's
most informative fact. Short paragraphs separated by a blank line. No
hashtags, no emoji, no markdown, no sign-off.
"""


def _complete(content: dict) -> dict:
    for f in WEEKLY_FIELDS:
        content.setdefault(f, [] if f in WEEKLY_LISTS else "")
    if not content.get("headline"):
        content["headline"] = "Weekly market review"
    return content


def write(facts: dict, max_attempts: int = 3) -> Note:
    """The model writes the review; the daily note's figure check audits it,
    and a rejected draft goes back with the offending figures."""
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    messages = [{"role": "user", "content":
                 f"{WEEKLY_SCHEMA}\n\nVerified fact pack for the week. This is the "
                 f"only admissible source of figures:\n\n"
                 f"{json.dumps(facts, ensure_ascii=False, default=str)}"}]
    content, bad, last_error = {}, [], None
    for attempt in range(1, max_attempts + 1):
        try:
            # Plain call, no thinking parameter (CLAUDE.md).
            r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                                       system=WEEKLY_SYSTEM, messages=messages)
            txt = "".join(getattr(b, "text", "") for b in r.content if b.type == "text")
            if r.stop_reason == "max_tokens":
                raise ValueError("reply hit the token ceiling and is truncated")
            content = parse_reply(txt, WEEKLY_FIELDS, WEEKLY_LISTS)
            missing = [f for f in WEEKLY_FIELDS if f not in content]
            if missing:
                raise ValueError(f"reply is incomplete: no {', '.join(missing)}")
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("Attempt %d failed to produce a usable reply: %s", attempt, e)
            continue
        bad = audit(content, facts)
        if not bad:
            return Note(_complete(content), True, [], attempt)
        log.warning("Audit %d rejected figures: %s", attempt, bad)
        tagged = "\n\n".join(f"==={k}===\n" + ("\n".join(v) if isinstance(v, list) else v)
                             for k, v in content.items())
        messages += [{"role": "assistant", "content": tagged},
                     {"role": "user", "content":
                      f"The figure check rejected these because they are not in the "
                      f"fact pack: {bad}. Return the full review again with those "
                      f"removed or replaced by the correct value from the pack. Do "
                      f"not introduce any new figure."}]
    if content:
        return Note(_complete(content), False, bad, max_attempts)
    raise RuntimeError(f"no usable reply after {max_attempts} attempts: {last_error}")


def _pct(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{abs(v):.2f}%"


def _bp(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{abs(v):.1f}bp"


def _fmt(r: dict) -> str:
    return _bp(r["week"]) if r["unit"] == "bp" else _pct(r["week"])


def _find(facts: dict, block: str, key: str) -> dict | None:
    return next((r for r in facts["moves"].get(block, []) if r["key"] == key), None)


def write_without_model(facts: dict) -> Note:
    """A short review set from the figures alone, every one of them quoted
    as the fact pack holds it, so it passes the figure check by construction.
    Used when the model is unavailable."""
    spx = _find(facts, "us_equity", "spx")
    ust = _find(facts, "treasury_curve", "ust10y")
    dxy = _find(facts, "fx", "dxy")
    best, worst = facts["indices_best"], facts["indices_worst"]
    sec = facts["sectors_ranked"]
    risk = facts["risk_path"]

    head = "Weekly market review"
    if spx:
        verb = "gained" if spx["week"] >= 0 else "lost"
        head = f"The S&P 500 {verb} {abs(spx['week']):.2f}% over the week"
    stand = []
    if spx:
        stand.append(f"The S&P 500 closed the week at {spx['last']:,.2f}, "
                     f"{_pct(spx['week'])} on the previous week's close.")
    stand.append("Published in quantitative mode: the tables and exhibits carry "
                 "the week, without commentary.")

    take = []
    if sec:
        take.append(f"{sec[0]['name']} was the strongest sector at {_fmt(sec[0])} "
                    f"and {sec[-1]['name']} the weakest at {_fmt(sec[-1])}.")
    if best and worst:
        take.append(f"{best[0]['name']} led the major indices at {_fmt(best[0])} "
                    f"and {worst[0]['name']} trailed at {_fmt(worst[0])}.")
    if ust:
        take.append(f"The 10-year Treasury yield moved {_bp(ust['week'])} to "
                    f"{ust['last']:.2f}%.")
    if risk:
        take.append(f"The cross-asset risk score ended the week at "
                    f"{risk[-1]['score']:.2f}, read as {str(risk[-1]['label']).lower()}.")

    # One paragraph per section of the note: equities; rates, credit and
    # the dollar; commodities, volatility and digital assets.
    missing = facts["week"]["missing"]
    eq = (f"No note was archived for {', '.join(missing)}, so the day-by-day "
          f"figures leave it out; the weekly moves are unaffected." if missing else "")
    macro = []
    if dxy:
        macro.append(f"The dollar index moved {_pct(dxy['week'])} to {dxy['last']:.2f}.")
    rest = []
    for block, label in (("commodities", "In commodities"), ("digital", "In digital assets")):
        rows = sorted(facts["moves"].get(block, []), key=lambda r: r["week"])
        if rows:
            rest.append(f"{label}, {rows[-1]['name']} moved {_fmt(rows[-1])} and "
                        f"{rows[0]['name']} {_fmt(rows[0])}.")
    content = {
        "headline": head,
        "standfirst": " ".join(stand),
        "takeaways": take,
        "narrative": "\n\n".join([eq, " ".join(macro), " ".join(rest)]),
        "macro": "", "week_ahead": "", "linkedin": "",
    }
    return Note(_complete(content), audit_ok=not audit(content, facts))
