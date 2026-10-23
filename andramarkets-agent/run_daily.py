#!/usr/bin/env python3
"""Andra Markets close agent.

    python run_daily.py                live data, builds and emails
    python run_daily.py --no-mail      builds only
    python run_daily.py --demo         synthetic fixture, no API calls
    python run_daily.py --date 2026-08-19   a past session, checked against NYSE
    python run_daily.py --force        send again even if the session was sent
    python run_daily.py --replay DIR   an archived run again, no model or email
                                       (replay.py fetches the files and calls this)

Scheduling: two crons cover the summer and winter UTC offset for the 4:00 pm
ET close. Both may fire close together, and GitHub's free scheduler can also
delay a run by hours. Neither should ever produce two emails or a report
mislabelled with the wrong date, so this file makes both mistakes structurally
impossible instead of relying on hitting an exact time of day:

  1. SESSION   The date reported on is worked out from the current New York
               time, not copied from it: the last NYSE session that closed at
               least fifteen minutes ago (andra/session.py). Before 4:15 pm
               ET, on a weekend or on a holiday, that is the previous
               session. A --date that is not a finished session stops the
               run, so no note is ever dated in the future or on a day NYSE
               did not trade.
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
from andra.session import (SessionError, check_requested, last_completed,
                           last_completed_weekday, todays_session)

logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                    format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("andra")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"


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


def _marker() -> Path:
    return ROOT / ".last_published"


def _already_published(date: dt.date) -> bool:
    f = _marker()
    return f.exists() and f.read_text().strip() == date.isoformat()


def _mark_published(date: dt.date) -> None:
    _marker().write_text(date.isoformat())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--force", action="store_true",
                    default=os.getenv("ANDRA_RESEND", "").lower() == "true",
                    help="send even if this session was already sent "
                         "(also set by ANDRA_RESEND=true)")
    # Kept so the crontab's 1:20 pm ET line still parses. Half days need no
    # flag: the session cut-off follows each day's actual close.
    ap.add_argument("--half-day", action="store_true", dest="half")
    # Scheduled runs report today's close or nothing. Set on its own for the
    # Actions schedule; the crontab can pass it.
    ap.add_argument("--today-only", action="store_true", dest="today_only",
                    default=os.getenv("GITHUB_EVENT_NAME") == "schedule")
    # Replay: an archived run's facts and note go through every step again.
    # Like demo: no model call, no email, no marker, no edition number.
    ap.add_argument("--replay", metavar="DIR")
    ap.add_argument("--replay-data", choices=("archive", "live"), default="archive")
    ap.add_argument("--out", help="output folder (default out/)")
    args = ap.parse_args(argv)
    out_dir = Path(args.out) if args.out else OUT
    replay = None
    if args.replay:
        import replay as replay_mod
        replay = replay_mod.load_folder(Path(args.replay))

    ny = _ny_now()

    # The date is never today's date by default, and never one NYSE did not
    # trade on, whatever flags are given.
    try:
        if replay:
            date = dt.date.fromisoformat(replay["facts"]["date"])
        elif args.date:
            date = dt.date.fromisoformat(args.date)
            if not args.demo:
                check_requested(date, ny)
        elif args.demo:
            try:
                date = last_completed(ny)
            except SessionError:
                date = last_completed_weekday(ny)
        elif args.today_only:
            date = todays_session(ny)
            if date is None:
                log.info("No NYSE session has closed today yet (New York time "
                         "%s). Scheduled run: nothing to report.",
                         ny.strftime("%Y-%m-%d %H:%M"))
                return 0
        else:
            date = last_completed(ny)
    except SessionError as e:
        log.error("Not publishing: %s", e)
        return 1
    log.info("Reporting on the %s session (New York time %s).",
             date, ny.strftime("%Y-%m-%d %H:%M"))

    # Forced and demo runs skip only the dedup gate, and are never recorded
    # in the marker, so they can never suppress a later scheduled run.
    if not (args.force or args.demo or replay) and _already_published(date):
        log.info("Already published the %s session. Skipping to avoid "
                 "sending a second email for the same close.", date)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1 · Data
    if replay and args.replay_data == "archive":
        mf = replay_mod.archived_frame(replay["facts"])
        log.info("Replay: market data rebuilt from the archived fact pack.")
    elif args.demo:
        from demo_fixture import synthetic_frame
        mf = synthetic_frame(date)
        log.info("Demo mode: synthetic data, no external calls.")
    else:
        from andra.data import load
        mf = load(date)
    log.info("Snapshot ready: %d series, %d with no print.", len(mf.snap), len(mf.missing))

    # 2 · Writing
    facts = fact_pack(mf)
    mode = "model"
    carried = []
    if replay and args.replay_data == "archive":
        carried = replay_mod.carry_over(facts, replay["facts"])
    if replay:
        note, mode = replay_mod.archived_note(replay, facts)
    elif args.demo:
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
            mode = "quantitative"
        else:
            filled = sum(1 for v in note.content.values() if v)
            log.info("Note written: %d of %d sections filled.",
                     filled, len(note.content))
    log.info("Figure check: %s (%d attempts)",
             "passed" if note.audit_ok else f"FAILED {note.unsupported}", note.attempts)

    # 3 · Composition
    stamp = date.strftime("%Y%m%d")
    if replay:
        edition = (replay.get("manifest") or {}).get("edition") or "REPLAY"
    else:
        edition = _edition()
    with tempfile.TemporaryDirectory() as tmp:
        ex = render.build_exhibits(mf, tmp, facts=facts)
        ctx = render.build_context(mf, note, ex, calendar=_calendar(),
                                 edition=edition, social_tmp=tmp, facts=facts)
        report = str(out_dir / f"AndraMarkets_Close_{stamp}.pdf")
        carousel = str(out_dir / f"AndraMarkets_LinkedIn_{stamp}.pdf")
        render.report_pdf(ctx, report)
        render.linkedin_pdf(ctx, carousel)
        stills = render.report_images(report, str(out_dir / f"tiktok_{stamp}"), f"andra_{stamp}")
    log.info("Built 2 documents and %d page stills in %s", len(stills), out_dir)

    # 4 · Copy
    from andra.social import check, linkedin_caption, tiktok_caption, tiktok_script
    li = linkedin_caption(note, ctx)
    tt = tiktok_caption(note, ctx)
    script = tiktok_script(note)
    checks = check(li)
    (out_dir / f"linkedin_caption_{stamp}.txt").write_text(li, encoding="utf-8")
    (out_dir / f"tiktok_caption_{stamp}.txt").write_text(f"{tt}\n\n---\n{script}", encoding="utf-8")
    (out_dir / f"facts_{stamp}.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / f"note_{stamp}.json").write_text(
        json.dumps(note.content, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # What was only visible inside the PDF and the email subject: whether the
    # figure check passed, what it rejected, and how the note was written.
    (out_dir / f"manifest_{stamp}.json").write_text(json.dumps({
        "date": date.isoformat(), "edition": edition,
        "audit_ok": note.audit_ok, "unsupported": note.unsupported,
        "attempts": note.attempts, "mode": mode,
        "demo": bool(args.demo or replay),
        **({"replay_of": str(args.replay), "replay_data": args.replay_data,
            "carried_from_archive": carried} if replay else {}),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # 5-minute bars of the session for the video, or the last 60 daily
    # closes when they cannot be had (demo runs, a failed fetch). The interval
    # is saved so the video never draws daily closes as if they were intraday.
    _series, _prev, _interval = [], None, "5m"
    try:
        _prev = float(mf.snap.at["spx", "prev"])
    except Exception:  # noqa: BLE001
        _prev = None
    if replay and (replay.get("series") or {}).get("series"):
        _series = replay["series"]["series"]
        _prev = replay["series"].get("prev_close", _prev)
        _interval = replay["series"].get("interval", _interval)
    elif not (args.demo or replay):
        try:
            import yfinance as yf
            _tkr = str(mf.snap.at["spx", "ticker"])
            _intr = yf.download(_tkr, start=date, end=date + dt.timedelta(days=1),
                                interval="5m", auto_adjust=False, progress=False,
                                prepost=False)
            if not _intr.empty:
                _cl = _intr["Close"]
                if hasattr(_cl, "columns"):
                    _cl = _cl.iloc[:, 0]
                _series = [round(float(x), 2) for x in _cl.dropna().tolist()]
        except Exception as e:  # noqa: BLE001
            log.warning("Intraday S&P fetch failed, using daily fallback: %s", e)
    if len(_series) < 2:
        _interval = "1d"
        try:
            _series = [round(float(x), 2) for x in mf.series("spx", 60).tolist()]
        except Exception:  # noqa: BLE001
            _series = []
    (out_dir / f"series_{stamp}.json").write_text(
        json.dumps({"series": _series, "prev_close": _prev, "interval": _interval},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("Caption: %d chars | figure in hook: %s | style flags: %s",
             checks["characters"], checks["hook_has_figure"],
             checks["style_flags"] or "none")

    if args.no_mail or args.demo or replay:
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
