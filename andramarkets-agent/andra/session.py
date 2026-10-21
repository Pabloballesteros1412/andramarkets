"""Which NYSE session a run reports on.

A note is always dated with the last session that has finished in New York,
never with the date the run happens to start on. A session counts as finished
fifteen minutes after its actual close (4:15 pm ET on a normal day, 1:15 pm
on a half day), once the closing auction has settled. So a run on a weekend,
on a market holiday, or before that cut-off on a trading day reports on the
previous session, and nothing can be stamped with a future or non-trading
date.

The NYSE calendar comes from pandas_market_calendars. Without it holidays
cannot be told apart from trading days, so live runs stop rather than guess.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger("andra.session")

SETTLE = dt.timedelta(minutes=15)
LOOKBACK = dt.timedelta(days=14)


class SessionError(RuntimeError):
    """The run cannot be dated safely. Nothing should be published."""


def _schedule(start: dt.date, end: dt.date):
    try:
        import pandas_market_calendars as mcal
    except ImportError as e:
        raise SessionError("pandas_market_calendars is not installed: the NYSE "
                           "holiday calendar is unavailable.") from e
    return mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)


def last_completed(now: dt.datetime) -> dt.date:
    """The last NYSE session closed at least SETTLE before `now` (tz-aware)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    sch = _schedule(now.date() - LOOKBACK, now.date())
    done = sch[sch["market_close"] + SETTLE <= now]
    if done.empty:
        raise SessionError(f"no NYSE session finished in the {LOOKBACK.days} days "
                           f"before {now:%Y-%m-%d %H:%M %Z}.")
    return done.index[-1].date()


def todays_session(now: dt.datetime) -> dt.date | None:
    """The session that closed today in New York, or None if it has not yet
    (or there is none today: a weekend or a holiday).

    Scheduled runs only ever report today's close. Two crons cover summer
    and winter time, so in winter the earlier one fires at 3:30 pm ET, before
    the close: it must stop, not fall back to yesterday's session, even if
    yesterday's note was never sent.
    """
    from zoneinfo import ZoneInfo
    d = last_completed(now)
    return d if d == now.astimezone(ZoneInfo("America/New_York")).date() else None


def last_completed_weekday(now: dt.datetime) -> dt.date:
    """Calendar-free fallback for demo runs only: weekends, no holidays."""
    d = now.date()
    if (now.hour, now.minute) < (16, 15):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def check_requested(date: dt.date, now: dt.datetime) -> None:
    """Reject a --date that is not a finished NYSE session."""
    latest = last_completed(now)
    if date > latest:
        raise SessionError(f"{date} has not finished yet: the last completed "
                           f"session is {latest}.")
    if _schedule(date, date).empty:
        raise SessionError(f"NYSE did not trade on {date}.")
