"""Composition and output.

Laid out in HTML/CSS and printed with headless Chromium. That is what buys
editorial-grade typographic control (half-point rules, tabular figures, a
millimetre grid) without leaving Python.

Three deliverables per session:
  · A4 research note, 5 pages
  · LinkedIn document carousel, 8 pages at 1200 x 1500
  · TikTok photo carousel, 7 PNG stills at 1080 x 1920
"""
from __future__ import annotations

import base64
import datetime as dt
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import charts
from .analytics import (breadth, cross_correlation, curve, horizon_matrix,
                        movers, risk_barometer)

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates"


# ------------------------------------------------------------ jinja filters
def f_num(v, dec=2):
    if v is None or v != v:
        return "n/a"
    return f"{float(v):,.{int(dec)}f}"


def f_chg(v, unit="px"):
    """Session or period change. Rates in basis points, everything else in %."""
    if v is None or v != v:
        return "n/a"
    sign = "+" if v >= 0 else "\u2212"
    if unit == "pct":
        dec = 1 if abs(v) < 2 else 0
        return f"{sign}{f_num(abs(v), dec)} bp"
    return f"{sign}{f_num(abs(v), 2)}%"


def f_bp(v):
    if v is None or v != v:
        return "n/a"
    return f"{'+' if v >= 0 else '−'}{f_num(abs(v), 1)} bp"


def f_lvl(v, dec=2, unit="px"):
    if v is None or v != v:
        return "n/a"
    return f"{f_num(v, 2)}%" if unit == "pct" else f_num(v, dec)


def f_dir(v):
    if v is None or v != v:
        return "nil"
    return "pos" if v > 0.005 else ("neg" if v < -0.005 else "nil")


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TPL)),
                      autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(num=f_num, chg=f_chg, bp=f_bp, lvl=f_lvl, dir=f_dir)
    return env


def _b64(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


# ----------------------------------------------------------------- exhibits
def build_exhibits(mf, tmp: str) -> dict[str, str]:
    charts.house_style()
    ex: dict[str, str] = {}
    p = lambda n: os.path.join(tmp, f"{n}.png")  # noqa: E731

    picks = [("spx", "S&P 500"), ("sx5e", "EURO STOXX 50"),
             ("nky", "Nikkei 225"), ("hsi", "Hang Seng"), ("ibov", "Bovespa")]
    series, x = {}, None
    for k, label in picks:
        if k in mf.px.columns:
            s = mf.series(k, 60)
            if len(s) > 10:
                series[label] = s.values
                x = [d.strftime("%d %b") for d in s.index]
    if series:
        ex["regions"] = _b64(charts.line_rebased(series, x, p("regions"), size=(10.6, 1.36), base_label=None))

    sec = mf.block("sectors")
    if not sec.empty:
        names, vals = sec["name"].tolist(), sec["chg"].tolist()
        ex["sectors"] = _b64(charts.bars_ranked(names, vals, p("sec"), size=(3.15, 2.6)))
        ex["sectors_sq"] = _b64(charts.bars_ranked(names, vals, p("sec_sq"), size=(7.6, 5.2)))
        ex["sectors_tt"] = _b64(charts.bars_ranked(names, vals, p("sec_tt"), size=(7.2, 6.4)))

    b = breadth(mf)
    ex["breadth"] = _b64(charts.breadth_bar(b["advancers"], b["decliners"],
                                            b["unchanged"], p("breadth")))

    c = mf.block("curve")
    if not c.empty:
        tenors = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
        today = c["last"].tolist()
        prior = [t - (w or 0) / 100 for t, w in zip(today, c["w1"].fillna(0).tolist())]
        tenors = tenors[:len(today)]
        ex["curve"] = _b64(charts.yield_curve(tenors, today, prior, p("curve"), size=(3.2, 2.9)))
        ex["curve_sq"] = _b64(charts.yield_curve(tenors, today, prior, p("curve_sq"), size=(7.6, 4.3)))

    cr = mf.block("credit")
    if not cr.empty:
        start = [float(l) / (1 + (w or 0) / 100) for l, w in zip(cr["last"], cr["w1"].fillna(0))]
        ex["credit"] = _b64(charts.dumbbell(cr["name"].tolist(), start,
                                            cr["last"].tolist(), p("credit"),
                                            size=(3.15, 4.6), unit="%"))

    fx = mf.block("fx")
    if not fx.empty:
        ex["fx"] = _b64(charts.bars_ranked(fx["name"].tolist(), fx["chg"].tolist(),
                                           p("fx"), size=(3.15, 3.3)))
    cm = mf.block("commodities")
    if not cm.empty:
        ex["commodities"] = _b64(charts.bars_ranked(cm["name"].tolist(), cm["chg"].tolist(),
                                                    p("cmd"), size=(3.15, 3.6)))
    if "vix" in mf.px.columns:
        s = mf.series("vix", 120)
        lab = [d.strftime("%d %b") for d in s.index]
        ex["vix"] = _b64(charts.area_vol(lab, s.values, p("vix")))
        ex["vix_sq"] = _b64(charts.area_vol(lab, s.values, p("vix_sq"), size=(7.6, 4.2)))

    if {"real10y", "be10y"} <= set(mf.px.columns):
        a, bb = mf.series("real10y", 120), mf.series("be10y", 120)
        if len(a) > 20 and len(bb) > 20:
            ex["real"] = _b64(charts.dual_axis([d.strftime("%d %b") for d in a.index],
                                               ("10-year real yield", a.values),
                                               ("10-year breakeven", bb.values),
                                               p("real"), size=(3.15, 2.2)))

    corr = cross_correlation(mf, ["spx", "ndx", "ust10y", "dxy", "gold",
                                  "wti", "btc", "hyg"], 60)
    if not corr.empty:
        labels = [str(mf.snap.at[k, "name"]) for k in corr.columns]
        ex["correlation"] = _b64(charts.corr_matrix(labels, corr.values, p("corr"),
                                                    size=(3.15, 1.95)))

    # --- social art: one continuous line per carousel, plus the bare curve ---
    if "spx" in mf.px.columns:
        path = mf.series("spx", 260).values
        for tag, w, h in (("tt", 7 * 1080, 770), ("li", 8 * 1200, 620)):
            ex[f"ribbon_{tag}_dark"] = _b64(charts.ribbon(
                path, p(f"rb_{tag}_d"), w, h, colour=charts.INK))
            ex[f"ribbon_{tag}_light"] = _b64(charts.ribbon(
                path, p(f"rb_{tag}_l"), w, h, colour="#FFFFFF"))

    if not c.empty:
        ex["curve_bare"] = _b64(charts.curve_bare(tenors, today, prior,
                                                  p("cb_tt"), 1080, 360,
                                                  colour="#FFFFFF", ghost="#6E6E6E"))
        ex["curve_bare_li"] = _b64(charts.curve_bare(tenors, today, prior,
                                                     p("cb_li"), 1200, 300,
                                                     colour="#FFFFFF", ghost="#6E6E6E"))

    rows, cols, data = horizon_matrix(mf, ["spx", "ndx", "sx5e", "nky",
                                           "ust10y", "gold", "wti", "btc"])
    if rows:
        ex["heatmap"] = _b64(charts.heat_matrix(rows, cols, data, p("heat"), size=(7.6, 1.14)))
    return ex


# ------------------------------------------------------------------ context
def _curve_note(cur: dict) -> str:
    shift = cur.get("shift") or {}
    if not shift:
        return "No computable curve shift this session."
    names = {"ust2y": "the 2-year", "ust5y": "the 5-year",
             "ust10y": "the 10-year", "ust30y": "the 30-year"}
    mx = max(shift, key=lambda k: abs(shift[k]))
    return (f"The curve saw a {cur.get('move_type', 'shift')}. "
            f"{names.get(mx, mx).capitalize()} moved most at {f_bp(shift[mx])}. "
            f"The spread between the largest and smallest move across the curve "
            f"was {f_num(max(shift.values()) - min(shift.values()), 1)} bp.")


def _hero(mf, bar: dict) -> dict:
    """The one number the social posts lead with."""
    spx = mf.get("spx", "chg")
    if spx is not None:
        return {"value": f_chg(spx), "label": "S&P 500, session close",
                "note": f"Cross-asset risk score at {bar['score']:.2f}, "
                        f"read as {bar['label'].lower()}."}
    return {"value": f"{bar['score']:.2f}", "label": "Cross-asset risk score",
            "note": bar["label"]}


def _sector_rows(mf) -> list[dict]:
    """Sector moves as full-bleed rows. The bar is the row, not a chart."""
    d = mf.block("sectors")
    if d.empty:
        return []
    d = d.sort_values("chg", ascending=False)
    span = float(max(abs(d["chg"].max()), abs(d["chg"].min())) or 1)
    return [{"name": r["name"], "value": f_chg(r["chg"]),
             "dir": f_dir(r["chg"]),
             "width": round(18 + 82 * abs(r["chg"]) / span, 1)}
            for r in d.reset_index().to_dict("records")]


def _social_pack(mf, note, tmp: str, hero: dict) -> dict:
    """Everything the carousels need, shaped for type rather than for plots.

    Sector bars and the tape are handed over as widths and formatted strings so
    the templates can set them in CSS. Only two pieces of line art get plotted,
    both untitled: the labels live in the HTML.
    """
    charts.house_style()
    p = lambda n: os.path.join(tmp, f"{n}.png")  # noqa: E731
    pack: dict = {"hero": hero}

    if "spx" in mf.px.columns:
        y = mf.series("spx", 60).values
        pack["spark_light"] = _b64(charts.social_spark(
            y, p("spark_l"), size=(13, 3.3), color="#FFFFFF", lw=5.0))
        pack["spark_dark"] = _b64(charts.social_spark(
            y, p("spark_d"), size=(13, 3.3), color=charts.INK, lw=5.0))
        # Ornament: the last twenty sessions of the S&P, used in place of a
        # rule on the pull frames. The mark is different every day because the
        # market is different every day.
        tail = y[-20:]
        pack["mark_light"] = _b64(charts.social_spark(
            tail, p("mark_l"), size=(4.2, .85), color="#FFFFFF", lw=3.4))
        pack["mark_dark"] = _b64(charts.social_spark(
            tail, p("mark_d"), size=(4.2, .85), color=charts.INK, lw=3.4))

    c = mf.block("curve")
    if not c.empty:
        pack["curve_img"] = _b64(charts.social_curve(
            c["last"].tolist(), p("curve_s"), size=(11, 3.6), color=charts.INK, lw=5.5))
        pack["tenors"] = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y",
                          "10Y", "20Y", "30Y"][:len(c)]

    sec = mf.block("sectors")
    if not sec.empty:
        peak = max(abs(float(v)) for v in sec["chg"]) or 1.0
        pack["sectors"] = [
            {"name": r["name"], "value": f_chg(r["chg"]),
             "dir": "pos" if r["chg"] >= 0 else "neg",
             "side": "left" if r["chg"] >= 0 else "right",
             "width": round(abs(float(r["chg"])) / peak * 48, 1)}
            for r in sec.sort_values("chg", ascending=False)
                       .reset_index().to_dict("records")]

    tape_keys = ["spx", "ndx", "rut", "ust10y", "dxy", "gold", "wti", "btc"]
    pack["tape"] = [
        {"name": str(mf.snap.at[k, "name"]),
         "last": f_lvl(mf.snap.at[k, "last"], int(mf.snap.at[k, "dec"]),
                       str(mf.snap.at[k, "unit"])),
         "chg": f_chg(mf.snap.at[k, "chg"], str(mf.snap.at[k, "unit"])),
         "dir": f_dir(mf.snap.at[k, "chg"])}
        for k in tape_keys if k in mf.snap.index]

    desk = (note.content.get("desk_view") or "").split("\n\n")
    pack["desk_line"] = desk[0] if desk and desk[0] else note.content.get("standfirst", "")
    return pack


def build_context(mf, note, ex, calendar=None, edition=1, social_tmp=None) -> dict:
    d = mf.asof
    bar = risk_barometer(mf)
    cur = curve(mf)

    sec = mf.block("sectors")
    if not sec.empty:
        best, worst = sec.loc[sec["chg"].idxmax()], sec.loc[sec["chg"].idxmin()]
        rotation = (f"{best['name']} led at {f_chg(best['chg'])} and "
                    f"{worst['name']} finished last at {f_chg(worst['chg'])}, "
                    f"a spread of {f_num(best['chg'] - worst['chg'], 2)} "
                    f"percentage points between the two ends.")
    else:
        rotation = "No sector detail available in this edition."

    snap = mf.snap.reset_index().to_dict("records") if not mf.snap.empty else []
    fx, cmd = mf.rows("fx"), mf.rows("commodities")

    hero = _hero(mf, bar)
    hero["dir"] = f_dir(mf.get("spx", "chg"))

    return {
        "css": (TPL / "styles.css").read_text(encoding="utf-8"),
        "social_css": (TPL / "social.css").read_text(encoding="utf-8"),
        "s": _social_pack(mf, note, social_tmp or ".", hero),
        "n": note.content,
        "audit_ok": note.audit_ok,
        "date_long": d.strftime("%B %-d, %Y"),
        "date_short": d.strftime("%d %b %Y"),
        "published": dt.datetime.now().strftime("%H:%M CET"),
        "edition": edition if isinstance(edition, str) else f"{edition:04d}",
        "pages": 5,
        "barometer": bar,
        "breadth": breadth(mf),
        "movers": movers(mf),
        "slopes": [{"name": k, "bp": v["bp"], "delta": v["delta"]}
                   for k, v in cur.items() if isinstance(v, dict) and "bp" in v],
        "curve_note": _curve_note(cur),
        "rotation": rotation,
        "hero": hero,
        "sector_rows": _sector_rows(mf),
        "ribbon": {"dark": ex.get("ribbon_tt_dark", ""),
                   "light": ex.get("ribbon_tt_light", ""),
                   "width": 7 * 1080, "height": 770},
        "ribbon_li": {"dark": ex.get("ribbon_li_dark", ""),
                      "light": ex.get("ribbon_li_light", ""),
                      "width": 8 * 1200, "height": 620},
        "calendar": calendar or [],
        "missing_series": len(mf.missing),
        "ex": ex,
        "t": {
            "summary_equity": [r for r in snap if r.get("summary") == "equity"],
            "summary_macro": [r for r in snap if r.get("summary") == "macro"],
            "us_equity": mf.rows("us_equity"),
            "europe": mf.rows("europe")[:8], "apac": mf.rows("apac")[:8],
            "americas": mf.rows("americas")[:5],
            "curve": mf.rows("curve"), "breakevens": mf.rows("breakevens"),
            "sovereigns": mf.rows("sovereigns"), "credit": mf.rows("credit"),
            "fx": fx, "fx_top": fx[:6],
            "commodities": cmd, "commodities_top": cmd[:6],
            "volatility": mf.rows("volatility"), "digital": mf.rows("digital"),
        },
    }


# ---------------------------------------------------------------- rendering
def _print_pdf(html: str, out: str, css_page: bool = True, **kw) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.emulate_media(media="print")
        page.pdf(path=out, print_background=True, prefer_css_page_size=css_page,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}, **kw)
        browser.close()
    return out


def report_pdf(ctx: dict, out: str) -> str:
    return _print_pdf(_env().get_template("report.html.j2").render(**ctx), out, format="A4")


def linkedin_pdf(ctx: dict, out: str) -> str:
    return _print_pdf(_env().get_template("linkedin.html.j2").render(**ctx), out)


def tiktok_images(ctx: dict, out_dir: str, stem: str) -> list[str]:
    """TikTok takes stills, not documents. One PNG per slide, 1080 x 1920."""
    from playwright.sync_api import sync_playwright
    html = _env().get_template("tiktok.html.j2").render(**ctx)
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920},
                                device_scale_factor=1)
        page.set_content(html, wait_until="load")
        for i, el in enumerate(page.query_selector_all(".f"), start=1):
            path = os.path.join(out_dir, f"{stem}_{i:02d}.png")
            el.screenshot(path=path)
            paths.append(path)
        browser.close()
    return paths
