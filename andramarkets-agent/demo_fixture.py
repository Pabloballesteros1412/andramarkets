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
    "audusd": (0.6584, .0052), "usdcny": (7.1284, .0018), "usdmxn": (18.42, .0062),
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
# Drawn after everything else, from their own generator, so the rest of the
# fixture is the same series it was before the FX analysis was added.
FX_MORE = {"nzdusd": (0.5842, .0050), "usdkrw": (1386.40, .0045),
           "usdzar": (17.62, .0068)}
POLICY = {"fedupper": 4.00, "fedlower": 3.75, "ecbdfr": 2.00, "pol_jp": 0.75,
          "pol_gb": 3.75, "pol_ch": 0.00, "pol_ca": 2.50, "pol_au": 3.60,
          "pol_nz": 2.75, "pol_cn": 1.40, "pol_mx": 7.25, "pol_br": 14.25,
          "pol_in": 5.50, "pol_kr": 2.50, "pol_za": 7.00, "pol_tr": 39.50}
INVERSE = {"vix", "vix9d", "vix3m", "vvix", "move", "vstoxx", "rvx"}


def synthetic_frame(asof: dt.date | None = None, seed: int = 20260819) -> MarketFrame:
    asof = asof or dt.date.today()
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp(asof), periods=300)
    market = rng.normal(0.0004, 0.0075, len(idx))

    data = {}
    for ins in all_instruments():
        if ins.key in FX_MORE or ins.key in POLICY:
            continue
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

    fx_rng = np.random.default_rng(seed + 1)
    for k, (level, vol) in FX_MORE.items():
        r = fx_rng.normal(0, vol, len(idx))
        data[k] = level * np.exp(np.cumsum(r) - np.cumsum(r)[-1])
    # Policy rates step, they do not drift: one 25bp cut 40 sessions ago.
    for k, rate in POLICY.items():
        data[k] = np.where(np.arange(len(idx)) < len(idx) - 40, rate + 0.25, rate)

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


def demo_fx_note(facts: dict) -> Note:
    """The FX note for demo runs. The prose carries no figure; the levels
    lines are set from the demo fact pack, so the figure check runs on them."""
    from andra.fx import level_lines
    return Note({
        "headline": "Dollar eases as the rand and the euro lead and the kiwi lags",
        "standfirst": ("The dollar index closed lower on the day, the week and the "
                       "month while the US 2-year yield barely moved, so the front end "
                       "was not the driver. The rand and the euro led the gains against "
                       "the dollar, and the New Zealand dollar was the weakest currency "
                       "on the board."),
        "takeaways": [
            "The dollar's decline came with a flat US 2-year yield, so the rate "
            "data offers no explanation for the session.",
            "The euro was the strongest major on the day and recovered most of "
            "its loss on the month over the past week.",
            "The New Zealand dollar moved against the trend and is the weakest "
            "major over the month.",
            "In emerging markets the rand and the won gained while the real, the "
            "yuan and the rupee slipped, a split that cuts across regions.",
        ],
        "dollar": "The dollar index finished lower and extended losses that now "
        "run across the week and the month. The US 2-year yield ended the session "
        "almost unchanged, so the front end is not the explanation the data offers "
        "today. The decline was broad among the majors: only sterling, the Canadian "
        "dollar and the New Zealand dollar lost ground to the dollar.\n\n"
        "The index closed below its 50-day and 200-day averages and sits closer to "
        "its 52-week low than to its high. That places the session inside an "
        "established decline rather than at the start of a new one. Without a move "
        "in US rates to anchor it, the dollar's direction came from the other side "
        "of each pair.",
        "majors": "EUR/USD led the majors higher and recovered most of its loss on "
        "the month over the past week. The ECB's deposit rate sits below the top of "
        "the Fed's range and neither moved, so the gain came without help from the "
        "policy differential. The pair closed just below its 50-day average, which "
        "frames the session as a move within a range rather than out of one.\n\n"
        "The Swiss franc and the yen also gained on the dollar. The franc is the "
        "strongest major over the month, in line with its role as a funding and "
        "haven currency. USD/JPY closed near its 1-month high despite the day's dip, "
        "so the yen's gain was small against a month of weakness.\n\n"
        "The New Zealand dollar went the other way. It was the weakest currency on "
        "the session, is the weakest major over the month and lost ground on the "
        "week as well. The Australian dollar rose on the day, so the move was "
        "specific to New Zealand rather than to the commodity bloc, with the RBNZ "
        "meeting inside the next week. Sterling and the Canadian dollar slipped "
        "against the dollar.",
        "em": "Emerging currencies split across regions rather than along them. "
        "The rand was the strongest currency in the pack on the day, and USD/ZAR "
        "closed below its 50-day average. The won also gained. In Latin America the "
        "Mexican peso firmed on the session but remains the weakest currency in the "
        "pack over the month, while the Brazilian real slipped on the day after a "
        "stronger month.\n\n"
        "In Asia the yuan and the rupee weakened against the dollar, and USD/CNY "
        "stayed inside its 1-month range. The Turkish lira was little changed. Over "
        "the week every EM currency in the pack lost ground to the dollar, so the "
        "session's gains in the rand and the won ran against the recent trend.",
        "drivers": "The rate side was quiet. The US 2-year closed almost unchanged "
        "and no central bank in the pack moved today, so the policy differentials "
        "that frame the majors were the same at the close as at the open. The euro, "
        "the franc and the yen all carry policy rates below the Fed's, and all three "
        "gained, which says the dollar's weakness came from flows the rate data does "
        "not capture.\n\n"
        "Outside the lira, the differential to the Fed is widest for the real and "
        "then the peso, and the two went in opposite directions on the session. "
        "Over the month the real, with the larger carry, gained while the peso fell "
        "the most. The correlation of each pair with the US 2-year over the last 60 "
        "sessions is close to zero across the board, which fits a month in which "
        "the front end explained little of what currencies did.\n\n"
        "The last decisions in the pack point the same way for every bank: a cut "
        "of the same size, applied some weeks ago, so no bank has moved the "
        "differential since. The Bank of Japan's cut left the yen with one of the "
        "widest gaps to the Fed in the G10, and the yen still gained on the "
        "dollar today. The rate data sets the frame for the month; it does not "
        "explain the session.",
        "levels": level_lines(facts),
    }, audit_ok=True)
