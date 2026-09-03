#!/usr/bin/env python3
"""Andra Markets close agent.

    python run_daily.py                live data, builds and emails
    python run_daily.py --no-mail      builds only
    python run_daily.py --demo         synthetic fixture, no API calls
    python run_daily.py --date 2026-08-19
    python run_daily.py --force        skip every gate, publish right now

Scheduling: two crons cover the summer and winter UTC offset for the 4:00 pm
ET close. Both may fire close together, and GitHub's free scheduler can also
delay a run by hours. Neither should ever produce two emails or a report
mislabelled with the wrong date, so this file makes both mistakes structurally
impossible instead of relying on hitting an exact time of day:

  1. SESSION   The date reported on is worked out from the current New York
               time, not copied from it. Before the close, "today" has not
               finished yet, so the correct session is the last one that has.
  2. DEDUP     A marker file records the last session actually emailed. Any
               run for a session already marked exits without doing anything,
               so a second cron firing minutes later, or a wildly delayed one
               firing the next morning, cannot send a duplicate.

The marker is committed back to the repository by the workflow after a
successful run, so it survives between the fresh checkouts each run starts
from.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from andra import render
from andra.analytics import fact_pack

logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                    format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("andra")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


def _traded(date: dt.date) -> bool:
    if date.weekday() >= 5:
        return False
    try:
        import pandas_market_calendars as mcal
        return not mcal.get_calendar("NYSE").schedule(start_date=date, end_date=date).empty
    except ImportError:
        log.warning("pandas_market_calendars not installed: weekend filter only.")
        return True


def _early_close(date: dt.date) -> bool:
    try:
        import pandas_market_calendars as mcal
        sch = mcal.get_calendar("NYSE").schedule(start_date=date, end_date=date)
        if sch.empty:
            return False
        return sch.iloc[0]["market_close"].tz_convert("America/New_York").hour < 15
    except ImportError:
        return False


def _edition() -> int:
    f = ROOT / ".edition"
    n = int(f.read_text()) + 1 if f.exists() else 1
    f.write_text(str(n))
    return n


def _ny_now() -> dt.datetime:
    """Current time in New York, where the session Andra reports on closes."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        # Fallback if tz data is unavailable: assume the runner is on UTC and
        # subtract a fixed offset. Coarse, but keeps the date on the US side.
        return dt.datetime.utcnow() - dt.timedelta(hours=5)


def _session_date(ny: dt.datetime) -> dt.date:
    """Which trading session this run should report on.

    Before the 4:00 pm ET close, today's session has not finished, so the
    right answer is the previous business day, not today. A run that fires
    at 1am New York time because GitHub delayed it overnight still resolves
    to the correct, already-closed session instead of mislabelling stale data
    as today's close.
    """
    d = ny.date()
    if ny.hour < 16:
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _marker() -> Path:
    return ROOT / ".last_published"


def _already_published(date: dt.date) -> bool:
    f = _marker()
    return f.exists() and f.read_text().strip() == date.isoformat()


def _mark_published(date: dt.date) -> None:
    _marker().write_text(date.isoformat())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--half-day", action="store_true", dest="half")
    args = ap.parse_args()

    ny = _ny_now()

    if args.force or args.demo:
        # Manual and demo runs bypass every gate below: they use the date
        # given, or the current New York date if none was given, and are
        # never recorded in the dedup marker so they can never suppress a
        # later scheduled run.
        date = dt.date.fromisoformat(args.date) if args.date else ny.date()
    else:
        date = dt.date.fromisoformat(args.date) if args.date else _session_date(ny)

        if _already_published(date):
            log.info("Already published the %s session. Skipping to avoid "
                     "sending a second email for the same close.", date)
            return 0
        if not _traded(date):
            log.info("NYSE did not trade on %s. Nothing published.", date)
            return 0
        if args.half and not _early_close(date):
            log.info("Full session: the half-day window does not publish.")
            return 0
        if not args.half and _early_close(date):
            log.info("Early close: the note went out in the 1:00 pm ET window.")
            return 0

    OUT.mkdir(exist_ok=True)

    # 1 · Data
    if args.demo:
        from demo_fixture import synthetic_frame
        mf = synthetic_frame(date)
        log.info("Demo mode: synthetic data, no external calls.")
    else:
        from andra.data import load
        mf = load(date)
    log.info("Snapshot ready: %d series, %d with no print.", len(mf.snap), len(mf.missing))

    # 2 · Writing
    facts = fact_pack(mf)
    if args.demo:
        from demo_fixture import demo_note
        note = demo_note()
    else:
        from andra.narrative import write, write_without_model
        try:
            note = write(facts)
        except Exception:  # noqa: BLE001
            # Log the full traceback. A one-line message is not enough to
            # diagnose a writer failure from a CI log.
            log.exception("Writer unavailable. Publishing in quantitative mode.")
            note = write_without_model(facts)
        else:
            filled = sum(1 for v in note.content.values() if v)
            log.info("Note written: %d of %d sections filled.",
                     filled, len(note.content))
    log.info("Figure check: %s (%d attempts)",
             "passed" if note.audit_ok else f"FAILED {note.unsupported}", note.attempts)

    # 3 · Composition
    stamp = date.strftime("%Y%m%d")
    with tempfile.TemporaryDirectory() as tmp:
        ex = render.build_exhibits(mf, tmp)
        ctx = render.build_context(mf, note, ex, calendar=_calendar(),
                                 edition=_edition(), social_tmp=tmp)
        report = str(OUT / f"AndraMarkets_Close_{stamp}.pdf")
        carousel = str(OUT / f"AndraMarkets_LinkedIn_{stamp}.pdf")
        render.report_pdf(ctx, report)
        render.linkedin_pdf(ctx, carousel)
        stills = render.tiktok_images(ctx, str(OUT / f"tiktok_{stamp}"), f"andra_{stamp}")
    log.info("Built 2 documents and %d TikTok stills in %s", len(stills), OUT)

    # 4 · Copy
    from andra.social import check, linkedin_caption, tiktok_caption, tiktok_script
    li = linkedin_caption(note, ctx)
    tt = tiktok_caption(note, ctx)
    script = tiktok_script(note)
    checks = check(li)
    (OUT / f"linkedin_caption_{stamp}.txt").write_text(li, encoding="utf-8")
    (OUT / f"tiktok_caption_{stamp}.txt").write_text(f"{tt}\n\n---\n{script}", encoding="utf-8")
    (OUT / f"facts_{stamp}.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("Caption: %d chars | figure in hook: %s | style flags: %s",
             checks["characters"], checks["hook_has_figure"],
             checks["style_flags"] or "none")

    if args.no_mail or args.demo:
        log.info("Email skipped.")
        return 0

    from andra.mailer import send
    send(li, tt, script, checks, [carousel, report, *stills], ctx,
         note.audit_ok, len(mf.missing), len(stills))
    log.info("Delivered to %s", os.environ["MAIL_TO"])

    if not args.force:
        _mark_published(date)
    return 0


def _calendar() -> list[dict]:
    """Next-session calendar. Wire an economic calendar feed here.

    Until then, drop a JSON list at calendar.json with time / event /
    consensus / prior and it gets picked up.
    """
    f = ROOT / "calendar.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("calendar.json is not valid JSON. Skipping the section.")
    return []


if __name__ == "__main__":
    sys.exit(main())
