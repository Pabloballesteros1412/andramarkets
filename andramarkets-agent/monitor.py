#!/usr/bin/env python3
"""Run monitoring: a GitHub issue whenever a close note goes missing.

    python monitor.py failed-run RUN_ID     a scheduled daily run failed
    python monitor.py check                 22:45 UTC: is today's note there?
    python monitor.py check --date 2026-10-21 --dry-run
    python monitor.py weekly --date 2026-10-23 --dry-run

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

On Fridays the check also reads the week's run manifests (tokens, model
time, run time) and, if any run used more than twice the median of the four
weeks before, adds a short summary to the monitoring issue: the day's
"Missed close note" issue if there is one, otherwise an issue of its own,
"Run monitoring: week ending <date>". A quiet week posts nothing.

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
WEEKLY_TITLE = "Run monitoring: week ending {date}"
# (label, how to read it from a manifest). Manifests from before 23 Oct 2026
# carry none of these and are left out.
METRICS = (
    ("input tokens", lambda m: (m.get("tokens") or {}).get("input")),
    ("output tokens", lambda m: (m.get("tokens") or {}).get("output")),
    ("model time, s", lambda m: m.get("model_seconds")),
    ("run time, s", lambda m: m.get("run_seconds")),
)
BASELINE_WEEKS = 4
MIN_BASELINE = 5      # runs needed before a median means anything
_MANIFEST = re.compile(r"manifest_(\d{8})_r(\d+)\.json")
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


# ------------------------------------------------------------ cost, timing
def manifests(repo: str, start: dt.date, end: dt.date) -> list[dict]:
    """Every archived non-demo manifest for sessions start..end, with
    `date` and `run` filled in."""
    out = []
    for page in range(1, 4):
        rels = _api(f"repos/{repo}/releases?per_page=100&page={page}") or []
        for rel in rels:
            tag = rel.get("tag_name", "")
            if not tag.startswith("archive-"):
                continue
            try:
                day = dt.date.fromisoformat(tag[len("archive-"):])
            except ValueError:
                continue
            if not start <= day <= end:
                continue
            for a in rel.get("assets", []):
                m = _MANIFEST.fullmatch(a["name"])
                if not m:
                    continue
                man = _api(f"repos/{repo}/releases/assets/{a['id']}",
                           "-H", "Accept: application/octet-stream", check=False)
                if isinstance(man, dict) and not man.get("demo"):
                    out.append({**man, "date": day.isoformat(), "run": m.group(2)})
        if len(rels) < 100:
            break
    return out


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def cost_summary(rows: list[dict], end: dt.date) -> str | None:
    """A short summary of the week ending `end` if any run used more than
    twice its metric's median over the four weeks before; None otherwise."""
    monday = end - dt.timedelta(days=end.weekday())
    base_from = monday - dt.timedelta(weeks=BASELINE_WEEKS)
    week = [r for r in rows if monday.isoformat() <= r["date"] <= end.isoformat()]
    base = [r for r in rows if base_from.isoformat() <= r["date"] < monday.isoformat()]

    table, over = [], []
    for label, get in METRICS:
        hist = [float(v) for v in map(get, base) if v is not None]
        now = [(r, float(get(r))) for r in week if get(r) is not None]
        if not now:
            continue
        top = max(v for _, v in now)
        if len(hist) < MIN_BASELINE:
            table.append(f"| {label} | {top:,.0f} | n/a ({len(hist)} runs) | |")
            continue
        med = _median(hist)
        hits = [(r, v) for r, v in now if med > 0 and v > 2 * med]
        table.append(f"| {label} | {top:,.0f} | {med:,.0f} | "
                     f"{'**over 2x**' if hits else ''} |")
        over += [f"- {r['date']} (run {r['run']}): {label} {v:,.0f}, "
                 f"{v / med:.1f}x the median of {med:,.0f}" for r, v in hits]
    if not over:
        return None
    return "\n".join([
        f"### Cost and timing, week ending {end}",
        "",
        f"{len(week)} run(s) this week against the median of {len(base)} run(s) "
        f"from {base_from} to {monday - dt.timedelta(days=1)}.",
        "",
        "| metric | highest this week | 4-week median | |",
        "|---|---|---|---|",
        *table,
        "",
        "Over twice the median:",
        *over,
    ])


def weekly(repo: str, end: dt.date) -> str | None:
    start = end - dt.timedelta(days=end.weekday()) - dt.timedelta(weeks=BASELINE_WEEKS)
    return cost_summary(manifests(repo, start, end), end)


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
    summary = weekly(repo, date) if date.weekday() == 4 else None
    if note_produced(repo, date):
        log.info("The %s note is in the archive.", date)
        close_recovered(repo, date, dry)
        if summary:
            post(repo, WEEKLY_TITLE.format(date=date), summary, dry)
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
    if summary:
        lines += ["", summary]
    post(repo, TITLE.format(date=date), "\n".join(lines), dry)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("failed-run")
    f.add_argument("run_id")
    c = sub.add_parser("check")
    c.add_argument("--date")
    w = sub.add_parser("weekly", help="the cost and timing summary alone")
    w.add_argument("--date", required=True, help="last day of the week")
    for p in (f, c, w):
        p.add_argument("--dry-run", action="store_true",
                       help="print the issue instead of posting it")
    args = ap.parse_args(argv)
    repo = _repo()
    if args.cmd == "failed-run":
        return on_failed_run(repo, args.run_id, args.dry_run)
    if args.cmd == "weekly":
        end = dt.date.fromisoformat(args.date)
        summary = weekly(repo, end)
        if summary:
            post(repo, WEEKLY_TITLE.format(date=end), summary, args.dry_run)
        else:
            log.info("Week ending %s: nothing over twice its 4-week median.", end)
        return 0
    return check(repo, dt.date.fromisoformat(args.date) if args.date else None,
                 args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
