import json
import os
from pathlib import Path

import pytest

import replay
import run_daily
from andra.analytics import fact_pack

ROOT = Path(__file__).resolve().parent.parent

FACTS = {
    "date": "2026-10-21",
    "us_equity": [{"key": "spx", "name": "S&P 500", "last": 7757.17, "chg": 0.578,
                   "ytd": 13.104, "date": "2026-10-21", "time": None}],
    "treasury_curve": [{"key": "ust10y", "name": "10 year", "last": 4.12, "chg": 3.0,
                        "ytd": -45.0, "date": "2026-10-20", "time": None}],
    "fx": [{"key": "eurusd", "name": "EUR/USD", "last": 1.1642, "chg": -0.21,
            "ytd": 4.5}],
    "movers": {"leaders": [{"key": "nvda", "name": "NVDA", "last": 221.97,
                            "chg": 2.54, "ytd": 17.54}], "laggards": []},
    "risk_barometer": {"score": 0.38, "label": "Constructive", "n": 12},
    "breadth": {"advancers": 14, "decliners": 10, "unchanged": 2,
                "ratio": 1.4, "dispersion": 1.85},
    "extremes": {"highs": ["AAPL"], "lows": []},
    "series_without_print": ["vstoxx"], "series_not_yet_published": [],
}


def _row(facts, block, key):
    return next(r for r in facts[block] if r["key"] == key)


def test_archived_frame_gives_back_the_archived_figures():
    mf = replay.archived_frame(FACTS)
    facts = fact_pack(mf)
    for block, key in (("us_equity", "spx"), ("treasury_curve", "ust10y"), ("fx", "eurusd")):
        old, new = _row(FACTS, block, key), _row(facts, block, key)
        assert new["last"] == pytest.approx(old["last"], abs=1e-3)
        assert new["chg"] == pytest.approx(old["chg"], abs=1e-3)
        assert new["ytd"] == pytest.approx(old["ytd"], abs=1e-3)
    # Each print keeps its own date: the curve printed the day before.
    assert _row(facts, "treasury_curve", "ust10y")["off_session"] is True
    assert _row(facts, "us_equity", "spx")["off_session"] is False
    # Rows with no print date take the session's.
    assert _row(facts, "fx", "eurusd")["date"] == "2026-10-21"
    assert mf.missing == ["vstoxx"]


def test_history_sections_are_carried_from_the_archive():
    facts = fact_pack(replay.archived_frame(FACTS))
    assert replay.carry_over(facts, FACTS) == list(replay.CARRIED)
    assert facts["risk_barometer"]["score"] == 0.38
    assert facts["breadth"]["advancers"] == 14


def test_compare_lists_only_moved_figures():
    new = json.loads(json.dumps(FACTS))
    assert replay.compare(FACTS, new) == []
    new["us_equity"][0]["last"] = 7800.0
    assert [d[0] for d in replay.compare(FACTS, new)] == ["us_equity[spx].last"]


def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_browser = pytest.mark.skipif(not _chromium(), reason="no Chromium for Playwright")


def _state():
    return {f: (ROOT / f).read_text() if (ROOT / f).exists() else None
            for f in (".edition", ".last_published")}


def _replay_into(src: Path, out: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    before = _state()
    assert replay.main(["--from", str(src), "--out", str(out)]) == 0
    # A replay never moves the edition counter or the publish marker.
    assert _state() == before
    stamp = json.loads(next(src.glob("facts_*.json")).read_text())["date"].replace("-", "")
    for name in (f"AndraMarkets_Close_{stamp}.pdf", f"AndraMarkets_LinkedIn_{stamp}.pdf",
                 f"facts_{stamp}.json", f"note_{stamp}.json", f"manifest_{stamp}.json",
                 f"linkedin_caption_{stamp}.txt", f"series_{stamp}.json"):
        assert (out / name).stat().st_size > 0, name
    assert len(list((out / f"tiktok_{stamp}").glob("*.png"))) >= 4
    return stamp, json.loads((out / f"manifest_{stamp}.json").read_text())


@needs_browser
def test_replay_end_to_end_on_a_demo_edition(tmp_path, monkeypatch):
    """Always runnable: a demo edition's facts and note, saved as an archived
    run would be, go through the whole replay."""
    from demo_fixture import demo_note, synthetic_frame
    import datetime as dt
    src = tmp_path / "input"
    src.mkdir()
    facts = fact_pack(synthetic_frame(dt.date(2026, 10, 21)))
    (src / "facts_20261021_r1.json").write_text(json.dumps(facts, default=str))
    (src / "note_20261021_r1.json").write_text(json.dumps(demo_note().content))
    stamp, man = _replay_into(src, tmp_path / "out", monkeypatch)
    assert man["demo"] is True and man["mode"] == "archived"
    assert man["carried_from_archive"] == list(replay.CARRIED)


@needs_browser
@pytest.mark.skipif(not os.environ.get("ANDRA_REPLAY_DAY"),
                    reason="set ANDRA_REPLAY_DAY to an archived run's folder "
                           "(the Tests workflow fetches one)")
def test_replay_end_to_end_on_an_archived_day(tmp_path, monkeypatch):
    src = Path(os.environ["ANDRA_REPLAY_DAY"])
    stamp, man = _replay_into(src, tmp_path / "out", monkeypatch)
    assert man["demo"] is True
    old = replay.load_folder(src)
    new = json.loads((tmp_path / "out" / f"facts_{stamp}.json").read_text())
    # Rebuilt from the archive, the fact pack gives back every archived figure.
    assert replay.compare(old["facts"], new) == []
    # The archived note text is what went through, unchanged.
    note = json.loads((tmp_path / "out" / f"note_{stamp}.json").read_text())
    if old.get("note"):
        assert note["headline"] == old["note"]["headline"]
