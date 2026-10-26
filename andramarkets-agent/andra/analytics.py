"""Market read derived from the MarketFrame.

Everything the note asserts in prose has to be derivable here. The language
model writes; it does not calculate and it does not estimate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import MarketFrame
from .universe import fx_only_keys

# (key, field, sign). Sign is +1 when a rise means risk appetite.
BAROMETER = [
    ("spx", "chg", +1), ("rut", "chg", +1), ("vix", "chg", -1),
    ("hyg", "chg", +1), ("lqd", "chg", +1), ("gold", "chg", -1),
    ("dxy", "chg", -1), ("usdjpy", "chg", +1), ("copper", "chg", +1),
    ("btc", "chg", +1), ("emb", "chg", +1), ("move", "chg", -1),
]

LABELS = [(-2.0, "Sharp risk off"), (-1.0, "Risk off"), (-0.35, "Defensive"),
          (0.35, "Neutral"), (1.0, "Constructive"), (2.0, "Risk on"),
          (99.0, "Stretched risk on")]


def risk_barometer(mf: MarketFrame) -> dict:
    pts, detail = [], []
    for key, field, sign in BAROMETER:
        v = mf.get(key, field)
        if v is None or key not in mf.px:
            continue
        hist = mf.px[key].pct_change().dropna().tail(252) * 100
        sd = float(hist.std()) if len(hist) > 30 else None
        if not sd:
            continue
        z = float(np.clip(sign * v / sd, -3, 3))
        pts.append(z)
        detail.append({"component": key, "contribution": round(z, 2)})
    score = float(np.mean(pts)) if pts else 0.0
    return {"score": round(score, 2),
            "label": next(l for u, l in LABELS if score < u),
            "n": len(pts),
            "pos": round((score + 3) / 6 * 100, 1),
            "ticks": [{"pos": round((i + 3) / 6 * 100, 1), "mid": i == 0}
                      for i in range(-3, 4)],
            "detail": sorted(detail, key=lambda d: d["contribution"])}


def breadth(mf: MarketFrame, block: str = "watchlist") -> dict:
    d = mf.block(block)
    if d.empty:
        return {"advancers": 0, "decliners": 0, "unchanged": 0,
                "ratio": None, "dispersion": 0.0}
    adv = int((d["chg"] > 0.05).sum())
    dec = int((d["chg"] < -0.05).sum())
    return {"advancers": adv, "decliners": dec,
            "unchanged": int(len(d) - adv - dec),
            "ratio": round(adv / dec, 2) if dec else None,
            "dispersion": round(float(d["chg"].std()), 2)}


def curve(mf: MarketFrame) -> dict:
    lvl = lambda k: mf.get(k, "last")   # noqa: E731
    d1 = lambda k: mf.get(k, "chg")     # noqa: E731
    out: dict = {}
    for name, short, long in (("2s10s", "ust2y", "ust10y"),
                              ("5s30s", "ust5y", "ust30y"),
                              ("3m10y", "ust3m", "ust10y")):
        a, b = lvl(short), lvl(long)
        if a is not None and b is not None:
            out[name] = {"bp": round((b - a) * 100, 1),
                         "delta": round((d1(long) or 0) - (d1(short) or 0), 1)}
    out["level"] = {k: lvl(k) for k in ("ust2y", "ust5y", "ust10y", "ust30y")
                    if lvl(k) is not None}
    out["shift"] = {k: d1(k) for k in ("ust2y", "ust5y", "ust10y", "ust30y")
                    if d1(k) is not None}
    if out["shift"]:
        v = list(out["shift"].values())
        out["move_type"] = ("parallel shift" if max(v) - min(v) < 3 else
                            "bear steepening" if v[-1] > v[0] else "flattening")
    return out


def movers(mf: MarketFrame, block: str = "watchlist", n: int = 5) -> dict:
    d = mf.block(block).sort_values("chg", ascending=False)
    cols = ["name", "last", "chg", "ytd"]
    return {"leaders": d.head(n)[cols].reset_index().to_dict("records"),
            "laggards": d.tail(n)[cols].iloc[::-1].reset_index().to_dict("records")}


def fresh_extremes(mf: MarketFrame, tol: float = 0.005) -> dict:
    # The FX analysis's own pairs and policy rates are not part of the close
    # note's universe.
    s = mf.snap.drop(list(fx_only_keys()), errors="ignore")
    if s.empty:
        return {"highs": [], "lows": []}
    return {"highs": s[s["last"] >= s["high52"] * (1 - tol)]["name"].tolist()[:10],
            "lows": s[s["last"] <= s["low52"] * (1 + tol)]["name"].tolist()[:10]}


def cross_correlation(mf: MarketFrame, keys: list[str], n: int = 60) -> pd.DataFrame:
    keys = [k for k in keys if k in mf.px.columns]
    return mf.px[keys].pct_change().tail(n).corr().round(2)


def horizon_matrix(mf: MarketFrame, keys: list[str]):
    cols = ["1D", "1W", "1M", "3M", "YTD"]
    fields = ["chg", "w1", "m1", "m3", "ytd"]
    rows, data = [], []
    for k in keys:
        if k not in mf.snap.index:
            continue
        rows.append(str(mf.snap.at[k, "name"]))
        data.append([float(mf.snap.at[k, f]) if pd.notna(mf.snap.at[k, f]) else 0.0
                     for f in fields])
    return rows, cols, data


def fact_pack(mf: MarketFrame) -> dict:
    """The verified facts handed to the writer. Nothing else is admissible.

    Any figure that appears in the note must exist in this structure. That is
    the contract that makes the prose auditable.
    """
    target = mf.asof.isoformat()

    def blk(name, cols=("name", "last", "chg", "ytd", "date", "time")):
        d = mf.block(name)
        if d.empty:
            return []
        rows = d[list(cols)].round(3).reset_index().to_dict("records")
        for r in rows:
            # A row whose print is not from the session reported on (a market
            # closed that day, a late or missing print) is flagged, so the
            # reader of the facts can hold a note that mixes dates.
            r["off_session"] = r["date"] != target
        return rows

    blocks = {name: blk(name) for name in (
        "us_equity", "sectors", "europe", "apac", "americas", "curve",
        "breakevens", "credit", "fx", "commodities", "volatility", "digital")}
    off = sorted(r["key"] for rows in blocks.values() for r in rows if r["off_session"])

    return {
        "date": target,
        "risk_barometer": risk_barometer(mf),
        "breadth": breadth(mf),
        "curve": curve(mf),
        "movers": movers(mf),
        "extremes": fresh_extremes(mf),
        "us_equity": blocks["us_equity"], "sectors": blocks["sectors"],
        "europe": blocks["europe"], "apac": blocks["apac"],
        "americas": blocks["americas"],
        "treasury_curve": blocks["curve"], "breakevens": blocks["breakevens"],
        "credit": blocks["credit"], "fx": blocks["fx"],
        "commodities": blocks["commodities"], "volatility": blocks["volatility"],
        "digital": blocks["digital"],
        "series_without_print": mf.missing,
        "series_not_yet_published": getattr(mf, "stale", []),
        # Every row above whose own print date is not `date`.
        "series_off_session": off,
    }
