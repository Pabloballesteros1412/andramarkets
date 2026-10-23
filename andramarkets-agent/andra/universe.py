"""Coverage universe.

One block per asset class. `key` is the stable internal identifier; `src`
names the provider, so the universe survives a vendor change without touching
anything downstream.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    key: str
    name: str                 # publication name
    ticker: str               # provider symbol
    src: str = "yahoo"        # yahoo | fred | bloomberg
    unit: str = "px"          # px | pct
    dec: int = 2
    summary: str | None = None   # "equity" or "macro" if shown on page one


I = Instrument

US_EQUITY = [
    I("spx", "S&P 500", "^GSPC", summary="equity"),
    I("ndx", "Nasdaq 100", "^NDX", summary="equity"),
    I("dji", "Dow Jones Industrial", "^DJI", summary="equity"),
    I("rut", "Russell 2000", "^RUT", summary="equity"),
    I("mid", "S&P MidCap 400", "^MID"),
    I("nya", "NYSE Composite", "^NYA"),
]

SECTORS = [
    I("xlk", "Technology", "XLK"), I("xlf", "Financials", "XLF"),
    I("xlv", "Health care", "XLV"), I("xly", "Cons. discretionary", "XLY"),
    I("xlp", "Cons. staples", "XLP"), I("xle", "Energy", "XLE"),
    I("xli", "Industrials", "XLI"), I("xlb", "Materials", "XLB"),
    I("xlre", "Real estate", "XLRE"), I("xlu", "Utilities", "XLU"),
    I("xlc", "Communications", "XLC"),
]

EUROPE = [
    I("sx5e", "EURO STOXX 50", "^STOXX50E", summary="equity"),
    I("dax", "DAX 40", "^GDAXI"), I("cac", "CAC 40", "^FCHI"),
    I("ftse", "FTSE 100", "^FTSE"), I("ibex", "IBEX 35", "^IBEX"),
    I("mib", "FTSE MIB", "FTSEMIB.MI"), I("smi", "SMI", "^SSMI"),
    I("aex", "AEX", "^AEX"),
]

# Checked against Yahoo on 21 Oct 2026. TOPIX (^TOPX), the IPSA (^IPSA),
# VSTOXX (^V2TX, V2TX.DE) and the Russell VIX (^RVX) return no data under any
# symbol; CSI 300 (000300.SS, 399300.SZ) and USD/CNH (CNH=X) return only the
# latest bar, so no change can be computed. They are left out rather than
# promised and never printed. USD/CNY (CNY=X) stands in for USD/CNH.
APAC = [
    I("nky", "Nikkei 225", "^N225", summary="equity"),
    I("hsi", "Hang Seng", "^HSI"), I("kospi", "KOSPI", "^KS11"),
    I("sensex", "SENSEX", "^BSESN"), I("asx", "ASX 200", "^AXJO"),
    I("twii", "TAIEX", "^TWII"),
]

AMERICAS = [
    I("ibov", "Bovespa", "^BVSP"), I("mexbol", "S&P/BMV IPC", "^MXX"),
    I("merval", "S&P Merval", "^MERV"),
    I("tsx", "S&P/TSX", "^GSPTSE"),
]

UST_CURVE = [
    I("ust1m", "1 month", "DGS1MO", "fred", "pct"),
    I("ust3m", "3 month", "DGS3MO", "fred", "pct"),
    I("ust6m", "6 month", "DGS6MO", "fred", "pct"),
    I("ust1y", "1 year", "DGS1", "fred", "pct"),
    I("ust2y", "2 year", "DGS2", "fred", "pct", summary="macro"),
    I("ust3y", "3 year", "DGS3", "fred", "pct"),
    I("ust5y", "5 year", "DGS5", "fred", "pct"),
    I("ust7y", "7 year", "DGS7", "fred", "pct"),
    I("ust10y", "10 year", "DGS10", "fred", "pct", summary="macro"),
    I("ust20y", "20 year", "DGS20", "fred", "pct"),
    I("ust30y", "30 year", "DGS30", "fred", "pct", summary="macro"),
]

BREAKEVENS = [
    I("be5y", "5-year breakeven", "T5YIE", "fred", "pct"),
    I("be10y", "10-year breakeven", "T10YIE", "fred", "pct"),
    I("fwd5y5y", "5y5y forward", "T5YIFR", "fred", "pct"),
    I("real10y", "10-year TIPS", "DFII10", "fred", "pct"),
]

SOVEREIGNS = [
    I("bund10", "German Bund", "DE10Y", "bloomberg", "pct"),
    I("oat10", "French OAT", "FR10Y", "bloomberg", "pct"),
    I("btp10", "Italian BTP", "IT10Y", "bloomberg", "pct"),
    I("bono10", "Spanish Bono", "ES10Y", "bloomberg", "pct"),
    I("gilt10", "UK Gilt", "GB10Y", "bloomberg", "pct"),
    I("jgb10", "Japan JGB", "JP10Y", "bloomberg", "pct"),
]

CREDIT = [
    I("lqd", "US investment grade", "LQD"),
    I("hyg", "US high yield", "HYG"),
    I("jnk", "US high yield (JNK)", "JNK"),
    I("emb", "EM sovereign USD", "EMB"),
    I("bkln", "Leveraged loans", "BKLN"),
    I("tlt", "Long Treasuries", "TLT"),
    I("ief", "7-10 year Treasuries", "IEF"),
]

FX = [
    I("dxy", "Dollar index", "DX-Y.NYB", summary="macro"),
    I("eurusd", "EUR/USD", "EURUSD=X", dec=4, summary="macro"),
    I("usdjpy", "USD/JPY", "USDJPY=X", summary="macro"),
    I("gbpusd", "GBP/USD", "GBPUSD=X", dec=4),
    I("usdchf", "USD/CHF", "USDCHF=X", dec=4),
    I("usdcad", "USD/CAD", "USDCAD=X", dec=4),
    I("audusd", "AUD/USD", "AUDUSD=X", dec=4),
    I("usdcny", "USD/CNY", "CNY=X", dec=4),
    I("usdmxn", "USD/MXN", "USDMXN=X", dec=4),
    I("usdbrl", "USD/BRL", "USDBRL=X", dec=4),
    I("usdtry", "USD/TRY", "USDTRY=X", dec=4),
    I("usdinr", "USD/INR", "USDINR=X", dec=3),
]

# Pairs read only by the FX analysis (andra/fx.py), kept out of the FX block
# so the close note's tables and exhibits are unchanged.
FX_MORE = [
    I("nzdusd", "NZD/USD", "NZDUSD=X", dec=4),
    I("usdkrw", "USD/KRW", "KRW=X"),
    I("usdzar", "USD/ZAR", "ZAR=X", dec=4),
]

# Policy rates FRED publishes daily. Every other central bank is read from
# central_banks.json (andra/fx.py).
POLICY = [
    I("fedupper", "Fed funds target, upper bound", "DFEDTARU", "fred", "pct"),
    I("fedlower", "Fed funds target, lower bound", "DFEDTARL", "fred", "pct"),
    I("ecbdfr", "ECB deposit facility rate", "ECBDFR", "fred", "pct"),
]

COMMODITIES = [
    I("wti", "WTI crude", "CL=F", summary="macro"),
    I("brent", "Brent crude", "BZ=F"),
    I("natgas", "Natural gas", "NG=F", dec=3),
    I("gold", "Gold", "GC=F", dec=1, summary="macro"),
    I("silver", "Silver", "SI=F", dec=3),
    I("copper", "Copper", "HG=F", dec=4),
    I("platinum", "Platinum", "PL=F", dec=1),
    I("palladium", "Palladium", "PA=F", dec=1),
    I("aluminium", "Aluminium", "ALI=F", dec=1),
    I("wheat", "Wheat", "ZW=F"), I("corn", "Corn", "ZC=F"),
    I("soybean", "Soybeans", "ZS=F"), I("coffee", "Coffee", "KC=F"),
    I("cocoa", "Cocoa", "CC=F", dec=1), I("sugar", "Sugar", "SB=F"),
]

VOLATILITY = [
    I("vix", "VIX", "^VIX", summary="macro"),
    I("vix9d", "VIX 9-day", "^VIX9D"),
    I("vix3m", "VIX 3-month", "^VIX3M"),
    I("vvix", "VVIX", "^VVIX"),
    I("skew", "SKEW", "^SKEW", dec=1),
    I("move", "MOVE (rates)", "^MOVE", dec=1),
]

DIGITAL = [
    I("btc", "Bitcoin", "BTC-USD", dec=0, summary="macro"),
    I("eth", "Ether", "ETH-USD", dec=0),
    I("sol", "Solana", "SOL-USD"),
    I("xrp", "XRP", "XRP-USD", dec=4),
]

WATCHLIST = [I(t.lower().replace("-", ""), t, t) for t in (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK-B",
    "LLY", "JPM", "XOM", "V", "UNH", "COST", "WMT", "NFLX", "AMD", "CRM",
    "ORCL", "BAC", "GS", "MS", "CVX", "PFE", "KO")]

BLOCKS: dict[str, list[Instrument]] = {
    "us_equity": US_EQUITY, "sectors": SECTORS, "europe": EUROPE,
    "apac": APAC, "americas": AMERICAS, "curve": UST_CURVE,
    "breakevens": BREAKEVENS, "sovereigns": SOVEREIGNS, "credit": CREDIT,
    "fx": FX, "commodities": COMMODITIES, "volatility": VOLATILITY,
    "digital": DIGITAL, "watchlist": WATCHLIST,
    "fx_more": FX_MORE, "policy": POLICY,
}


def all_instruments() -> list[Instrument]:
    return [i for b in BLOCKS.values() for i in b]


def summary_block(kind: str) -> list[Instrument]:
    return [i for i in all_instruments() if i.summary == kind]
