"""Ingestion and quality control.

Swappable provider layer: Yahoo and FRED cover the build with no cost;
`bloomberg` is a stub so blpapi or Refinitiv can be wired in without touching
anything downstream.

Output contract, always the same:
    MarketFrame.px    closing prices, dates x key
    MarketFrame.snap  one row per instrument: last, chg, w1, m1, m3, ytd, z

No module downstream ever sees a vendor symbol, only the key.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .universe import BLOCKS, Instrument, all_instruments

log = logging.getLogger("andra.data")
WINDOW_DAYS = 400


@dataclass
class MarketFrame:
    px: pd.DataFrame
    snap: pd.DataFrame
    asof: dt.date
    missing: list[str]

    def block(self, name: str) -> pd.DataFrame:
        keys = [i.key for i in BLOCKS[name] if i.key in self.snap.index]
        return self.snap.loc[keys]

    def rows(self, name: str) -> list[dict]:
        d = self.block(name)
        return [] if d.empty else d.reset_index().to_dict("records")

    def get(self, key: str, field: str = "chg") -> float | None:
        try:
            v = float(self.snap.at[key, field])
            return None if pd.isna(v) else v
        except Exception:
            return None

    def series(self, key: str, n: int = 120) -> pd.Series:
        return self.px[key].dropna().tail(n)


def _yahoo(instrs: list[Instrument], start: dt.date, end: dt.date) -> pd.DataFrame:
    import yfinance as yf
    tickers = [i.ticker for i in instrs]
    raw = yf.download(tickers, start=start, end=end + dt.timedelta(days=1),
                      auto_adjust=False, progress=False, threads=True)
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else \
        raw[["Close"]].rename(columns={"Close": tickers[0]})
    mapping = {i.ticker: i.key for i in instrs}
    close = close.rename(columns=mapping)
    return close.loc[:, [c for c in close.columns if c in mapping.values()]]


def _fred(instrs: list[Instrument], start: dt.date, end: dt.date) -> pd.DataFrame:
    key = os.getenv("FRED_API_KEY")
    if not key:
        log.warning("FRED_API_KEY not set: skipping the Treasury curve block.")
        return pd.DataFrame()
    from fredapi import Fred
    fred = Fred(api_key=key)
    out = {}
    for i in instrs:
        try:
            out[i.key] = fred.get_series(i.ticker, observation_start=start,
                                         observation_end=end)
        except Exception as e:  # noqa: BLE001
            log.warning("FRED %s failed: %s", i.ticker, e)
    return pd.DataFrame(out)


def _bloomberg(instrs: list[Instrument], start, end) -> pd.DataFrame:
    """Extension point. Wire blpapi or Refinitiv here in production.

    Return a DataFrame of dates x key. Until a terminal is connected the note
    prints n/a for these rows rather than estimating a level.
    """
    log.info("No institutional feed configured: %d series skipped.", len(instrs))
    return pd.DataFrame()


PROVIDERS = {"yahoo": _yahoo, "fred": _fred, "bloomberg": _bloomberg}


def load(asof: dt.date | None = None) -> MarketFrame:
    asof = asof or dt.date.today()
    start = asof - dt.timedelta(days=WINDOW_DAYS)

    frames = []
    for src, fn in PROVIDERS.items():
        instrs = [i for i in all_instruments() if i.src == src]
        if not instrs:
            continue
        try:
            df = fn(instrs, start, asof)
            if not df.empty:
                frames.append(df)
        except Exception as e:  # noqa: BLE001
            log.error("Provider %s failed outright: %s", src, e)

    px = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
    px.index = pd.to_datetime(px.index)
    px = px.ffill(limit=3)

    missing = sorted({i.key for i in all_instruments()} - set(px.columns))
    if missing:
        log.warning("No print for %d series: %s", len(missing), ", ".join(missing[:12]))
    return MarketFrame(px=px, snap=snapshot(px), asof=asof, missing=missing)


def _ret(s: pd.Series, n: int) -> float:
    s = s.dropna()
    return np.nan if len(s) <= n else 100.0 * (s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def snapshot(px: pd.DataFrame) -> pd.DataFrame:
    meta = {i.key: i for i in all_instruments()}
    rows = []
    for key in px.columns:
        s = px[key].dropna()
        if len(s) < 2:
            continue
        ins = meta[key]
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        is_rate = ins.unit == "pct"

        ytd_base = s[s.index.year == s.index[-1].year]
        ytd_px = np.nan if ytd_base.empty else 100.0 * (last / float(ytd_base.iloc[0]) - 1.0)

        r = s.pct_change().dropna().tail(252)
        z = (r.iloc[-1] - r.mean()) / r.std() if len(r) > 30 and r.std() else np.nan

        rows.append({
            "key": key, "name": ins.name, "ticker": ins.ticker,
            "dec": ins.dec, "unit": ins.unit, "summary": ins.summary,
            "last": last, "prev": prev,
            # Rates move in basis points, never in percent.
            "chg": (last - prev) * 100 if is_rate else 100.0 * (last / prev - 1.0),
            "w1": (s.iloc[-1] - s.iloc[-6]) * 100 if is_rate and len(s) > 6 else _ret(s, 5),
            "m1": (s.iloc[-1] - s.iloc[-22]) * 100 if is_rate and len(s) > 22 else _ret(s, 21),
            "m3": (s.iloc[-1] - s.iloc[-64]) * 100 if is_rate and len(s) > 64 else _ret(s, 63),
            "ytd": (last - float(ytd_base.iloc[0])) * 100 if is_rate and not ytd_base.empty else ytd_px,
            "z": z,
            "high52": float(s.tail(252).max()), "low52": float(s.tail(252).min()),
        })
    return pd.DataFrame(rows).set_index("key") if rows else pd.DataFrame()
