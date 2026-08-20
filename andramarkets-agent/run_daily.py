#!/usr/bin/env python3
"""Andra Markets close agent.

    python run_daily.py                live data, builds and emails
    python run_daily.py --no-mail      builds only
    python run_daily.py --demo         synthetic fixture, no API calls
    python run_daily.py --date 2026-08-19

Scheduling: runs at 16:20 New York time, twenty minutes after the bell, so the
closing auction has settled and vendors have consolidated the official close.
If the NYSE did not trade, the run exits without publishing.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--half-day", action="store_true", dest="half")
    args = ap.parse_args()

    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    if not args.force and not args.demo:
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
        except Exception as e:  # noqa: BLE001
            log.error("Writer unavailable (%s). Publishing in quantitative mode.", e)
            note = write_without_model(facts)
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
