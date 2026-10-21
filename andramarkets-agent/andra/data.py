"""Ingestion and quality control.

Swappable provider layer: Yahoo and FRED cover the build with no cost;
`bloomberg` is a stub so blpapi or Refinitiv can be wired in without touching
anything downstream.

Output contract, always the same:
    MarketFrame.px    closing prices, dates x key
    MarketFrame.snap  one row per instrument: last, chg, w1, m1, m3, ytd, z,
                      and the instrument's own print: date (its session date,
                      in its exchange's time zone) and time (ISO timestamp,
                      when the provider reports it)

No module downstream ever sees a vendor symbol, only the key.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field as dc_field

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
    stale: list[str] = dc_field(default_factory=list)

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


def _yahoo_one(ins: Instrument, start: dt.date, end: dt.date):
    """One ticker's daily closes, indexed by its own exchange's session date.

    Yahoo leaves the close of the latest daily bar empty for a while after
    many non-US markets have closed (Nikkei, Hang Seng, Euro Stoxx): the
    official close sits only in the chart metadata, as regularMarketPrice at
    regularMarketTime. Read without it, those markets look as if they had not
    printed. The metadata close fills that bar, and its timestamp is kept as
    the print time whenever it is the bar's close.
    """
    import yfinance as yf
    t = yf.Ticker(ins.ticker)
    h = t.history(start=start, end=end + dt.timedelta(days=1), interval="1d",
                  auto_adjust=False)
    if h is None or h.empty:
        return None, None
    s = h["Close"].astype(float)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    s = s[~s.index.duplicated(keep="last")]

    meta = t.history_metadata or {}
    price, when, tz = (meta.get("regularMarketPrice"), meta.get("regularMarketTime"),
                       meta.get("exchangeTimezoneName"))
    stamp = None
    if price is not None and when and tz:
        ts = pd.Timestamp(when, unit="s", tz="UTC").tz_convert(tz)
        day = ts.tz_localize(None).normalize()
        if start <= day.date() <= end and pd.isna(s.get(day)):
            s.loc[day] = float(price)
            s = s.sort_index()
        last = s.dropna()
        if (not last.empty and last.index[-1] == day
                and abs(last.iloc[-1] - price) <= 1e-6 * max(1.0, abs(price))):
            stamp = ts.isoformat()
    return s, stamp


def _yahoo(instrs: list[Instrument], start: dt.date, end: dt.date) -> pd.DataFrame:
    def one(ins):
        try:
            return ins.key, _yahoo_one(ins, start, end)
        except Exception as e:  # noqa: BLE001
            log.warning("Yahoo %s failed: %s", ins.ticker, e)
            return ins.key, (None, None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = dict(pool.map(one, instrs))
        # Yahoo drops the odd request (a 404 or a rate limit) for a ticker
        # that is fine a second later: ask once more for anything empty.
        again = [i for i in instrs if got[i.key][0] is None]
        if again:
            time.sleep(2)
            got.update(pool.map(one, again))
            still = [i.ticker for i in again if got[i.key][0] is None]
            log.info("Yahoo retry: %d of %d recovered.%s", len(again) - len(still),
                     len(again), f" Still empty: {', '.join(still)}" if still else "")
    out = pd.DataFrame({k: s for k, (s, _) in got.items()
                        if s is not None and s.notna().any()})
    out.attrs["times"] = {k: t for k, (_, t) in got.items() if t}
    return out


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

    frames, times = [], {}
    for src, fn in PROVIDERS.items():
        instrs = [i for i in all_instruments() if i.src == src]
        if not instrs:
            continue
        try:
            df = fn(instrs, start, asof)
            if not df.empty:
                frames.append(df)
                times.update(df.attrs.get("times", {}))
        except Exception as e:  # noqa: BLE001
            log.error("Provider %s failed outright: %s", src, e)

    raw = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
    raw.index = pd.to_datetime(raw.index)

    # Two views of the same data, and the difference matters.
    #
    # Providers do not publish on the same clock: Yahoo has today's row the
    # moment a market closes, FRED posts the Treasury curve later. Union the
    # indices and every series that has not printed yet leaves a gap.
    #
    # Forward filling closes those gaps, which is what the charts need to draw
    # a continuous line. But a filled gap makes today's value identical to
    # yesterday's, and the change computes as exactly zero. That is how a note
    # ends up stating that the curve did not move when in fact it had not yet
    # been published.
    #
    # So: charts read the filled frame, every change reads the raw one.
    px = raw.ffill(limit=3)

    missing = sorted({i.key for i in all_instruments()} - set(raw.columns))
    if missing:
        log.warning("No print for %d series: %s", len(missing), ", ".join(missing[:12]))

    snap = snapshot(raw, times)
    stale = _stale(raw, asof)
    if stale:
        log.warning("%d series had no print for %s and are quoted at their last "
                    "close: %s", len(stale), asof, ", ".join(stale[:12]))
    return MarketFrame(px=px, snap=snap, asof=asof, missing=missing, stale=stale)


def _stale(raw: pd.DataFrame, asof: dt.date) -> list[str]:
    """Series whose most recent print predates the session being reported."""
    target = pd.Timestamp(asof)
    out = []
    for key in raw.columns:
        s = raw[key].dropna()
        if not s.empty and s.index[-1].normalize() < target.normalize():
            out.append(key)
    return sorted(out)


def _ret(s: pd.Series, n: int) -> float:
    s = s.dropna()
    return np.nan if len(s) <= n else 100.0 * (s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def snapshot(px: pd.DataFrame, times: dict[str, str] | None = None) -> pd.DataFrame:
    """Per-instrument snapshot. `times` maps key -> ISO time of the last print."""
    meta = {i.key: i for i in all_instruments()}
    times = times or {}
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
            # The instrument's own last print, never the run's date.
            "date": s.index[-1].date().isoformat(),
            "time": times.get(key),
        })
    return pd.DataFrame(rows).set_index("key") if rows else pd.DataFrame()
