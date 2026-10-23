import datetime as dt

import pytest

import monitor

REPO = "o/r"

# The shape of a real failed job log (13 Oct 2026), trimmed.
LOG = """2026-10-13T22:20:36.0Z ##[group]Run python run_daily.py
2026-10-13T22:20:36.1Z python run_daily.py
2026-10-13T22:20:36.2Z env:
2026-10-13T22:20:36.3Z   ANTHROPIC_API_KEY: ***
2026-10-13T22:20:36.4Z   SMTP_PASSWORD: ***
2026-10-13T22:20:36.5Z ##[endgroup]
2026-10-13T22:20:54.4Z 22:20:54  INFO    andra | Snapshot ready: 119 series, 6 with no print.
2026-10-13T22:22:20.2Z Traceback (most recent call last):
2026-10-13T22:22:20.2Z     ex = render.build_exhibits(mf, tmp)
2026-10-13T22:22:20.2Z NameError: name 'charts' is not defined
2026-10-13T22:22:20.4Z ##[error]Process completed with exit code 1.
2026-10-13T22:22:20.4Z ##[group]Run git config user.name "andra-bot"
2026-10-13T22:22:20.6Z Everything up-to-date
2026-10-13T22:22:20.9Z Cleaning up orphan processes
"""


def test_excerpt_is_the_failing_steps_output():
    ex = monitor.log_excerpt(LOG)
    assert ex.splitlines()[0].endswith("Snapshot ready: 119 series, 6 with no print.")
    assert "NameError: name 'charts' is not defined" in ex
    assert ex.splitlines()[-1] == "##[error]Process completed with exit code 1."
    # Not the step's environment, not the steps after it.
    assert "API_KEY" not in ex and "SMTP" not in ex
    assert "Everything up-to-date" not in ex
    assert not any(ln[:4].isdigit() for ln in ex.splitlines())


def test_excerpt_without_an_error_is_the_tail():
    raw = "\n".join(f"2026-10-13T00:00:00.0Z line {i}" for i in range(100))
    assert monitor.log_excerpt(raw, n=3) == "line 97\nline 98\nline 99"


class Fake:
    """Answers gh api calls from a table and records what is posted."""

    def __init__(self, produced=False, runs=(), issues=()):
        self.produced, self.runs, self.issues = produced, list(runs), list(issues)
        self.posted = []

    def api(self, path, *args, check=True):
        if args and "-f" in args:
            self.posted.append((path, args))
            return {"number": 99}
        if "/releases/tags/" in path:
            if not self.produced:
                return None
            stamp = path.rsplit("archive-", 1)[1].replace("-", "")
            return {"assets": [{"name": f"AndraMarkets_Close_{stamp}_r1.pdf"}]}
        if path.endswith("/jobs"):
            return {"jobs": [{"id": 7, "html_url": "u", "steps": [
                {"name": "Dependencies", "conclusion": "success"},
                {"name": "Build and publish", "conclusion": "failure"}]}]}
        if "/actions/runs/" in path:
            return next(r for r in self.runs if path.endswith(str(r["id"])))
        if "/workflows/" in path:
            return {"workflow_runs": self.runs}
        if "/issues?" in path:
            return self.issues
        raise AssertionError(path)


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        f = Fake(**kw)
        monkeypatch.setattr(monitor, "_api", f.api)
        monkeypatch.setattr(monitor, "job_log", lambda repo, job: LOG)
        return f
    return make


def run(event="schedule", conclusion="failure", created="2026-10-21T21:30:12Z", id=5):
    return {"id": id, "event": event, "conclusion": conclusion, "status": "completed",
            "created_at": created, "run_started_at": created, "name": "Daily market close",
            "run_number": 101, "html_url": f"https://x/runs/{id}"}


def test_scheduled_failure_opens_an_issue_with_step_and_log(fake):
    f = fake(runs=[run()])
    monitor.on_failed_run(REPO, "5", dry=False)
    (path, args), = f.posted
    assert path == f"repos/{REPO}/issues"
    assert "title=Missed close note: 2026-10-21" in args
    body = next(a for a in args if a.startswith("body="))
    assert "Failing step: `Build and publish`" in body
    assert "NameError: name 'charts' is not defined" in body


def test_failure_on_a_trading_day_before_its_close_is_that_days_session(fake):
    # 20:30 UTC in winter is 3:30 pm ET: the run was for that day's session.
    f = fake(runs=[run(created="2026-12-01T20:30:05Z")])
    monitor.on_failed_run(REPO, "5", dry=False)
    assert "title=Missed close note: 2026-12-01" in f.posted[0][1]


def test_manual_or_successful_runs_are_not_reported(fake):
    f = fake(runs=[run(event="workflow_dispatch"), run(conclusion="success", id=6)])
    monitor.on_failed_run(REPO, "5", dry=False)
    monitor.on_failed_run(REPO, "6", dry=False)
    assert f.posted == []


def test_failure_after_the_note_came_out_is_not_a_missed_note(fake):
    f = fake(produced=True, runs=[run()])
    monitor.on_failed_run(REPO, "5", dry=False)
    assert f.posted == []


def test_an_open_issue_gets_a_comment_not_a_second_issue(fake):
    f = fake(runs=[run()], issues=[{"number": 12, "title": "Missed close note: 2026-10-21",
                                    "state": "open"}])
    monitor.on_failed_run(REPO, "5", dry=False)
    assert f.posted[0][0] == f"repos/{REPO}/issues/12/comments"


def test_check_with_no_run_at_all(fake):
    f = fake(runs=[])
    monitor.check(REPO, dt.date(2026, 10, 21), dry=False)
    body = next(a for a in f.posted[0][1] if a.startswith("body="))
    assert "No run of Daily market close started" in body


def test_check_quotes_the_failed_run(fake):
    f = fake(runs=[run(conclusion="failure")])
    monitor.check(REPO, dt.date(2026, 10, 21), dry=False)
    body = next(a for a in f.posted[0][1] if a.startswith("body="))
    assert "Failing step: `Build and publish`" in body


def test_check_closes_the_issue_once_the_note_is_out(fake):
    f = fake(produced=True, runs=[run(conclusion="success")],
             issues=[{"number": 12, "title": "Missed close note: 2026-10-21", "state": "open"}])
    monitor.check(REPO, dt.date(2026, 10, 21), dry=False)
    paths = [p for p, _ in f.posted]
    assert paths == [f"repos/{REPO}/issues/12/comments", f"repos/{REPO}/issues/12"]
    assert "state=closed" in f.posted[1][1]


def test_check_on_a_day_nyse_did_not_trade_does_nothing(fake, monkeypatch):
    f = fake()
    import andra.session as s
    monkeypatch.setattr(s, "todays_session", lambda now: None)
    monitor.check(REPO, None, dry=False)
    assert f.posted == []


def man(date, run, tin=20000, tout=3000, model=40.0, total=90.0):
    return {"date": date, "run": str(run), "tokens": {"input": tin, "output": tout},
            "model_seconds": model, "run_seconds": total}


BASE = [man(f"2026-10-{d:02d}", d) for d in (5, 6, 8, 9, 12, 13, 14, 15, 16, 19, 20, 21, 22)]


def test_quiet_week_has_no_summary():
    rows = BASE + [man("2026-10-26", 100), man("2026-10-30", 101, model=79.0)]
    assert monitor.cost_summary(rows, dt.date(2026, 10, 30)) is None


def test_a_run_over_twice_the_median_is_summarised():
    rows = BASE + [man("2026-10-26", 100), man("2026-10-29", 101, tout=16000, model=130.0)]
    s = monitor.cost_summary(rows, dt.date(2026, 10, 30))
    assert "week ending 2026-10-30" in s
    assert "2026-10-29 (run 101): output tokens 16,000, 5.3x the median of 3,000" in s
    assert "model time, s 130, 3.2x" in s
    assert "input tokens" in s and "run 100" not in s


def test_baseline_is_the_four_weeks_before_only():
    # A heavy run five weeks back does not move the median; one this week
    # does not count in its own baseline.
    rows = [man("2026-09-25", 1, tout=90000)] + BASE + [man("2026-10-29", 2, tout=6001)]
    assert "output tokens 6,001" in monitor.cost_summary(rows, dt.date(2026, 10, 30))


def test_too_little_history_flags_nothing():
    rows = BASE[:3] + [man("2026-10-29", 2, tout=60000)]
    assert monitor.cost_summary(rows, dt.date(2026, 10, 30)) is None


def test_manifests_without_metrics_are_ignored():
    rows = [{"date": "2026-10-22", "run": "1", "audit_ok": True}] + BASE[:2]
    assert monitor.cost_summary(rows, dt.date(2026, 10, 23)) is None


def test_friday_summary_goes_into_the_missed_note_issue(fake, monkeypatch):
    f = fake(runs=[])
    monkeypatch.setattr(monitor, "weekly", lambda repo, d: "### Cost and timing, week ending x")
    monitor.check(REPO, dt.date(2026, 10, 23), dry=False)
    (path, args), = f.posted
    assert "title=Missed close note: 2026-10-23" in args
    assert any("### Cost and timing" in a for a in args)


def test_friday_summary_alone_gets_its_own_issue(fake, monkeypatch):
    f = fake(produced=True)
    monkeypatch.setattr(monitor, "weekly", lambda repo, d: "### Cost and timing")
    monitor.check(REPO, dt.date(2026, 10, 23), dry=False)
    (path, args), = f.posted
    assert "title=Run monitoring: week ending 2026-10-23" in args


def test_other_days_never_read_the_manifests(fake, monkeypatch):
    fake(produced=True)
    monkeypatch.setattr(monitor, "weekly", lambda *a: pytest.fail("read on a Wednesday"))
    monitor.check(REPO, dt.date(2026, 10, 21), dry=False)
