"""Composition of the weekly review: the A4 note and the LinkedIn carousel.

Same house style as the daily close: the same stylesheet, table macro,
exhibit engine and social frames. Only the content differs: weekly moves
(last close of the week against the previous week's), the S&P 500 day by
day, the week's releases and earnings, and next week's events.
"""
from __future__ import annotations

import datetime as dt
import os

from . import charts
from .render import TPL, _b64, _env, _print_pdf, f_chg, f_dir, f_lvl
from .universe import all_instruments

# The page-one summary, in this order when present.
SUMMARY = ("spx", "ndx", "dji", "rut", "sx5e", "nky", "ust2y", "ust10y",
           "dxy", "eurusd", "usdjpy", "wti", "gold", "vix", "btc")
TAPE = ("spx", "ndx", "rut", "ust10y", "dxy", "gold", "wti", "btc")


def _rows(facts: dict) -> dict[str, list[dict]]:
    """Weekly moves shaped for the daily note's table macro: `chg` holds the
    week's move, `unit` is the instrument's (pct for rates, in bp)."""
    meta = {i.key: i for i in all_instruments()}
    out = {}
    for block, rows in facts["moves"].items():
        out[block] = [{**r, "chg": r["week"],
                       "unit": "pct" if r["unit"] == "bp" else "px",
                       "dec": meta[r["key"]].dec if r["key"] in meta else 2}
                      for r in rows]
    return out


def build_exhibits(facts: dict, tmp: str) -> dict[str, str]:
    charts.house_style()
    p = lambda n: os.path.join(tmp, f"{n}.png")  # noqa: E731
    ex = {}
    idx = [r for b in ("us_equity", "europe", "apac", "americas") for r in facts["moves"][b]]
    if idx:
        ex["indices"] = _b64(charts.bars_ranked([r["name"] for r in idx],
                                                [r["week"] for r in idx], p("idx"),
                                                size=(3.15, 4.3)))
    sec = facts["moves"].get("sectors", [])
    if sec:
        ex["sectors"] = _b64(charts.bars_ranked([r["name"] for r in sec],
                                                [r["week"] for r in sec], p("sec"),
                                                size=(3.15, 2.7)))
    # The week's closes, from the previous week's last close.
    spx = next((r for r in facts["moves"].get("us_equity", []) if r["key"] == "spx"), None)
    line = ([spx["prior_week"]] if spx else []) + [r["last"] for r in facts["spx_path"]]
    if len(line) >= 2:
        ex["spx_line"] = _b64(charts.social_spark(
            line, p("spx_l"), size=(13, 3.3), color="#FFFFFF", lw=5.0))
    return ex


def build_context(facts: dict, note, ex: dict, edition: str = "") -> dict:
    end = dt.date.fromisoformat(facts["week"]["end"])
    start = dt.date.fromisoformat(facts["week"]["start"])
    rows = _rows(facts)
    by_key = {r["key"]: r for block in rows.values() for r in block}
    days = [{"day": dt.date.fromisoformat(r["date"]).strftime("%a %-d %b"),
             "last": f_lvl(r["last"]), "chg": f_chg(r["chg"]), "dir": f_dir(r["chg"])}
            for r in facts["spx_path"]]
    peak = max((abs(r["chg"]) for b in ("sectors",) for r in rows.get(b, [])), default=1) or 1
    sectors = [{"name": r["name"], "value": f_chg(r["chg"]), "dir": "pos" if r["chg"] >= 0 else "neg",
                "side": "left" if r["chg"] >= 0 else "right",
                "width": round(abs(r["chg"]) / peak * 48, 1)}
               for r in sorted(rows.get("sectors", []), key=lambda r: -r["chg"])]
    spx = by_key.get("spx")
    hero = ({"value": f_chg(spx["chg"]), "label": "S&P 500, week", "dir": f_dir(spx["chg"]),
             "note": f"Closed the week at {f_lvl(spx['last'])}."} if spx else None)
    missing = facts["week"]["missing"]
    return {
        "css": (TPL / "styles.css").read_text(encoding="utf-8"),
        "social_css": (TPL / "social.css").read_text(encoding="utf-8"),
        "n": note.content, "audit_ok": note.audit_ok,
        "week_long": f"Week ending {end:%B} {end.day}, {end.year}",
        "week_span": (f"{start.day} {start:%b} to {end.day} {end:%b %Y}"),
        "date_short": end.strftime("%d %b %Y"),
        "edition": edition or f"W{end.isocalendar()[1]:02d}",
        "published": dt.datetime.now().strftime("%H:%M CET"),
        "summary": [by_key[k] for k in SUMMARY if k in by_key],
        "t": rows,
        "days": days,
        "sectors": sectors,
        "hero": hero,
        "tape": [{"name": by_key[k]["name"],
                  "last": f_lvl(by_key[k]["last"], by_key[k]["dec"], by_key[k]["unit"]),
                  "chg": f_chg(by_key[k]["chg"], by_key[k]["unit"]),
                  "dir": f_dir(by_key[k]["chg"])} for k in TAPE if k in by_key],
        "best": facts["indices_best"], "worst": facts["indices_worst"],
        "macro": facts["macro"], "earnings": facts["earnings"],
        "ahead": facts["week_ahead"], "calendar_source": facts["calendar_source"],
        "missing": missing,
        "left_out": facts["week"].get("left_out", []),
        "prior_close": facts["week"]["prior_close"],
        "prior_close_from": facts["week"]["prior_close_from"],
        "last_session": facts["week"]["last_session"],
        "ex": ex,
    }


def report_pdf(ctx: dict, out: str) -> str:
    return _print_pdf(_env().get_template("weekly.html.j2").render(**ctx), out, format="A4")


def linkedin_pdf(ctx: dict, out: str) -> str:
    return _print_pdf(_env().get_template("weekly_linkedin.html.j2").render(**ctx), out)


def linkedin_caption(note, ctx: dict) -> str:
    from .social import HASHTAGS, LIMIT, bold
    body = (note.content.get("linkedin") or "").strip()
    if not body:
        body = "\n\n".join([note.content.get("standfirst", ""), *note.content.get("takeaways", [])[:3]])
    header = bold(f"WEEKLY MARKET REVIEW / {ctx['date_short'].upper()}")
    tail = "Full review in the attached document.\n\nInformation only. Not investment advice."
    return f"{header}\n\n{body}\n\n{tail}\n\n{HASHTAGS}"[:LIMIT]
