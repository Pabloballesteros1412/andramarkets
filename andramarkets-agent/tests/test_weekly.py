import datetime as dt
import json
import sys
import types

import pytest

from andra import weekly
from andra.narrative import audit

# A calendar week as the site renders it (tools/build_site.py, cal_table),
# made with the site's own code from three sample events.
PAGE = '<div class="cl-wrap"><table class="cl__table" aria-label="Calendar"><thead><tr><th scope="col">New York</th><th scope="col">Madrid</th><th scope="col">Event</th><th scope="col">Region</th><th scope="col">Type</th><th scope="col">Importance</th><th scope="col">Previous</th><th scope="col">Actual</th></tr></thead><tbody class="cl__day-group" id="d-2026-10-14" data-day="2026-10-14" data-week="2026-10-12"><tr class="cl__day"><th scope="rowgroup" colspan="8" data-label="Wednesday 14 Oct">Wednesday 14 Oct</th></tr><tr class="cl__row" data-type="macro" data-region="US" data-imp="High"><td class="cl__ny"><time datetime="2026-10-14T12:30:00+00:00">8:30 am</time></td><td class="cl__md">2:30 pm</td><th scope="row"><span class="cl__ev"><a class="cl__src" href="https://www.bls.gov">Consumer price index, Sep 2026</a></span><span class="cl__meta"><span class="cl__mregion">US. </span>Bureau of Labor Statistics</span></th><td class="cl__region">US</td><td class="cl__type"><span class="tag">Macro</span></td><td class="cl__imp" data-imp="High">High</td><td class="cl__prior" data-label="Previous">+0.4%</td><td class="cl__actual" data-label="Actual"><a class="cl__act" href="https://www.bls.gov">+0.3% <svg class="icon" aria-hidden="true"><use href="#i-arrow-up-right"/></svg></a></td></tr><tr class="cl__row" data-type="earnings" data-region="US" data-er="us" data-imp="High"><td class="cl__ny" colspan="2">Before open</td><th scope="row"><span class="cl__ev">JPMorgan Chase</span><span class="cl__meta"><span class="cl__mregion">US. </span>Yahoo Finance</span><span class="cl__tags"><span class="tag">Confirmed date</span></span></th><td class="cl__region">US</td><td class="cl__type"><span class="tag">Earnings</span></td><td class="cl__imp" data-imp="High">High</td><td class="cl__prior" data-label="Year ago">$4.37, Q3 2025</td><td class="cl__actual" data-label="Actual"><a class="cl__act" href="https://finance.yahoo.com">$4.81 <svg class="icon" aria-hidden="true"><use href="#i-arrow-up-right"/></svg></a><span class="cl__react"><span class="cl__rlabel">First session</span> <span class="mv mv--down">\u22121.72%</span><span class="cl__bench">, S&amp;P 500 <span class="mv mv--down">\u22121.11%</span></span></span></td></tr></tbody><tbody class="cl__day-group" id="d-2026-10-15" data-day="2026-10-15" data-week="2026-10-12"><tr class="cl__day"><th scope="rowgroup" colspan="8" data-label="Thursday 15 Oct">Thursday 15 Oct</th></tr><tr class="cl__row" data-type="macro" data-region="US" data-imp="Medium"><td class="cl__ny"><time datetime="2026-10-15T12:30:00+00:00">8:30 am</time></td><td class="cl__md">2:30 pm</td><th scope="row"><span class="cl__ev"><a class="cl__src" href="https://www.dol.gov">Initial jobless claims</a></span><span class="cl__meta"><span class="cl__mregion">US. </span>Bureau of Labor Statistics</span></th><td class="cl__region">US</td><td class="cl__type"><span class="tag">Macro</span></td><td class="cl__imp" data-imp="Medium">Medium</td><td class="cl__prior" data-label="Previous">231K</td><td class="cl__actual" data-label="Actual"><a class="cl__act" href="https://www.dol.gov">224K <svg class="icon" aria-hidden="true"><use href="#i-arrow-up-right"/></svg></a></td></tr></tbody></table><p class="cl__empty" hidden>Nothing matches these filters this week.</p></div>'


def _next_week(title="Nonfarm payrolls, Oct 2026"):
    return PAGE.replace("2026-10-14", "2026-10-21").replace("2026-10-15", "2026-10-22") \
               .replace("Consumer price index, Sep 2026", title)


def test_calendar_rows_are_read_with_their_figures():
    cpi, jpm, claims = weekly.parse_calendar(PAGE)
    assert cpi["title"] == "Consumer price index, Sep 2026" and cpi["date"] == "2026-10-14"
    assert (cpi["type"], cpi["imp"], cpi["country"]) == ("macro", "High", "US")
    assert (cpi["previous"], cpi["actual"], cpi["time"]) == ("+0.4%", "+0.3%", "8:30 am")
    assert cpi["values"] == [0.4, 0.3]
    assert jpm["type"] == "earnings" and jpm["actual"] == "$4.81"
    # The site prints a fall with a true minus sign; it reads as negative.
    assert jpm["reaction"].startswith("-1.72%") and -1.72 in jpm["values"]
    assert claims["imp"] == "Medium" and claims["actual"] == "224K"


def test_site_calendar_keeps_high_importance_and_next_week():
    cal = weekly.site_calendar(dt.date(2026, 10, 16),
                               {"2026-10-12": PAGE, "2026-10-19": _next_week()})
    assert [e["title"] for e in cal["macro"]] == ["Consumer price index, Sep 2026"]
    assert [e["title"] for e in cal["earnings"]] == ["JPMorgan Chase"]
    assert "Nonfarm payrolls, Oct 2026" in [e["title"] for e in cal["week_ahead"]]
    assert cal["source"].endswith("/calendar/week/2026-10-12/")


def test_unreadable_calendar_gives_nothing():
    assert weekly.site_calendar(dt.date(2026, 10, 16), {}) == {}


# ------------------------------------------------------------ the archive
def facts(day, spx, spx_chg, ten, ten_chg, xlk=200.0, xlk_chg=0.5):
    def row(k, n, last, chg):
        return {"key": k, "name": n, "last": last, "chg": chg, "ytd": 1.0}
    return {"date": day,
            "us_equity": [row("spx", "S&P 500", spx, spx_chg)],
            "sectors": [row("xlk", "Technology", xlk, xlk_chg)],
            "treasury_curve": [row("ust10y", "10 year", ten, ten_chg)],
            "fx": [row("eurusd", "EUR/USD", 1.15, 0.1)],
            "risk_barometer": {"score": 0.2, "label": "Neutral"},
            "series_not_yet_published": []}


def chain(start, moves):
    """Closes that chain: each day's change is on the day before."""
    out, last = [], start
    for m in moves:
        last = round(last * (1 + m / 100), 2)
        out.append((last, m))
    return out


def snap(label, run, f):
    return weekly.Snapshot(dt.date.fromisoformat(label), run, f)


SESSIONS = weekly.nyse_sessions(dt.date(2026, 9, 28), dt.date(2026, 10, 23))


def week_of_oct_16(drop=()):
    """Fri 9 Oct, then 12 to 16 Oct, filed the way the archive filed them
    before 23 October: the 13 Oct close by a run on the morning of the 14th,
    the 16 Oct close by a Saturday run, the 9 Oct close twice."""
    closes = chain(7764.4, [0.6, -0.055, -0.023, -1.108, 0.325, -1.093])
    labels = ["2026-10-09", "2026-10-12", "2026-10-14", "2026-10-14", "2026-10-15", "2026-10-17"]
    tens = [(5.22, -6.0), (5.22, 0.0), (5.24, 2.0), (5.21, -3.0), (5.19, -2.0), (5.10, -9.0)]
    xlk = chain(200.0, [0.5] * 6)
    out = []
    for i, ((c, m), lab, (t, tc), (x, xc)) in enumerate(zip(closes, labels, tens, xlk)):
        if i in drop:
            continue
        out.append(snap(lab, 100 + i, facts(lab, c, m, t, tc, x, xc)))
    if 0 not in drop:  # the 9 Oct close archived a second time, on the 10th
        out.append(snap("2026-10-10", 99, facts("2026-10-10", *closes[0], 5.22, -6.0, *xlk[0])))
    return out, closes


def resolved(snaps):
    return weekly.resolve_sessions(snaps, SESSIONS)


def test_sessions_are_worked_out_from_the_prices():
    got = resolved(week_of_oct_16()[0])
    assert [d.isoformat() for d in got] == ["2026-10-09", "2026-10-12", "2026-10-13",
                                            "2026-10-14", "2026-10-15", "2026-10-16"]
    assert got[dt.date(2026, 10, 13)].label == dt.date(2026, 10, 14)
    assert got[dt.date(2026, 10, 16)].label == dt.date(2026, 10, 17)


def test_a_print_date_in_the_facts_wins():
    s = snap("2026-10-23", 1, facts("2026-10-23", 7700.0, 0.1, 5.0, 1.0))
    s.facts["us_equity"][0]["date"] = "2026-10-22"
    assert list(resolved([s])) == [dt.date(2026, 10, 22)]


def test_weekly_moves():
    snaps, closes = week_of_oct_16()
    f = weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16))
    spx = f["moves"]["us_equity"][0]
    assert spx["prior_week"] == closes[0][0] and spx["last"] == closes[-1][0]
    assert spx["week"] == round(100 * (closes[-1][0] / closes[0][0] - 1), 3)
    ten = f["moves"]["treasury_curve"][0]
    assert ten["week"] == -12.0 and ten["unit"] == "bp"
    assert f["week"]["missing"] == [] and f["week"]["prior_close_from"] == "archived"
    assert f["spx_path"][0]["date"] == "2026-10-12"


def test_missing_prior_week_close_is_given_back_by_mondays_change():
    snaps, closes = week_of_oct_16(drop=(0,))
    f = weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16))
    assert f["week"]["prior_close_from"] == "implied by the first session's change"
    assert f["moves"]["us_equity"][0]["prior_week"] == pytest.approx(closes[0][0], abs=0.01)


def test_missing_midweek_session_is_listed():
    snaps, _ = week_of_oct_16(drop=(3,))
    f = weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16))
    assert f["week"]["missing"] == ["2026-10-14"]


def _friday(snaps):
    return next(s for s in snaps if s.label == dt.date(2026, 10, 17))


def test_a_close_that_does_not_follow_from_the_day_before_is_left_out():
    snaps, _ = week_of_oct_16()
    # The provider changed the history: the close says +2% on a close the
    # 15 Oct note never printed.
    _friday(snaps).facts["sectors"][0].update(last=150.0, chg=2.0)
    f = weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16))
    assert f["week"]["left_out"] == ["Technology"] and f["moves"]["sectors"] == []


def test_a_late_print_the_day_before_is_not_a_break():
    snaps, _ = week_of_oct_16()
    next(s for s in snaps if s.label == dt.date(2026, 10, 15)) \
        .facts["series_not_yet_published"] = ["xlk"]
    _friday(snaps).facts["sectors"][0].update(last=150.0, chg=2.0)
    f = weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16))
    assert f["week"]["left_out"] == []


# ---------------------------------------------------------------- writing
def _facts():
    snaps, _ = week_of_oct_16()
    cal = weekly.site_calendar(dt.date(2026, 10, 16),
                               {"2026-10-12": PAGE, "2026-10-19": _next_week()})
    return weekly.week_facts(resolved(snaps), dt.date(2026, 10, 16), cal)


def test_review_without_the_model_passes_the_figure_check():
    f = _facts()
    note = weekly.write_without_model(f)
    assert note.audit_ok and audit(note.content, f) == []
    assert note.content["headline"].startswith("The S&P 500 lost")
    assert len(note.content["narrative"].split("\n\n")) == 3


def test_calendar_figures_are_admissible():
    f = _facts()
    assert audit({"macro": "Consumer prices rose 0.3% after 0.4%. JPMorgan earned "
                           "$4.81 and its shares fell 1.72% the next session."}, f) == []
    assert audit({"macro": "Consumer prices rose 0.5%."}, f) == ["0.5%"]


class _Client:
    def __init__(self, replies):
        self.replies, self.messages, self.seen = list(replies), self, []

    def create(self, **kw):
        self.seen.append(kw)
        txt = self.replies.pop(0)
        return types.SimpleNamespace(stop_reason="end_turn",
                                     content=[types.SimpleNamespace(type="text", text=txt)])


def _reply(fig):
    body = {"headline": "Staples led as technology gave back ground",
            "standfirst": f"The S&P 500 fell {fig} on the week.",
            "takeaways": "Technology lagged.\nStaples led.\nYields fell.\nCredit held.",
            "narrative": "One.\n\nTwo.\n\nThree.", "macro": "Prices rose 0.3%.",
            "week_ahead": "Payrolls next.", "linkedin": "A week of rotation."}
    return "\n".join(f"==={k}===\n{v}" for k, v in body.items())


def test_model_review_is_checked_and_sent_back_once(monkeypatch):
    f = _facts()
    spx = f["moves"]["us_equity"][0]["week"]
    c = _Client([_reply("3.33%"), _reply(f"{abs(spx):.2f}%")])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda api_key: c))
    note = weekly.write(f)
    assert note.audit_ok and note.attempts == 2
    assert "3.33%" in c.seen[1]["messages"][-1]["content"]
    assert c.seen[0]["system"].startswith("You write the weekly market review")
    assert "thinking" not in c.seen[0]


# --------------------------------------------------------------- end to end
def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chromium(), reason="no Chromium for Playwright")
def test_weekly_run_builds_the_note_and_carousel(tmp_path, monkeypatch):
    import weekly_run
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    src, cal = tmp_path / "in", tmp_path / "cal"
    src.mkdir()
    cal.mkdir()
    for s in week_of_oct_16()[0]:
        (src / f"facts_{s.label:%Y%m%d}_r{s.run}.json").write_text(json.dumps(s.facts))
    (cal / "2026-10-12.html").write_text(PAGE)
    (cal / "2026-10-19.html").write_text(_next_week())
    out = tmp_path / "out"
    assert weekly_run.main(["--week-ending", "2026-10-16", "--from", str(src),
                            "--calendar-dir", str(cal), "--no-mail", "--out", str(out)]) == 0
    for name in ("AndraMarkets_Weekly_20261016.pdf", "AndraMarkets_Weekly_LinkedIn_20261016.pdf",
                 "weekly_facts_20261016.json", "weekly_linkedin_caption_20261016.txt"):
        assert (out / name).stat().st_size > 0
    man = json.loads((out / "weekly_manifest_20261016.json").read_text())
    assert man["audit_ok"] and man["mode"] == "quantitative" and man["calendar"]
