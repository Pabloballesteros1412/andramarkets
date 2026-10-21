import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from andra.session import SessionError, check_requested, last_completed

NY = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=NY)


@pytest.mark.parametrize("now, expected", [
    (at(2026, 10, 21, 16, 14), dt.date(2026, 10, 20)),   # before 4:15 pm
    (at(2026, 10, 21, 16, 15), dt.date(2026, 10, 21)),   # cut-off reached
    (at(2026, 10, 21, 23, 59), dt.date(2026, 10, 21)),
    (at(2026, 10, 22, 0, 24), dt.date(2026, 10, 21)),    # past midnight
    (at(2026, 10, 22, 9, 30), dt.date(2026, 10, 21)),    # next morning
    (at(2026, 10, 3, 8, 19), dt.date(2026, 10, 2)),      # Saturday
    (at(2026, 10, 4, 17, 0), dt.date(2026, 10, 2)),      # Sunday
    (at(2026, 10, 5, 10, 0), dt.date(2026, 10, 2)),      # Monday morning
    (at(2026, 11, 26, 18, 0), dt.date(2026, 11, 25)),    # Thanksgiving
    (at(2026, 11, 27, 13, 14), dt.date(2026, 11, 25)),   # half day, too early
    (at(2026, 11, 27, 13, 15), dt.date(2026, 11, 27)),   # half day, 1 pm close
    (at(2027, 1, 1, 20, 0), dt.date(2026, 12, 31)),      # New Year's Day
])
def test_last_completed(now, expected):
    assert last_completed(now) == expected


def test_utc_clock_gives_new_york_session():
    # 00:24 ET on 22 Oct is 04:24 UTC: still the 21 Oct session.
    now = dt.datetime(2026, 10, 22, 4, 24, tzinfo=dt.timezone.utc)
    assert last_completed(now) == dt.date(2026, 10, 21)


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        last_completed(dt.datetime(2026, 10, 21, 18, 0))


@pytest.mark.parametrize("date", [
    dt.date(2026, 10, 3),     # Saturday
    dt.date(2026, 11, 26),    # holiday
    dt.date(2026, 10, 22),    # future
    dt.date(2026, 10, 21),    # today, before the cut-off
])
def test_requested_date_rejected(date):
    with pytest.raises(SessionError):
        check_requested(date, at(2026, 10, 21, 15, 0))


def test_requested_past_session_accepted():
    check_requested(dt.date(2026, 10, 20), at(2026, 10, 21, 15, 0))
