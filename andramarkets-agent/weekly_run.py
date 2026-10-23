#!/usr/bin/env python3
"""Andra Markets weekly review.

    python weekly_run.py                          the week of the last session
    python weekly_run.py --week-ending 2026-10-16 a given week
    python weekly_run.py --from DIR --no-model    archived facts on disk, no model
    python weekly_run.py --no-mail                build only

Reads the week's archived daily fact packs (the archive-YYYY-MM-DD releases,
fetched with the REST API and GH_TOKEN) and the site's economic calendar,
builds the weekly fact pack (andra/weekly.py), writes the review with the
model under the same figure check as the daily note, and renders the A4 note
and the LinkedIn carousel in the house style (andra/weekly_render.py).
Without ANTHROPIC_API_KEY, or with --no-model, the review is set from the
figures alone. Email only goes out when SMTP is configured and --no-mail is
not given; the Weekly review workflow passes --no-mail on manual runs unless
asked to send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from andra import weekly, weekly_render
from andra.narrative import audit

logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                    format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("andra.weekly")

ROOT = Path(__file__).resolve().parent
_FACTS = re.compile(r"facts_\d{8}_r\d+\.json")


def default_friday(now: dt.datetime | None = None) -> dt.date:
    """Friday of the week of the last finished NYSE session."""
    from zoneinfo import ZoneInfo
    from andra.session import last_completed
    d = last_completed(now or dt.datetime.now(ZoneInfo("America/New_York")))
    return d + dt.timedelta(days=4 - d.weekday())


def fetch_week(friday: dt.date, dest: Path, repo: str) -> int:
    """Every archived fact pack filed from ten days before the week to three
    days after it (archive labels can trail the session), into dest."""
    lo = friday - dt.timedelta(days=friday.weekday() + 10)
    hi = friday + dt.timedelta(days=3)
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for page in range(1, 4):
        res = subprocess.run(["gh", "api", f"repos/{repo}/releases?per_page=100&page={page}"],
                             check=True, text=True, capture_output=True)
        rels = json.loads(res.stdout or "[]")
        for rel in rels:
            tag = rel.get("tag_name", "")
            try:
                day = dt.date.fromisoformat(tag.removeprefix("archive-"))
            except ValueError:
                continue
            if not (tag.startswith("archive-") and lo <= day <= hi):
                continue
            for a in rel.get("assets", []):
                if _FACTS.fullmatch(a["name"]) and not (dest / a["name"]).exists():
                    body = subprocess.run(
                        ["gh", "api", "-H", "Accept: application/octet-stream",
                         f"repos/{repo}/releases/assets/{a['id']}"],
                        check=True, capture_output=True).stdout
                    (dest / a["name"]).write_bytes(body)
                    n += 1
        if len(rels) < 100:
            break
    log.info("Fetched %d archived fact pack(s) filed %s to %s.", n, lo, hi)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-ending", help="the week's Friday, YYYY-MM-DD")
    ap.add_argument("--from", dest="src", help="folder of archived facts_*.json")
    ap.add_argument("--calendar-dir", help="folder of calendar week pages, <monday>.html")
    ap.add_argument("--no-calendar", action="store_true")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = ap.parse_args(argv)

    friday = (dt.date.fromisoformat(args.week_ending) if args.week_ending
              else default_friday())
    if friday.weekday() != 4:
        friday += dt.timedelta(days=4 - friday.weekday())
    log.info("Weekly review for the week ending %s.", friday)

    src = Path(args.src) if args.src else ROOT / "weekly" / friday.isoformat() / "input"
    if not args.src:
        if not args.repo:
            sys.exit("GITHUB_REPOSITORY is not set: pass --repo or --from.")
        fetch_week(friday, src, args.repo)

    snaps = weekly.load_snapshots(src)
    monday = friday - dt.timedelta(days=friday.weekday())
    sessions = weekly.nyse_sessions(monday - dt.timedelta(days=21), friday + dt.timedelta(days=3))
    by_session = weekly.resolve_sessions(snaps, sessions)

    calendar = {}
    if not args.no_calendar:
        pages = None
        if args.calendar_dir:
            pages = {p.stem: p.read_text(encoding="utf-8")
                     for p in Path(args.calendar_dir).glob("*.html")}
        calendar = weekly.site_calendar(friday, pages)
    facts = weekly.week_facts(by_session, friday, calendar)
    w = facts["week"]
    log.info("Sessions: %d of %d archived%s. Prior close: %s (%s). Calendar: %s.",
             len(w["archived"]), len(w["sessions"]),
             f", missing {', '.join(w['missing'])}" if w["missing"] else "",
             w["prior_close"], w["prior_close_from"],
             "read" if facts["calendar_source"] else "unavailable")

    mode = "model"
    if args.no_model or not os.getenv("ANTHROPIC_API_KEY", "").strip():
        note, mode = weekly.write_without_model(facts), "quantitative"
    else:
        try:
            note = weekly.write(facts)
        except Exception:  # noqa: BLE001
            log.exception("Writer unavailable. Publishing in quantitative mode.")
            note, mode = weekly.write_without_model(facts), "quantitative"
    # The figure check, on the text as it will print.
    note.unsupported = audit(note.content, facts)
    note.audit_ok = not note.unsupported
    log.info("Figure check: %s (%d attempts)",
             "passed" if note.audit_ok else f"FAILED {note.unsupported}", note.attempts)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = friday.strftime("%Y%m%d")
    with tempfile.TemporaryDirectory() as tmp:
        ex = weekly_render.build_exhibits(facts, tmp)
        ctx = weekly_render.build_context(facts, note, ex)
        report = str(out / f"AndraMarkets_Weekly_{stamp}.pdf")
        carousel = str(out / f"AndraMarkets_Weekly_LinkedIn_{stamp}.pdf")
        weekly_render.report_pdf(ctx, report)
        weekly_render.linkedin_pdf(ctx, carousel)
    caption = weekly_render.linkedin_caption(note, ctx)
    (out / f"weekly_linkedin_caption_{stamp}.txt").write_text(caption, encoding="utf-8")
    (out / f"weekly_facts_{stamp}.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / f"weekly_note_{stamp}.json").write_text(
        json.dumps(note.content, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"weekly_manifest_{stamp}.json").write_text(json.dumps({
        "week_ending": friday.isoformat(), "audit_ok": note.audit_ok,
        "unsupported": note.unsupported, "attempts": note.attempts, "mode": mode,
        "sessions_archived": w["archived"], "sessions_missing": w["missing"],
        "prior_close_from": w["prior_close_from"],
        "calendar": bool(facts["calendar_source"]),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Built the weekly review and carousel in %s.", out)

    if args.no_mail:
        log.info("Email skipped.")
        return 0
    from andra.mailer import send_weekly
    send_weekly(caption, [carousel, report], ctx["date_short"], note.content["headline"],
                note.audit_ok, mode, w["missing"], bool(facts["calendar_source"]))
    log.info("Delivered to %s", os.environ["MAIL_TO"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
