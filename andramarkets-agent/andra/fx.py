"""Daily FX analysis: the dollar, the G10 majors and the main EM pairs.

Built on the same MarketFrame and the same figure check as the close note:

    fx_facts   the FX fact pack: each pair's close and its daily, weekly and
               monthly move as quoted, the currency's own move against the
               dollar, the levels that matter (1-month and 52-week range,
               50- and 200-day averages), its 60-session correlation with the
               US 2-year yield, and the policy rate of its central bank with
               the differential to the Fed.
    write      the model writes from that pack only; narrative.audit checks
               every figure, and the length (800 to 1,200 words) and the
               neutrality check (no trade language) are enforced the same way:
               a draft that fails goes back with the reason.
    to_site    the JSON the site imports for its FX section (fx_YYYYMMDD.json).

Policy rates: the Fed and the ECB come from FRED every day. Every other bank
comes from central_banks.json, which the desk maintains; an entry is used only
when it is marked verified and its next meeting has not yet come, so a rate
is never printed from memory or after a decision it does not reflect.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path

import pandas as pd

from .narrative import (MAX_TOKENS, MODEL, SYSTEM, Note, _metered, audit,
                        parse_reply)

log = logging.getLogger("andra.fx")

ROOT = Path(__file__).resolve().parent.parent
BANKS_FILE = ROOT / "central_banks.json"
SCHEMA_ID = "andra.fx/1"

# (key, currency, group). Order is the order of the tables.
PAIRS = (
    ("dxy", "USD", "dollar"),
    ("eurusd", "EUR", "major"), ("usdjpy", "JPY", "major"),
    ("gbpusd", "GBP", "major"), ("usdchf", "CHF", "major"),
    ("usdcad", "CAD", "major"), ("audusd", "AUD", "major"),
    ("nzdusd", "NZD", "major"),
    ("usdcny", "CNY", "em"), ("usdmxn", "MXN", "em"), ("usdbrl", "BRL", "em"),
    ("usdinr", "INR", "em"), ("usdkrw", "KRW", "em"), ("usdzar", "ZAR", "em"),
    ("usdtry", "TRY", "em"),
)
# Policy rates read from FRED: currency -> MarketFrame key.
FRED_POLICY = {"USD": "fedupper", "EUR": "ecbdfr"}
AHEAD_DAYS = 14

WORDS_MIN, WORDS_MAX = 800, 1200
FIELDS = ("headline", "standfirst", "takeaways", "dollar", "majors", "em",
          "drivers", "levels", "ahead")
LISTS = ("takeaways", "levels")
# Sections as the PDF and the site print them, in order.
SECTIONS = (("dollar", "The dollar"), ("majors", "G10 majors"),
            ("em", "Emerging markets"),
            ("drivers", "Rate differentials and central banks"),
            ("levels", "Levels that matter"), ("ahead", "Ahead"))
# Trade language. The note describes; it never tells anyone what to do.
_ADVICE = re.compile(
    r"\b(?:recommend\w*|we (?:like|prefer|favou?r|expect|see value)|"
    r"(?:go|going|get|stay|be) (?:long|short)|price target|target of|"
    r"stop[- ]loss|take[- ]profit|entry (?:point|level)|buy(?!-side)|"
    r"sell(?!-off|-side)|"
    r"overweight|underweight|should (?:buy|sell|hedge|fade|add))\b", re.I)


# ------------------------------------------------------------- policy rates
def load_banks(path: Path = BANKS_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("%s not found: only the FRED policy rates are used.", path.name)
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _fred_policy(mf, key: str) -> dict | None:
    if key not in mf.px.columns:
        return None
    s = mf.px[key].dropna()
    if s.empty:
        return None
    out = {"rate": round(float(s.iloc[-1]), 2), "last_decision": None,
           "last_change_bp": None}
    d = s.diff()
    moved = d[d.abs() > 1e-9]
    if not moved.empty:
        out["last_decision"] = moved.index[-1].date().isoformat()
        out["last_change_bp"] = round(float(moved.iloc[-1]) * 100)
    return out


def policy_rates(mf, banks: dict, asof: dt.date) -> tuple[dict, list, list]:
    """currency -> policy entry, plus the banks not on file and the banks
    whose entry is out of date (its next meeting has come)."""
    out, missing, stale = {}, [], []
    for ccy, b in banks.items():
        nxt = b.get("next_meeting")
        nxt_d = dt.date.fromisoformat(nxt) if nxt else None
        entry = {"bank": b.get("bank"), "short": b.get("short"),
                 "rate_name": b.get("rate_name"),
                 "next_meeting": nxt if (b.get("verified") and nxt_d and nxt_d > asof) else None}
        if ccy in FRED_POLICY:
            got = _fred_policy(mf, FRED_POLICY[ccy])
            if got is None:
                missing.append(b.get("short") or ccy)
                continue
            entry.update(got, source="FRED")
            if ccy == "USD" and "fedlower" in mf.px.columns:
                lo = mf.px["fedlower"].dropna()
                entry["rate_lower"] = round(float(lo.iloc[-1]), 2) if not lo.empty else None
        elif not b.get("verified") or b.get("rate") is None:
            missing.append(b.get("short") or ccy)
            continue
        elif nxt_d and nxt_d <= asof:
            stale.append(b.get("short") or ccy)
            continue
        else:
            entry.update(rate=float(b["rate"]), last_decision=b.get("last_decision"),
                         last_change_bp=b.get("last_change_bp"),
                         source=b.get("source"))
        out[ccy] = entry
    return out, missing, stale


# ---------------------------------------------------------------- the facts
def _r(v, n=3):
    return None if v is None or pd.isna(v) else round(float(v), n)


def _vs_usd(chg: float | None, usd_base: bool) -> float | None:
    """The currency's own move against the dollar, from the pair's move.
    For USD/XXX a rise in the pair is a fall in the currency."""
    if chg is None or pd.isna(chg):
        return None
    return _r(100.0 * (1.0 / (1.0 + chg / 100.0) - 1.0) if usd_base else chg)


def _levels(s: pd.Series, snap_row) -> dict:
    lv = {"high_1m": s.tail(21).max(), "low_1m": s.tail(21).min(),
          "ma50": s.tail(50).mean() if len(s) >= 50 else None,
          "ma200": s.tail(200).mean() if len(s) >= 200 else None,
          "high_52w": snap_row["high52"], "low_52w": snap_row["low52"]}
    return {k: _r(v, 5) for k, v in lv.items()}


def _nearest(last: float, levels: dict, dec: int) -> dict:
    """The closest level either side of the close, compared at the pair's
    quoted decimals; levels the close sits on are listed under "at"."""
    q = round(last, dec)
    got = [(v, k) for k, v in levels.items() if v is not None]
    above = sorted((v, k) for v, k in got if round(v, dec) > q)
    below = sorted(((v, k) for v, k in got if round(v, dec) < q), reverse=True)
    out = {"at": [k for v, k in got if round(v, dec) == q]}
    for side, near in (("above", above), ("below", below)):
        if near:
            v, k = near[0]
            out[side] = {"level": k, "value": v,
                         "distance_pct": _r(100.0 * (v / last - 1.0), 2)}
    return out


def fx_facts(mf, banks: dict | None = None) -> dict:
    """The FX fact pack. Nothing else is admissible in the FX note."""
    asof = mf.asof
    target = asof.isoformat()
    banks = load_banks() if banks is None else banks
    policy, banks_missing, banks_stale = policy_rates(mf, banks, asof)
    fed = policy.get("USD")
    ust2y = mf.px["ust2y"].diff() if "ust2y" in mf.px.columns else None

    pairs, missing = [], []
    for key, ccy, group in PAIRS:
        if key not in mf.snap.index or key not in mf.px.columns:
            missing.append(key)
            continue
        r = mf.snap.loc[key]
        name = str(r["name"])
        usd_base = name.startswith("USD/")
        s = mf.px[key].dropna()
        last = float(r["last"])
        levels = _levels(s, r)
        corr = None
        if ust2y is not None:
            joined = pd.concat([s.pct_change(), ust2y], axis=1).dropna().tail(60)
            if len(joined) > 20:
                corr = _r(joined.iloc[:, 0].corr(joined.iloc[:, 1]), 2)
        row = {
            "key": key, "name": name, "currency": ccy, "group": group,
            "quote": ("index" if group == "dollar" else
                      f"{ccy} per USD" if usd_base else f"USD per {ccy}"),
            "dec": int(r["dec"]),
            "last": _r(last, 5), "prev": _r(r["prev"], 5),
            "d1": _r(r["chg"]), "w1": _r(r["w1"]), "m1": _r(r["m1"]),
            "ytd": _r(r["ytd"]), "z": _r(r["z"], 2),
            "ccy_vs_usd": (None if group == "dollar" else
                           {h: _vs_usd(r[f], usd_base)
                            for h, f in (("d1", "chg"), ("w1", "w1"), ("m1", "m1"))}),
            "levels": levels, "nearest": _nearest(last, levels, int(r["dec"])),
            "corr_ust2y_60d": corr,
            "date": str(r["date"]), "off_session": str(r["date"]) != target,
        }
        p = policy.get(ccy) if group != "dollar" else None
        if p:
            row["policy"] = {**p, "vs_fed_bp": (round((p["rate"] - fed["rate"]) * 100)
                                                if fed else None)}
        else:
            row["policy"] = None
        pairs.append(row)

    def us(key):
        if key not in mf.snap.index:
            return None
        r = mf.snap.loc[key]
        return {"last": _r(r["last"]), "d1_bp": _r(r["chg"], 1),
                "w1_bp": _r(r["w1"], 1), "m1_bp": _r(r["m1"], 1)}

    ranked = {}
    for h in ("d1", "w1", "m1"):
        got = sorted((p for p in pairs if p["ccy_vs_usd"] and p["ccy_vs_usd"][h] is not None),
                     key=lambda p: p["ccy_vs_usd"][h], reverse=True)
        ranked[h] = [{"currency": p["currency"], "vs_usd": p["ccy_vs_usd"][h]} for p in got]
    main = sorted((p for p in pairs if p["z"] is not None), key=lambda p: -abs(p["z"]))[:4]
    end = asof + dt.timedelta(days=AHEAD_DAYS)
    ahead = sorted(({"date": p["next_meeting"], "bank": p["bank"], "currency": c}
                    for c, p in policy.items()
                    if p.get("next_meeting") and asof < dt.date.fromisoformat(p["next_meeting"]) <= end),
                   key=lambda e: e["date"])
    return {
        "date": target,
        "pairs": pairs,
        "us_rates": {"fed": fed, "ust2y": us("ust2y"), "ust10y": us("ust10y")},
        "strength_vs_usd": ranked,
        "main_moves": [p["key"] for p in main],
        "central_bank_meetings_ahead": ahead,
        "banks_not_on_file": banks_missing,
        "banks_out_of_date": banks_stale,
        "pairs_without_print": missing,
        "pairs_off_session": [p["key"] for p in pairs if p["off_session"]],
    }


# ------------------------------------------------------------------ checks
def word_count(content: dict) -> int:
    text = " ".join(" ".join(v) if isinstance(v, list) else str(v)
                    for k, v in content.items() if k != "headline")
    return len(text.split())


def advice_flags(content: dict) -> list[str]:
    text = " ".join(" ".join(v) if isinstance(v, list) else str(v) for v in content.values())
    return sorted({m.group(0).lower() for m in _ADVICE.finditer(text)})


def _problems(content: dict, facts: dict) -> tuple[list, int, list]:
    return audit(content, facts), word_count(content), advice_flags(content)


# ----------------------------------------------------------------- writing
FX_SYSTEM = SYSTEM.replace(
    "You write the daily US market close note for Andra Markets",
    "You write the daily FX analysis for Andra Markets").replace(
    "- Give investment advice, price targets, or any buy or sell language.",
    "- Give investment advice, price targets, trade ideas, or any buy, sell,\n"
    "  long or short language. Do not forecast where a pair will trade. The\n"
    "  note is neutral: it describes what moved, against what, and why the\n"
    "  data says it may have, and it stops there.")

FX_SCHEMA = f"""Output format. Write each section after its tag, on the lines
below it. Use the tags exactly as written, one per line, in this order. No
JSON, no markdown, no wrapper.

Length: {WORDS_MIN:,} to {WORDS_MAX:,} words in total, headline excluded. Count
before you answer.

How to read the fact pack. Each row of "pairs" is a pair as quoted: "d1", "w1"
and "m1" are its move over one session, five sessions and 21 sessions, in
percent. A rise in USD/JPY is a stronger dollar; a rise in EUR/USD a weaker
one. "ccy_vs_usd" is the currency's own move against the dollar in percent,
positive when the currency gained: use it when comparing currencies, and say
which convention a figure is in. "z" is the day's move in standard deviations
of the last year. "main_moves" lists the pairs with the largest moves for
their own volatility: they lead the note. "levels" are the 1-month high and
low, the 50- and 200-day averages and the 52-week high and low; "nearest"
gives the closest level above and below the close and the distance in
percent, and under "at" any level the close sits on. "corr_ust2y_60d" is
the 60-session correlation of the pair's daily change with the US 2-year
yield's. "policy" is the central bank's rate as on file and "vs_fed_bp" its
differential to the top of the Fed's target range in basis points. "us_rates" holds the Fed range and the US 2-year and 10-year
yields with their moves in basis points.

Rules for the central bank context. State a policy rate, a decision or a
meeting date only if it is in the pack. If a row's "policy" is null, do not
give that bank's rate or describe its stance from memory; say at most that
its rate is not on file. Do not claim a central bank caused a move. Say what
the rate differential and the US front end did, and whether the pair moved
with them or against them.

===headline===
8 to 13 words. What the dollar did and the move that mattered, as a claim.

===standfirst===
Two sentences. The dollar's session and the cross that told the story.

===takeaways===
Four one-sentence conclusions, ordered by importance. One per line.

===dollar===
One or two paragraphs: the dollar index on the day, week and month, and the
US front end beside it.

===majors===
Two or three paragraphs: the G10 majors, led by the main moves, with each
pair's daily, weekly and monthly move where it matters.

===em===
Two paragraphs: the EM pairs, Asia apart from Latin America and EMEA, with
their moves on the day, week and month.

===drivers===
Two paragraphs: the rate differentials and central bank context behind the
main moves, and which pairs followed the US 2-year and which did not.

===levels===
One line per pair for six to eight pairs, starting with the main moves: the
close and the nearest levels above and below it from "levels". Plain
statement, no view on whether a level will hold.

===ahead===
One paragraph on the central bank meetings in "central_bank_meetings_ahead".
If it is empty, one sentence saying no meeting on file falls in the next two
weeks.
"""


def _complete(content: dict) -> dict:
    for f in FIELDS:
        content.setdefault(f, [] if f in LISTS else "")
    if not content.get("headline"):
        content["headline"] = "FX analysis"
    return content


def _call(client, messages: list[dict], meter: dict) -> dict:
    # Plain call: no thinking parameter, no temperature (CLAUDE.md).
    r = _metered(meter, client.messages.create, model=MODEL, max_tokens=MAX_TOKENS,
                 system=FX_SYSTEM, messages=messages)
    txt = "".join(getattr(b, "text", "") for b in r.content if b.type == "text").strip()
    if not txt:
        raise ValueError(f"reply carried no text (stop: {r.stop_reason}).")
    if r.stop_reason == "max_tokens":
        raise ValueError(f"reply hit the {MAX_TOKENS}-token ceiling and is truncated.")
    content = parse_reply(txt, FIELDS, LISTS)
    missing = [f for f in FIELDS if f not in content]
    if missing:
        raise ValueError(f"reply is incomplete: no {', '.join(missing)}.")
    return content


def _as_tagged(content: dict) -> str:
    return "\n\n".join(f"==={k}===\n" + ("\n".join(v) if isinstance(v, list) else v)
                       for k, v in content.items() if v)


def write(facts: dict, max_attempts: int = 3) -> Note:
    """The model writes the FX note. A draft with a figure not in the pack,
    a length outside 800 to 1,200 words or trade language goes back once
    more with the reason; after the last attempt the note ships flagged."""
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    messages = [{"role": "user", "content":
                 f"{FX_SCHEMA}\n\nVerified FX fact pack for the session. This is "
                 f"the only admissible source of figures:\n\n"
                 f"{json.dumps(facts, ensure_ascii=False, default=str)}"}]
    content, bad, last_error = {}, [], None
    usage = Note({}).usage
    for attempt in range(1, max_attempts + 1):
        try:
            content = _call(client, messages, usage)
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("FX attempt %d failed to produce a usable reply: %s", attempt, e)
            continue
        bad, words, flags = _problems(content, facts)
        if not bad and WORDS_MIN <= words <= WORDS_MAX and not flags:
            return Note(_complete(content), True, [], attempt, usage)
        log.warning("FX attempt %d: rejected figures %s, %d words, trade language %s",
                    attempt, bad, words, flags)
        asks = []
        if bad:
            asks.append(f"The figure check rejected these because they are not in "
                        f"the fact pack: {bad}. Remove them or use the value from the pack.")
        if not WORDS_MIN <= words <= WORDS_MAX:
            asks.append(f"The note is {words} words. It must be {WORDS_MIN:,} to "
                        f"{WORDS_MAX:,} words, headline excluded.")
        if flags:
            asks.append(f"These read as trade language and must go: {flags}. The "
                        f"note is neutral and gives no recommendation.")
        messages += [{"role": "assistant", "content": _as_tagged(content)},
                     {"role": "user", "content": " ".join(asks) + " Return the full "
                      "note again. Do not introduce any new figure."}]
    if content:
        return Note(_complete(content), not bad, bad, max_attempts, usage)
    err = RuntimeError(f"no usable FX reply after {max_attempts} attempts: {last_error}")
    err.usage = usage
    raise err


# ----------------------------------------------------- figures-only writing
def _pct(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{abs(v):.2f}%"


def _lvl(v: float, dec: int) -> str:
    return f"{v:,.{dec}f}"


_LEVEL_NAMES = {"high_1m": "1-month high", "low_1m": "1-month low",
                "ma50": "50-day average", "ma200": "200-day average",
                "high_52w": "52-week high", "low_52w": "52-week low"}


def level_lines(facts: dict, n: int = 8) -> list[str]:
    """One line per pair, main moves first: the close and the nearest levels
    either side, every figure as the pack holds it."""
    by_key = {p["key"]: p for p in facts["pairs"]}
    order = facts["main_moves"] + [p["key"] for p in facts["pairs"]
                                   if p["key"] not in facts["main_moves"]]
    out = []
    for k in order[:n]:
        p, dec = by_key[k], by_key[k]["dec"]
        parts = [f"{p['name']} closed at {_lvl(p['last'], dec)}"]
        if p["nearest"]["at"]:
            parts[0] += (", on its " + " and ".join(_LEVEL_NAMES[k] for k in p["nearest"]["at"]))
        for side, word in (("above", "above"), ("below", "below")):
            got = p["nearest"].get(side)
            if got:
                parts.append(f"the nearest level {word} is the "
                             f"{_LEVEL_NAMES[got['level']]} at {_lvl(got['value'], dec)}")
        out.append(", ".join(parts) + ".")
    return out


def write_without_model(facts: dict) -> Note:
    """A short note set from the figures alone, used when the model is
    unavailable (and in replays). It passes the figure check by construction
    and is shorter than the 800-word floor: the manifest says so."""
    by_key = {p["key"]: p for p in facts["pairs"]}
    dxy = by_key.get("dxy")
    d1 = facts["strength_vs_usd"]["d1"]
    head, stand = "FX analysis: quantitative read of the session", []
    if dxy and dxy["d1"] is not None:
        verb = "rose" if dxy["d1"] >= 0 else "fell"
        head = f"The dollar index {verb} {abs(dxy['d1']):.2f}% on the session"
        month = f" and {_pct(dxy['m1'])} on the month" if dxy["m1"] is not None else ""
        stand.append(f"The dollar index closed at {_lvl(dxy['last'], dxy['dec'])}, "
                     f"{_pct(dxy['d1'])} on the day{month}.")
    stand.append("Published in quantitative mode: the tables carry the session, "
                 "without commentary.")
    take = []
    if d1:
        take.append(f"{d1[0]['currency']} was the strongest currency against the "
                    f"dollar at {_pct(d1[0]['vs_usd'])} and {d1[-1]['currency']} the "
                    f"weakest at {_pct(d1[-1]['vs_usd'])}.")
    fed, two = facts["us_rates"]["fed"], facts["us_rates"]["ust2y"]
    drivers = ""
    if fed:
        drivers = f"The top of the Fed's target range is {fed['rate']:.2f}%."
    if two and two["d1_bp"] is not None:
        drivers += (f" The US 2-year yield closed at {two['last']:.2f}%, "
                    f"{two['d1_bp']:+.1f}bp on the day.")
    content = {"headline": head, "standfirst": " ".join(stand), "takeaways": take,
               "dollar": "", "majors": "", "em": "", "drivers": drivers.strip(),
               "levels": level_lines(facts), "ahead": ""}
    return Note(_complete(content), audit_ok=not audit(content, facts))


# -------------------------------------------------------------- site export
def to_site(facts: dict, note: Note, mode: str, edition, pdf_name: str) -> dict:
    """fx_YYYYMMDD.json, the file the site imports for its FX section."""
    c = note.content
    return {
        "schema": SCHEMA_ID,
        "date": facts["date"],
        "edition": edition,
        "mode": mode,
        "headline": c.get("headline", ""),
        "standfirst": c.get("standfirst", ""),
        "takeaways": list(c.get("takeaways", [])),
        "sections": [{"id": sid, "title": title,
                      "paragraphs": (list(c.get(sid) or []) if sid in LISTS else
                                     [p for p in (c.get(sid) or "").split("\n\n") if p.strip()])}
                     for sid, title in SECTIONS],
        "word_count": word_count(c),
        "audit": {"ok": note.audit_ok, "unsupported": note.unsupported,
                  "attempts": note.attempts},
        "trade_language_flags": advice_flags(c),
        "pdf": pdf_name,
        "facts": facts,
    }
