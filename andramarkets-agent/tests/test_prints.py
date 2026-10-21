import datetime as dt
import sys
import types

import numpy as np
import pandas as pd

from andra import data
from andra.analytics import fact_pack
from andra.universe import APAC


def fake_yfinance(monkeypatch, closes, meta):
    class Ticker:
        def __init__(self, symbol):
            self.history_metadata = meta

        def history(self, **kw):
            idx = pd.DatetimeIndex(list(closes), tz="Asia/Tokyo")
            return pd.DataFrame({"Close": list(closes.values())}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))


NKY = APAC[0]
CLOSED = pd.Timestamp("2026-10-21 15:45:03", tz="Asia/Tokyo")


def test_empty_close_filled_from_metadata(monkeypatch):
    fake_yfinance(monkeypatch, {"2026-10-20": 64075.42, "2026-10-21": np.nan},
                  {"regularMarketPrice": 64621.24, "exchangeTimezoneName": "Asia/Tokyo",
                   "regularMarketTime": int(CLOSED.timestamp())})
    s, stamp = data._yahoo_one(NKY, dt.date(2026, 9, 1), dt.date(2026, 10, 21))
    assert s.loc["2026-10-21"] == 64621.24
    assert stamp == "2026-10-21T15:45:03+09:00"


def test_metadata_after_the_session_is_ignored(monkeypatch):
    # Reporting on 20 Oct: the 21 Oct print must not leak in.
    fake_yfinance(monkeypatch, {"2026-10-19": 64916.70, "2026-10-20": 64075.42},
                  {"regularMarketPrice": 64621.24, "exchangeTimezoneName": "Asia/Tokyo",
                   "regularMarketTime": int(CLOSED.timestamp())})
    s, stamp = data._yahoo_one(NKY, dt.date(2026, 9, 1), dt.date(2026, 10, 20))
    assert s.index[-1] == pd.Timestamp("2026-10-20")
    assert s.iloc[-1] == 64075.42
    assert stamp is None


def test_rows_carry_their_own_date_and_flag():
    idx = pd.bdate_range(end="2026-10-21", periods=60)
    px = pd.DataFrame({"spx": np.linspace(7000, 7757, 60),
                       "nky": np.linspace(60000, 64621, 60)}, index=idx)
    px.loc[idx[-1], "nky"] = np.nan        # Tokyo shut on the session date
    snap = data.snapshot(px, {"spx": "2026-10-21T16:31:21-04:00"})
    mf = data.MarketFrame(px=px.ffill(), snap=snap, asof=dt.date(2026, 10, 21),
                          missing=[])
    facts = fact_pack(mf)
    spx = facts["us_equity"][0]
    nky = facts["apac"][0]
    assert (spx["date"], spx["time"], spx["off_session"]) == \
        ("2026-10-21", "2026-10-21T16:31:21-04:00", False)
    assert (nky["date"], nky["time"], nky["off_session"]) == ("2026-10-20", None, True)
    assert facts["series_off_session"] == ["nky"]
