#!/usr/bin/env python3
"""Run monitoring: a GitHub issue whenever a close note goes missing.

    python monitor.py failed-run RUN_ID     a scheduled daily run failed
    python monitor.py check                 22:45 UTC: is today's note there?
    python monitor.py check --date 2026-10-21 --dry-run

Two ways a note goes missing, one issue title for both, "Missed close note:
<session date>", so a day never gets two issues:

  failed-run  The Run monitoring workflow calls this when a scheduled run of
              Daily market close ends in failure. The issue names the failed
              step and quotes the end of its log.
  check       At 22:45 UTC on weekdays. If NYSE traded today and no note has
              been produced for the session, the issue says so, with the
              day's runs and, if one failed, its failed step and log. A day
              whose note did come out after an earlier failure has its issue
              closed with a comment saying which run produced it.

A note counts as produced when the session's archive release
(archive-YYYY-MM-DD) holds a report PDF. Nothing is emailed. Runs inside
Actions with GH_TOKEN set to the workflow token (issues: write, actions: read)
and talks to the REST API through the gh CLI; the token is never printed.
GitHub masks secrets in the logs this quotes.
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
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                    format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("andra.monitor")

NY = ZoneInfo("America/New_York")
WORKFLOW = "daily-close.yml"
TITLE = "Missed close note: {date}"
EXCERPT_LINES = 40
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")


# ---------------------------------------------------------------- GitHub
def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        sys.exit("GITHUB_REPOSITORY is not set.")
    return repo


def _api(path: str, *args: str, check: bool = True):
    res = subprocess.run(["gh", "api", path, *args], text=True, capture_output=True)
    if res.returncode != 0:
        if check:
            raise RuntimeError(f"gh api {path}: {res.stderr.strip()[:300]}")
        return None
    out = res.stdout.strip()
    try:
        return json.loads(out) if out else None
    except ValueError:
        return out


def note_produced(repo: str, date: dt.date) -> bool:
    rel = _api(f"repos/{repo}/releases/tags/archive-{date}", check=False)
    stamp = date.strftime("%Y%m%d")
    return bool(rel) and any(a["name"].startswith(f"AndraMarkets_Close_{stamp}_r")
                             for a in rel.get("assets", []))


def day_runs(repo: str, date: dt.date) -> list[dict]:
    """Daily close runs created on the session's New York date, oldest first."""
    lo = dt.datetime.combine(date, dt.time(0, 0), NY).astimezone(dt.timezone.utc)
    hi = lo + dt.timedelta(days=1, hours=6)
    res = _api(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=50"
               f"&created={lo:%Y-%m-%dT%H:%M:%SZ}..{hi:%Y-%m-%dT%H:%M:%SZ}")
    return sorted(res.get("workflow_runs", []), key=lambda r: r["created_at"])


def failed_steps(repo: str, run_id) -> list[tuple[dict, dict]]:
    """(job, step) for every step that failed in the run."""
    jobs = _api(f"repos/{repo}/actions/runs/{run_id}/jobs").get("jobs", [])
    return [(j, s) for j in jobs for s in j.get("steps", [])
            if s.get("conclusion") == "failure"]


def log_excerpt(raw: str, n: int = EXCERPT_LINES) -> str:
    """The failing step's own output, last n lines, timestamps off.

    The job log runs every step in order: a "##[group]Run" header holding the
    command and its environment (secret values already masked as ***), an
    "##[endgroup]", then the output. The excerpt is the output between the
    header of the step that failed and its first ##[error]; later lines are
    other steps and cleanup. Without an error it is the tail of the log.
    """
    lines = [_STAMP.sub("", ln) for ln in raw.splitlines()]
    end = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("##[error]")),
               len(lines))
    start = max((i + 1 for i, ln in enumerate(lines[:end]) if ln.startswith("##[endgroup]")),
                default=0)
    lines = [ln for ln in lines[start:end] if not ln.startswith(("##[group]", "##[endgroup]"))]
    return "\n".join(lines[-n:]).replace("```", "'''")


def job_log(repo: str, job_id) -> str:
    res = subprocess.run(["gh", "api", f"repos/{repo}/actions/jobs/{job_id}/logs"],
                         text=True, capture_output=True)
    return res.stdout if res.returncode == 0 else ""


def find_issue(repo: str, title: str) -> dict | None:
    """The newest issue with exactly this title, open first."""
    found = []
    for page in range(1, 6):
        items = _api(f"repos/{repo}/issues?state=all&per_page=100&page={page}") or []
        found += [i for i in items if i["title"] == title and "pull_request" not in i]
        if len(items) < 100:
            break
    found.sort(key=lambda i: (i["state"] != "open", -i["number"]))
    return found[0] if found else None


def post(repo: str, title: str, body: str, dry: bool) -> None:
    """Open the issue, or comment on it if one with this title is open."""
    if dry:
        print(f"--- would post: {title}\n{body}")
        return
    have = find_issue(repo, title)
    if have and have["state"] == "open":
        _api(f"repos/{repo}/issues/{have['number']}/comments", "-f", f"body={body}")
        log.info("Commented on #%s.", have["number"])
    else:
        made = _api(f"repos/{repo}/issues", "-f", f"title={title}", "-f", f"body={body}")
        log.info("Opened #%s: %s", made["number"], title)


def close_recovered(repo: str, date: dt.date, dry: bool) -> None:
    have = find_issue(repo, TITLE.format(date=date))
    if not have or have["state"] != "open":
        return
    runs = [r for r in day_runs(repo, date) if r.get("conclusion") == "success"]
    by = f" by [run {runs[-1]['id']}]({runs[-1]['html_url']})" if runs else ""
    msg = (f"The {date} note was produced{by} after all; it is in the "
           f"archive-{date} release. Closing.")
    if dry:
        print(f"--- would close #{have['number']}: {msg}")
        return
    _api(f"repos/{repo}/issues/{have['number']}/comments", "-f", f"body={msg}")
    _api(f"repos/{repo}/issues/{have['number']}", "-X", "PATCH",
         "-f", "state=closed", "-f", "state_reason=completed")
    log.info("Closed #%s: the note was produced.", have["number"])


# ------------------------------------------------------------------ bodies
def describe_failure(repo: str, run: dict) -> str:
    steps = failed_steps(repo, run["id"])
    lines = [f"Run: [{run.get('display_title') or run['name']} #{run.get('run_number')}]"
             f"({run['html_url']}), {run.get('event')}, started {run.get('run_started_at') or run['created_at']}, "
             f"conclusion **{run.get('conclusion') or run.get('status')}**."]
    if not steps:
        lines.append("\nNo step reported a failure (cancelled, timed out, or "
                     "failed while setting up the job).")
        return "\n".join(lines)
    names = ", ".join(f"`{s['name']}`" for _, s in steps)
    lines.append(f"\nFailing step: {names}")
    job, _ = steps[0]
    raw = job_log(repo, job["id"])
    if raw:
        lines += [f"\nLog, last {EXCERPT_LINES} lines up to the first error:",
                  "", "```", log_excerpt(raw), "```"]
    else:
        lines.append(f"\nThe log could not be read; see {job.get('html_url', run['html_url'])}.")
    return "\n".join(lines)


def session_of_run(run: dict) -> dt.date:
    """The session a run was for: its New York date if NYSE traded that day,
    else the last session before it."""
    from andra.session import last_completed
    started = dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(NY)
    end_of_day = dt.datetime.combine(started.date(), dt.time(23, 59), NY)
    return last_completed(end_of_day)


# -------------------------------------------------------------------- modes
def on_failed_run(repo: str, run_id: str, dry: bool) -> int:
    run = _api(f"repos/{repo}/actions/runs/{run_id}")
    if run.get("conclusion") != "failure":
        log.info("Run %s ended %s: nothing to report.", run_id, run.get("conclusion"))
        return 0
    if run.get("event") != "schedule":
        log.info("Run %s was started by %s, not the schedule: not reported.",
                 run_id, run.get("event"))
        return 0
    date = session_of_run(run)
    if note_produced(repo, date):
        # The other firing of the day already produced the note: nothing is
        # missing, and the failure stays visible on the run itself.
        log.info("Run %s failed, but the %s note is already archived.", run_id, date)
        return 0
    body = (f"A scheduled run of Daily market close failed and no note for the "
            f"**{date}** session has been produced.\n\n" + describe_failure(repo, run))
    post(repo, TITLE.format(date=date), body, dry)
    return 0


def check(repo: str, date: dt.date | None, dry: bool) -> int:
    from andra.session import todays_session
    if date is None:
        date = todays_session(dt.datetime.now(NY))
        if date is None:
            log.info("No NYSE session closed today: nothing to check.")
            return 0
    if note_produced(repo, date):
        log.info("The %s note is in the archive.", date)
        close_recovered(repo, date, dry)
        return 0

    runs = day_runs(repo, date)
    lines = [f"No close note has been produced for the **{date}** session by "
             f"{dt.datetime.now(dt.timezone.utc):%H:%M} UTC: there is no report "
             f"PDF in the archive-{date} release.", ""]
    if not runs:
        lines.append("No run of Daily market close started that day (the "
                     "scheduler skipped it, or the workflow is disabled).")
    else:
        lines.append("Runs that day:")
        lines += [f"- [#{r.get('run_number')}]({r['html_url']}) {r['event']}, "
                  f"{r['created_at']}: {r.get('conclusion') or r['status']}" for r in runs]
        failed = [r for r in runs if r.get("conclusion") == "failure"]
        if failed:
            lines += ["", describe_failure(repo, failed[-1])]
        elif all(r.get("conclusion") == "success" for r in runs):
            lines += ["", "Every run succeeded without producing a note: they "
                      "stopped early (before the close, or on the dedup marker). "
                      "Check the session date and `.last_published`."]
    post(repo, TITLE.format(date=date), "\n".join(lines), dry)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("failed-run")
    f.add_argument("run_id")
    c = sub.add_parser("check")
    c.add_argument("--date")
    for p in (f, c):
        p.add_argument("--dry-run", action="store_true",
                       help="print the issue instead of posting it")
    args = ap.parse_args(argv)
    repo = _repo()
    if args.cmd == "failed-run":
        return on_failed_run(repo, args.run_id, args.dry_run)
    return check(repo, dt.date.fromisoformat(args.date) if args.date else None,
                 args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
