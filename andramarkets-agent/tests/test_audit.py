from andra.narrative import audit

FACTS = {
    "us_equity": [{"key": "spx", "last": 7757.17, "chg": 0.578},
                  {"key": "ndx", "last": 29822.518, "chg": 1.127}],
    "apac": [{"key": "nky", "last": 64621.24, "chg": 0.852}],
    "commodities": [{"key": "gold", "last": 4321.2, "chg": 0.54}],
    "curve": {"2s10s": {"bp": 41.5, "delta": 2.0}},
}


def check(text):
    return audit({"desk_view": text}, FACTS)


def test_index_names_and_terms_are_not_figures():
    assert check("The S&P 500 rose 0.58% while the Nasdaq 100 added 1.13%. "
                 "The S&P MidCap 400 and the Russell 2000 lagged, the Nikkei 225 "
                 "rose 0.85%, the ASX 200 and CSI 300 were flat and the EURO "
                 "STOXX 50 firmed. The index holds above its 200-day average "
                 "and its 52-week high; 2s10s at 41.5bp, 10-year and 3m10y, "
                 "5y5y and the 7-10 year sector.") == []


def test_levels_without_thousands_separator_are_read_whole():
    # The old parser read 7757.17 as 775 and 7.17 and rejected both.
    assert check("The S&P 500 closed at 7757.17, gold at 4321.20, the Nikkei "
                 "at 64621.24 and the Nasdaq 100 at 29822.52.") == []
    assert check("The S&P 500 closed at 7,757.17.") == []


def test_wrong_figures_still_rejected():
    assert check("The S&P 500 closed at 8250.00.") == ["8250"]
    assert check("The S&P 500 fell -0.58%.") == ["-0.58"]
    assert check("Gold rose 3.75%.") == ["3.75"]


def test_ranges_and_dates_hold_no_negative_figures():
    assert check("On 2026-10-21 the 7-10 year bucket outperformed.") == []
