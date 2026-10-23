"""Secrets are read with surrounding whitespace removed: a leading space in
the FRED key once silently dropped every rate series."""
import datetime as dt
import sys
import types

import pandas as pd

from andra import data, mailer
from andra.universe import Instrument


def test_fred_key_is_stripped(monkeypatch):
    seen = {}

    class Fred:
        def __init__(self, api_key):
            seen["key"] = api_key

        def get_series(self, ticker, observation_start, observation_end):
            return pd.Series([4.0, 4.1], index=pd.to_datetime(["2026-10-21", "2026-10-22"]))

    monkeypatch.setenv("FRED_API_KEY", " abc123 \n")
    monkeypatch.setitem(sys.modules, "fredapi", types.SimpleNamespace(Fred=Fred))
    out = data._fred([Instrument("ust10y", "10 year", "DGS10", "fred", "pct")],
                     dt.date(2026, 10, 1), dt.date(2026, 10, 22))
    assert seen["key"] == "abc123" and "ust10y" in out


def test_blank_fred_key_counts_as_unset(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "  ")
    assert data._fred([], dt.date(2026, 10, 1), dt.date(2026, 10, 22)).empty


def test_smtp_settings_are_stripped(monkeypatch):
    sent = {}
    monkeypatch.setattr(mailer, "_deliver",
                        lambda msg, host, port, user, pwd: sent.update(
                            host=host, port=port, user=user, pwd=pwd))
    monkeypatch.setenv("SMTP_HOST", " smtp.example.com ")
    monkeypatch.setenv("SMTP_PORT", " 465\n")
    monkeypatch.setenv("SMTP_USER", " desk@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass ")
    monkeypatch.setenv("MAIL_TO", " a@example.com , b@example.com ")
    mailer.send_weekly("caption", [], "23 Oct 2026", "Headline", True, "model", [], True)
    assert sent == {"host": "smtp.example.com", "port": 465,
                    "user": "desk@example.com", "pwd": "app-pass"}
