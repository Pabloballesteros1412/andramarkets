"""Composition of the daily FX analysis: one A4 note in the house style.

Same stylesheet, filters and exhibit engine as the close note. The note
flows across as many pages as the text needs (continuous flow, sections kept
whole with break-inside: avoid).
"""
from __future__ import annotations

import datetime as dt
import os

from . import charts
from .fx import SECTIONS
from .render import TPL, _b64, _env, _print_pdf, f_chg, f_dir, f_lvl

KPI = ("dxy", "eurusd", "usdjpy", "usdcny")


def build_exhibits(facts: dict, tmp: str) -> dict[str, str]:
    charts.house_style()
    p = lambda n: os.path.join(tmp, f"{n}.png")  # noqa: E731
    ex = {}
    rows = [r for r in facts["pairs"] if r["ccy_vs_usd"]]
    for h, size in (("d1", (3.15, 2.9)), ("m1", (3.15, 2.9))):
        got = [r for r in rows if r["ccy_vs_usd"][h] is not None]
        if got:
            ex[h] = _b64(charts.bars_ranked([r["currency"] for r in got],
                                            [r["ccy_vs_usd"][h] for r in got],
                                            p(f"fx_{h}"), size=size))
    return ex


def _row(r: dict) -> dict:
    """A pair shaped for the house table macro (chg is the session move)."""
    return {**r, "chg": r["d1"], "unit": "px"}


def build_context(facts: dict, note, ex: dict, edition="") -> dict:
    d = dt.date.fromisoformat(facts["date"])
    pairs = facts["pairs"]
    by_key = {r["key"]: r for r in pairs}
    us = facts["us_rates"]
    kpi = [{"label": by_key[k]["name"], "value": f_lvl(by_key[k]["last"], by_key[k]["dec"]),
            "chg": f_chg(by_key[k]["d1"]), "dir": f_dir(by_key[k]["d1"])}
           for k in KPI if k in by_key]
    if us.get("ust2y"):
        kpi.append({"label": "US 2-year", "value": f_lvl(us["ust2y"]["last"], 2, "pct"),
                    "chg": f_chg(us["ust2y"]["d1_bp"], "pct"), "dir": f_dir(us["ust2y"]["d1_bp"])})
    banks = [{"currency": r["currency"], **r["policy"]} for r in pairs if r.get("policy")]
    fed = us.get("fed")
    c = note.content
    return {
        "css": (TPL / "styles.css").read_text(encoding="utf-8"),
        "n": c, "audit_ok": note.audit_ok,
        "sections": [{"id": sid, "title": title, "body": c.get(sid)} for sid, title in SECTIONS],
        "date_long": d.strftime("%B %-d, %Y"),
        "date_short": d.strftime("%d %b %Y"),
        "published": dt.datetime.now().strftime("%H:%M CET"),
        "edition": edition if isinstance(edition, str) else f"{edition:04d}",
        "kpi": kpi,
        "dollar": [_row(r) for r in pairs if r["group"] == "dollar"],
        "majors": [_row(r) for r in pairs if r["group"] == "major"],
        "em": [_row(r) for r in pairs if r["group"] == "em"],
        "levels": pairs,
        "banks": banks, "fed": fed,
        "banks_not_on_file": facts["banks_not_on_file"],
        "banks_out_of_date": facts["banks_out_of_date"],
        "pairs_without_print": facts["pairs_without_print"],
        "ex": ex,
    }


def report_pdf(ctx: dict, out: str) -> str:
    return _print_pdf(_env().get_template("fx.html.j2").render(**ctx), out, format="A4")
