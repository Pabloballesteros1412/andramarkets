import datetime as dt
import sys
import types

import pytest

import archive
from andra import fx, fx_render
from andra.analytics import fresh_extremes
from andra.narrative import audit
from andra.render import _env
from andra.universe import BLOCKS
from demo_fixture import demo_fx_note, synthetic_frame

DAY = dt.date(2026, 10, 22)


@pytest.fixture(scope="module")
def mf():
    return synthetic_frame(DAY)


@pytest.fixture(scope="module")
def facts(mf):
    return fx.fx_facts(mf)


def pair(facts, key):
    return next(p for p in facts["pairs"] if p["key"] == key)


# ------------------------------------------------------------- the facts
def test_every_pair_is_covered_with_its_three_moves(facts):
    keys = [p["key"] for p in facts["pairs"]]
    assert keys == [k for k, _, _ in fx.PAIRS] and len(keys) == 15
    for p in facts["pairs"]:
        assert None not in (p["d1"], p["w1"], p["m1"]), p["key"]
    assert {p["group"] for p in facts["pairs"]} == {"dollar", "major", "em"}


def test_currency_move_is_inverted_for_usd_base_pairs(facts):
    jpy, eur = pair(facts, "usdjpy"), pair(facts, "eurusd")
    assert eur["ccy_vs_usd"]["d1"] == eur["d1"]
    # USD/JPY up x% is the yen down by 1 - 1/(1 + x).
    expect = 100 * (1 / (1 + jpy["d1"] / 100) - 1)
    assert jpy["ccy_vs_usd"]["d1"] == pytest.approx(expect, abs=2e-3)
    assert (jpy["ccy_vs_usd"]["d1"] > 0) == (jpy["d1"] < 0)
    assert pair(facts, "dxy")["ccy_vs_usd"] is None


def test_policy_differential_is_to_the_top_of_the_fed_range(facts):
    fed = facts["us_rates"]["fed"]
    assert (fed["rate"], fed["rate_lower"], fed["source"]) == (4.0, 3.75, "FRED")
    # The demo series cut 25bp 40 sessions ago; FRED decisions are read from it.
    assert fed["last_change_bp"] == -25
    gbp, eur = pair(facts, "gbpusd")["policy"], pair(facts, "eurusd")["policy"]
    assert gbp["vs_fed_bp"] == -25 and eur["source"] == "FRED" and eur["vs_fed_bp"] == -200


def test_every_rate_carries_its_source_series_and_date(facts):
    jpy = pair(facts, "usdjpy")["policy"]
    assert jpy["source"].startswith("BIS") and jpy["series"] == "JP"
    assert jpy["as_of"] == DAY.isoformat() and jpy["last_change_bp"] == -25
    assert pair(facts, "eurusd")["policy"]["series"] == "ECBDFR"
    assert facts["banks_without_rate"] == []


def test_a_bank_with_no_series_is_reported_not_guessed(mf):
    import copy
    thin = copy.copy(mf)
    thin.px = mf.px.drop(columns=["pol_br"])
    thin.snap = mf.snap.drop(index=["pol_br"])
    f = fx.fx_facts(thin)
    assert f["banks_without_rate"] == ["BCB"] and pair(f, "usdbrl")["policy"] is None


def test_bis_rates_are_parsed_into_frame_columns(monkeypatch):
    from andra import data
    csv = (b"FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
           b"D,JP,2026-10-15,1.0\nD,JP,2026-10-16,1.25\nD,TR,2026-10-16,37.0\n")

    class Resp:
        def __init__(self, url):
            assert "WS_CBPOL/D.JP+TR/" in url and "detail=dataonly" in url

        def read(self):
            return csv

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Resp(url))
    ins = [i for i in BLOCKS["policy"] if i.ticker in ("JP", "TR")]
    got = data._bis(ins, dt.date(2026, 10, 1), DAY)
    assert list(got.columns) == ["pol_jp", "pol_tr"]
    assert got["pol_jp"].tolist() == [1.0, 1.25]


def test_fx_only_series_stay_out_of_the_close_note_counts():
    from andra.universe import fx_only_keys
    assert {"pol_jp", "fedupper", "nzdusd"} <= fx_only_keys()
    assert not fx_only_keys() & {i.key for i in BLOCKS["fx"]}


def test_nearest_level_is_never_the_close_itself():
    lv = {"high_1m": 18.67871, "low_1m": 17.7387, "ma50": 18.1, "ma200": None,
          "high_52w": 19.5, "low_52w": 16.9}
    n = fx._nearest(18.678701, lv, 4)
    assert n["at"] == ["high_1m"]
    assert n["above"]["level"] == "high_52w" and n["below"]["level"] == "ma50"


def test_fx_pairs_stay_out_of_the_close_note(mf):
    assert not {i.key for i in BLOCKS["fx_more"]} & {i.key for i in BLOCKS["fx"]}
    names = {i.name for b in ("fx_more", "policy") for i in BLOCKS[b]}
    ext = fresh_extremes(mf)
    assert not names & set(ext["highs"] + ext["lows"])


# ---------------------------------------------------------------- checks
def test_demo_note_passes_every_check(facts):
    note = demo_fx_note(facts)
    assert audit(note.content, facts) == []
    assert fx.WORDS_MIN <= fx.word_count(note.content) <= fx.WORDS_MAX
    assert fx.advice_flags(note.content) == []


def test_trade_language_is_flagged_but_description_is_not():
    assert fx.advice_flags({"a": "We expect EUR/USD to rise. Buy the dip."}) == ["buy", "we expect"]
    assert fx.advice_flags({"a": "Traders should hedge into the meeting."}) == ["should hedge"]
    assert fx.advice_flags({"a": "The sell-off hit the short end and long-dated "
                                 "yields; sellers were busy."}) == []


def test_figures_only_note_passes_the_figure_check(facts):
    note = fx.write_without_model(facts)
    assert note.audit_ok and audit(note.content, facts) == []
    assert note.content["levels"] and note.content["drivers"]


# ---------------------------------------------------------------- writer
def reply(text, stop="end_turn"):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)],
                                 stop_reason=stop)


def tagged(content):
    return fx._as_tagged(content)


def run(monkeypatch, facts, replies):
    replies = list(replies)
    sent = []

    class Client:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            sent.append(kw)
            return replies.pop(0)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda api_key: Client()))
    return fx.write(facts), sent


def test_short_or_advisory_draft_goes_back_with_the_reason(monkeypatch, facts):
    good = demo_fx_note(facts).content
    short = {**good, **{k: good[k].split("\n\n")[0][:80] for k in ("dollar", "majors", "em", "drivers")}}
    advice = {**good, "drivers": good["drivers"] + " We prefer to buy the euro here."}
    note, sent = run(monkeypatch, facts, [reply(tagged(short)), reply(tagged(advice)),
                                          reply(tagged(good))])
    assert note.attempts == 3 and note.audit_ok
    asks = [m["content"] for m in sent[-1]["messages"] if m["role"] == "user"][1:]
    assert "words" in asks[0] and "trade language" in asks[1]
    # Plain call (CLAUDE.md): no thinking parameter, no temperature.
    assert not {"thinking", "temperature"} & set(sent[0])


def test_invented_figure_fails_the_note(monkeypatch, facts):
    bad = {**demo_fx_note(facts).content, "dollar": "The index fell 3.21% on the day."}
    note, _ = run(monkeypatch, facts, [reply(tagged(bad))] * 3)
    assert not note.audit_ok and note.unsupported == ["3.21%"]


# ------------------------------------------------------- site and archive
def test_site_file_carries_note_sections_and_facts(facts):
    note = demo_fx_note(facts)
    site = fx.to_site(facts, note, "demo", "0041", "AndraMarkets_FX_20261022.pdf")
    assert site["schema"] == "andra.fx/1" and site["date"] == "2026-10-22"
    assert [s["id"] for s in site["sections"]] == [s for s, _ in fx.SECTIONS]
    assert all(s["paragraphs"] for s in site["sections"])
    assert site["facts"] is facts and site["audit"]["ok"] and site["word_count"] >= 800


def test_archive_keeps_the_fx_files():
    for name in ("AndraMarkets_FX_20261022.pdf", "fx_20261022.json"):
        assert archive.KEEP.fullmatch(name)
    assert not archive.KEEP.fullmatch("fx_20261022.txt")


def test_template_renders_every_section(facts):
    note = demo_fx_note(facts)
    ctx = fx_render.build_context(facts, note, {}, edition="0041")
    html = _env().get_template("fx.html.j2").render(**ctx)
    for title in ("Key takeaways", "The dollar", "G10 majors", "Emerging markets",
                  "Rate differentials and central banks", "Levels that matter",
                  "Methodology", "Disclaimer", "BIS central bank policy rates"):
        assert title in html
    assert html.count("<tr>") >= 15 + 14 + 15


def test_figures_only_note_skips_a_move_it_does_not_have(facts):
    # A replay rebuilt from one archived day has no monthly move.
    thin = {**facts, "pairs": [{**p, "m1": None} if p["key"] == "dxy" else p
                               for p in facts["pairs"]]}
    note = fx.write_without_model(thin)
    assert note.audit_ok and "on the month" not in note.content["standfirst"]
