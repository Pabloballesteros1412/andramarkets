"""Deterministic synthetic data.

Two jobs: show the finished document without credentials, and act as a visual
regression bench (same seed, same PDF apart from the date).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from andra.data import MarketFrame, snapshot
from andra.narrative import Note
from andra.universe import all_instruments

LEVELS = {
    "spx": (6420, .0082), "ndx": (23480, .0104), "dji": (46180, .0071),
    "rut": (2438, .0118), "mid": (3395, .0092), "nya": (21740, .0068),
    "xlk": (272, .0118), "xlf": (54.2, .0088), "xlv": (152, .0079),
    "xly": (232, .0104), "xlp": (81.4, .0055), "xle": (94.6, .0136),
    "xli": (147, .0083), "xlb": (91.8, .0097), "xlre": (43.6, .0091),
    "xlu": (84.9, .0084), "xlc": (108, .0102),
    "sx5e": (5612, .0088), "dax": (24310, .0092), "cac": (8074, .0089),
    "ftse": (9412, .0071), "ibex": (15840, .0094), "mib": (42180, .0098),
    "smi": (12760, .0069), "aex": (958, .0086),
    "nky": (43620, .0112), "topix": (3086, .0098), "hsi": (26140, .0134),
    "csi300": (4382, .0119), "kospi": (3184, .0121), "sensex": (84960, .0086),
    "asx": (8916, .0074), "twii": (24380, .0126),
    "ibov": (142800, .0128), "mexbol": (59840, .0096), "merval": (2148000, .0212),
    "ipsa": (8940, .0091), "tsx": (28640, .0071),
    "be5y": (2.44, .012), "be10y": (2.36, .010), "fwd5y5y": (2.29, .011),
    "real10y": (1.80, .022),
    "bund10": (2.68, .019), "oat10": (3.34, .018), "btp10": (3.72, .017),
    "bono10": (3.16, .017), "gilt10": (4.42, .019), "jgb10": (1.74, .024),
    "lqd": (112.4, .0042), "hyg": (81.9, .0034), "jnk": (98.2, .0035),
    "emb": (94.6, .0041), "bkln": (21.3, .0016), "tlt": (89.4, .0092),
    "ief": (96.8, .0038),
    "dxy": (97.86, .0038), "eurusd": (1.1642, .0042), "usdjpy": (146.32, .0046),
    "gbpusd": (1.3418, .0044), "usdchf": (0.7962, .0040), "usdcad": (1.3684, .0031),
    "audusd": (0.6584, .0052), "usdcnh": (7.1284, .0018), "usdmxn": (18.42, .0062),
    "usdbrl": (5.386, .0071), "usdtry": (42.68, .0028), "usdinr": (87.42, .0022),
    "wti": (66.84, .0182), "brent": (70.42, .0174), "natgas": (3.184, .0342),
    "gold": (3486.0, .0092), "silver": (39.86, .0164), "copper": (4.6820, .0138),
    "platinum": (1284.0, .0158), "palladium": (1142.0, .0186),
    "aluminium": (2684.0, .0112), "wheat": (5.42, .0148), "corn": (4.16, .0126),
    "soybean": (10.42, .0118), "coffee": (312.4, .0224), "cocoa": (7840.0, .0268),
    "sugar": (16.84, .0164),
    "vix": (16.42, .0684), "vix9d": (14.86, .0812), "vix3m": (18.92, .0492),
    "vvix": (92.4, .0424), "skew": (146.2, .0184), "move": (84.6, .0362),
    "vstoxx": (17.24, .0592), "rvx": (21.86, .0562),
    "btc": (118400.0, .0248), "eth": (4386.0, .0312), "sol": (218.4, .0384),
    "xrp": (2.8420, .0342),
}
STOCKS = {
    "AAPL": 238, "MSFT": 542, "NVDA": 186, "AMZN": 246, "GOOGL": 214,
    "META": 782, "TSLA": 348, "AVGO": 342, "BRK-B": 512, "LLY": 812,
    "JPM": 312, "XOM": 118, "V": 386, "UNH": 298, "COST": 968, "WMT": 108,
    "NFLX": 1284, "AMD": 186, "CRM": 268, "ORCL": 242, "BAC": 52.4,
    "GS": 786, "MS": 148, "CVX": 156, "PFE": 26.8, "KO": 71.2,
}
INVERSE = {"vix", "vix9d", "vix3m", "vvix", "move", "vstoxx", "rvx"}


def synthetic_frame(asof: dt.date | None = None, seed: int = 20260819) -> MarketFrame:
    asof = asof or dt.date.today()
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp(asof), periods=300)
    market = rng.normal(0.0004, 0.0075, len(idx))

    data = {}
    for ins in all_instruments():
        level, vol = LEVELS.get(ins.key, (None, None))
        if level is None:
            level, vol = STOCKS.get(ins.ticker, 100.0), 0.016
        beta = -3.4 if ins.key in INVERSE else (-0.25 if ins.key in ("gold", "dxy") else 0.55)
        noise = rng.normal(0, vol, len(idx))
        r = beta * market + noise * (1 - abs(beta) * 0.2)
        data[ins.key] = level * np.exp(np.cumsum(r) - np.cumsum(r)[-1])

    # A sovereign curve cannot be a set of independent random walks. Three
    # factors (level, slope, curvature) keep it monotone and plausible.
    tenor_keys = ["ust1m", "ust3m", "ust6m", "ust1y", "ust2y", "ust3y",
                  "ust5y", "ust7y", "ust10y", "ust20y", "ust30y"]
    tau = np.array([1/12, .25, .5, 1, 2, 3, 5, 7, 10, 20, 30])
    lam = 0.42
    load_s = (1 - np.exp(-lam * tau)) / (lam * tau)
    load_c = load_s - np.exp(-lam * tau)
    level = 4.62 + np.cumsum(rng.normal(0, .020, len(idx)))
    slope = -0.92 + np.cumsum(rng.normal(0, .017, len(idx)))
    curv = -0.58 + np.cumsum(rng.normal(0, .022, len(idx)))
    curve = (level[:, None] + slope[:, None] * load_s[None, :]
             + curv[:, None] * load_c[None, :])
    for j, k in enumerate(tenor_keys):
        data[k] = curve[:, j]

    px = pd.DataFrame(data, index=idx)
    return MarketFrame(px=px, snap=snapshot(px), asof=asof, missing=[])


def demo_note() -> Note:
    return Note({
        "headline": "Long end sets the pace and equities give ground in an orderly session",
        "standfirst": ("US equities closed lower with the damage concentrated in "
                       "the longest-duration corners of the market, while the "
                       "10-year Treasury set the tempo. Defensive rotation was the "
                       "session's defining feature, with no strain visible in "
                       "funding markets or credit spreads."),
        "takeaways": [
            "Equities fell with wide sector dispersion, which reads as rotation "
            "rather than an indiscriminate cut in risk.",
            "The curve shift landed at the long end. The 10-year led the move and "
            "the 2-year barely budged.",
            "Credit did not confirm the equity signal. Spreads held and the "
            "primary market stayed open.",
            "Implied volatility rose off a low base without inverting the term "
            "structure, which caps the stress read.",
        ],
        "equities": "The decline was broad but far from uniform. The gap between "
        "the leading and lagging sector stayed inside the range typical of a "
        "rotation day, with rate-sensitive names giving ground and defensive flows "
        "absorbing part of the move.\n\n"
        "Breadth across the watchlist finished on the sell side, though "
        "cross-sectional dispersion remained high. That is the signature of a "
        "market discriminating on fundamentals, not one cutting exposure "
        "wholesale.",
        "rates": "The Treasury curve shifted higher with the bias toward longer "
        "maturities. The 2s10s spread widened, extending the steepening that has "
        "run through the quarter.\n\n"
        "Breakeven inflation barely moved, so the adjustment came from the real "
        "yield component and the term premium. That is the day's most useful "
        "signal: the market is demanding more compensation to hold duration, not "
        "to hold inflation risk.",
        "credit": "Credit refused to confirm what equities were saying. "
        "Investment grade and high yield vehicles closed with no meaningful "
        "spread deterioration, and dollar EM held its footing. As long as credit "
        "stays put, the equity move has the character of a valuation adjustment.",
        "fx": "The dollar firmed modestly against the G10, consistent with the "
        "shift at the US long end. Higher-beta emerging crosses gave up the most, "
        "which fits the rise in implied volatility.",
        "commodities": "Energy traded on its own inventory balance rather than "
        "on any correlation with risk assets. Precious metals did their usual "
        "offsetting work and industrials remained the cleanest read available on "
        "the global manufacturing cycle.",
        "volatility": "Implied volatility rose from a low base without inverting "
        "the term structure. Protection is still cheap by historical standards, "
        "which suggests the market is treating this as a rotation day rather than "
        "the start of a different regime.",
        "digital": "Digital assets tracked equity risk appetite with their usual "
        "beta to the tech complex. The correlation with long-duration exposure "
        "remains the structural feature of the asset class.",
        "international": "Europe closed before the weakest stretch of the US "
        "session and missed the final leg down. Asia had set the tone from the "
        "open, with the China bloc trading its own domestic agenda. The clock "
        "leaves European indices with an adjustment to make at tomorrow's open.",
        "correlation": "The matrix is the check on the narrative read of the "
        "session. A stable correlation between equities and the Treasury long end "
        "says the market is still pricing a common discount-rate factor. When "
        "that link breaks, the regime usually changes before the indices show "
        "it.\n\n"
        "Commodities and the dollar give the complementary read. When both move "
        "the same way against risk assets, the impulse is coming from the real "
        "economy rather than from monetary policy.",
        "desk_view": "The session confirms that the dominant factor this quarter "
        "is still term premium, not the earnings cycle. While credit holds and "
        "the volatility term structure stays upward sloping, the reasonable read "
        "is rotation within risk rather than an exit from it.\n\n"
        "The level to watch sits in the 10-year. That is where the difference "
        "between a valuation adjustment and the start of something else gets "
        "settled.",
        "watching": [
            "Long-end Treasury auction and the behaviour of indirect demand.",
            "US price data and the pass-through to breakeven inflation.",
            "European open and the adjustment left over from the US close.",
            "Volatility term structure. An inversion changes the read.",
        ],
        "linkedin": "US equities closed lower, but the number that mattered "
        "today was not in the equity market. It was at the long end of the "
        "Treasury curve.\n\n"
        "The shift landed in longer maturities while the 2-year barely moved. "
        "Breakeven inflation was close to flat, so the adjustment came from real "
        "yields and term premium. The market wants more compensation to hold "
        "duration. It is not asking for more compensation to hold inflation "
        "risk.\n\n"
        "Three things kept the move contained.\n\n"
        "Credit did not follow. Investment grade and high yield spreads held, "
        "and the primary market stayed open.\n\n"
        "Sector dispersion was wide. A market that discriminates is rotating. A "
        "market that is cutting risk sells everything at once.\n\n"
        "The volatility term structure stayed upward sloping. Protection is "
        "still cheap by historical standards.\n\n"
        "The desk read: rotation within risk, not an exit from it. What would "
        "change that is the 10-year.",
        "tiktok": "US stocks closed lower. The move started in the bond market, "
        "not the stock market. Long-dated Treasury yields rose while short yields "
        "sat still. Inflation expectations barely moved, so this was about term "
        "premium. Credit spreads held. Sector dispersion stayed wide. Both of "
        "those say rotation, not panic. The 10-year is the level that decides "
        "what happens next.",
    }, audit_ok=True)
