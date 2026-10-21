import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from andra.session import (SessionError, check_requested, last_completed,
                           todays_session)

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


# The two weekday crons, 20:30 and 21:30 UTC, across both clock changes.
# Summer (EDT): both fire after the close; winter (EST): 20:30 UTC is 3:30 pm
# ET, before it. A scheduled run reports today's close or nothing.
@pytest.mark.parametrize("utc, expected", [
    ("2026-10-30T20:30", dt.date(2026, 10, 30)),   # Fri, EDT, 4:30 pm
    ("2026-10-30T21:30", dt.date(2026, 10, 30)),   # Fri, EDT, 5:30 pm
    ("2026-11-02T20:30", None),                    # Mon, EST, 3:30 pm: before the close
    ("2026-11-02T21:30", dt.date(2026, 11, 2)),    # Mon, EST, 4:30 pm
    ("2026-11-26T21:30", None),                    # Thanksgiving
    ("2026-11-27T20:30", dt.date(2026, 11, 27)),   # half day, 1 pm close
    ("2027-03-12T20:30", None),                    # Fri, last EST day
    ("2027-03-12T21:30", dt.date(2027, 3, 12)),
    ("2027-03-15T20:30", dt.date(2027, 3, 15)),    # Mon, EDT again
    ("2027-03-15T21:30", dt.date(2027, 3, 15)),
])
def test_scheduled_runs_report_only_todays_close(utc, expected):
    now = dt.datetime.fromisoformat(utc).replace(tzinfo=dt.timezone.utc)
    assert todays_session(now) == expected
