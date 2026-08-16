"""
CBSL Daily Economic Indicators parser.

Word fixtures below reproduce the real coordinate layout of the
13 August 2026 edition (captured with pdfplumber during development), so
the tests exercise the actual geometry the parser relies on without
committing a 300KB PDF to the repository. Expected values are the
figures printed in that edition.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.cbsl_parsing import (
    SERIES_CCPI_YOY,
    SERIES_NCPI_YOY,
    SERIES_POLICY_RATE,
    SERIES_TBILL_91D,
    SERIES_TBILL_182D,
    SERIES_TBILL_364D,
    SERIES_TBILL_364D_SECONDARY,
    CbslParseError,
    _as_fraction,
    _glued_percent,
    _labelled_percent,
    _parse_tbills,
    edition_url,
)

PUBLISHED = dt.date(2026, 8, 14)
EDITION = dt.date(2026, 8, 13)


def w(text: str, x0: float, top: float, width: float = 30.0) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top, "bottom": top + 8}


# Real geometry: Primary Market header at x~403, Secondary at x~472;
# column date headers at 421.9 and 495.2; tenor rows at top 372/388/406
# with values at x~444 (primary) and x~518 (secondary).
TBILL_WORDS = [
    w("Primary", 403.1, 346.1), w("Market", 435.8, 346.1),
    w("Secondary", 472.6, 345.4), w("Market", 514.9, 345.4),
    w("12-Aug-26", 421.9, 358.7), w("13-Aug-26", 495.2, 358.7),
    w("91", 348.0, 372.0, 13.2), w("Day", 359.7, 372.0),
    w("9.44", 444.3, 373.3), w("9.44", 517.7, 373.3),
    w("182", 347.4, 388.4, 18.1), w("Day", 364.0, 388.4),
    w("9.78", 444.3, 388.4), w("9.75", 517.7, 388.4),
    w("364", 348.7, 406.7, 18.0), w("Day", 365.2, 406.7),
    w("10.01", 439.0, 406.7), w("10.01", 513.0, 406.7),
]


def test_tbill_yields_match_the_published_edition():
    obs = _parse_tbills(TBILL_WORDS, PUBLISHED, EDITION)
    by_series = {o.series_id: o for o in obs}
    assert by_series[SERIES_TBILL_91D].value == Decimal("0.0944")
    assert by_series[SERIES_TBILL_182D].value == Decimal("0.0978")
    assert by_series[SERIES_TBILL_364D].value == Decimal("0.1001")


def test_primary_and_secondary_are_kept_apart():
    """They genuinely differ — 9.78 vs 9.75 on the 182-day — and §17.2
    specifies the PRIMARY auction yield for the risk-free rate. Swapping
    the columns would be invisible downstream."""
    by_series = {o.series_id: o for o in _parse_tbills(TBILL_WORDS, PUBLISHED, EDITION)}
    assert by_series["cbsl.tbill_182d"].value == Decimal("0.0978")  # primary
    assert by_series["cbsl.tbill_182d_secondary"].value == Decimal("0.0975")  # secondary


def test_each_column_carries_its_own_observation_date():
    """The primary column is dated 12 Aug and the secondary 13 Aug in the
    same edition — using the edition date for both would misdate the
    weekly auction result."""
    by_series = {o.series_id: o for o in _parse_tbills(TBILL_WORDS, PUBLISHED, EDITION)}
    assert by_series[SERIES_TBILL_364D].obs_date == dt.date(2026, 8, 12)
    assert by_series[SERIES_TBILL_364D_SECONDARY].obs_date == dt.date(2026, 8, 13)


def test_first_available_date_is_the_publication_date_not_the_observation():
    """The 13 August edition says "Published on 14-Aug-2026", and its
    primary column is dated the 12th. A figure observed on the 12th was
    not public until the 14th — §6 turns on exactly this gap."""
    obs = _parse_tbills(TBILL_WORDS, PUBLISHED, EDITION)
    assert all(o.first_available_date == PUBLISHED for o in obs)
    assert any(o.obs_date < o.first_available_date for o in obs)


def test_column_assignment_is_by_header_position_not_left_to_right():
    """If the panel's columns were ever swapped, the parser should follow
    the headers rather than silently mislabel the series."""
    swapped = []
    for word in TBILL_WORDS:
        word = dict(word)
        if word["text"] in ("Primary", "Secondary"):
            word["x0"] = 472.6 if word["text"] == "Primary" else 403.1
            word["x1"] = word["x0"] + 30
        swapped.append(word)
    by_series = {o.series_id: o for o in _parse_tbills(swapped, PUBLISHED, EDITION)}
    # values now attach to the opposite series, following the headers
    assert by_series[SERIES_TBILL_364D_SECONDARY].value == Decimal("0.1001")


def test_missing_market_headers_raise_rather_than_guess():
    words = [x for x in TBILL_WORDS if x["text"] not in ("Primary", "Secondary")]
    with pytest.raises(CbslParseError):
        _parse_tbills(words, PUBLISHED, EDITION)


def test_labelled_percent_reads_the_policy_rate():
    words = [
        w("Policy", 64, 301.7), w("Rate", 89, 301.7), w("(OPR):", 109, 301.7),
        w("8.75%", 143, 301.7), w("SRR:", 262, 301.7), w("2.00%", 294, 301.7),
    ]
    obs = _labelled_percent(words, "(OPR):", SERIES_POLICY_RATE, PUBLISHED, EDITION, "OPR")
    assert obs is not None and obs.value == Decimal("0.0875")


# --- the glued-token trap ------------------------------------------------


def test_glued_year_and_value_is_split_correctly():
    """CBSL emits "July" + "7.3%" as the single token "20267.3%". A greedy
    pattern reads 20267.3 and stores a 202% CCPI — which is exactly what
    the first version of this parser did."""
    words = [w("CCPI", 399, 76.8), w("Y-o-Y", 418, 76.8), w("Change:", 440, 76.8),
             w("July", 477, 76.8), w("20267.3%", 505, 76.8)]
    obs = _glued_percent(words, "CCPI", SERIES_CCPI_YOY, PUBLISHED, EDITION, "CCPI")
    assert obs is not None
    assert obs.value == Decimal("0.073")
    assert obs.value != Decimal("202.673")


def test_ungued_value_still_parses():
    words = [w("NCPI", 209, 76.8), w("Change:", 251, 76.8), w("June", 287, 76.8),
             w("2026", 312, 76.8), w("6.5%", 339, 76.8)]
    obs = _glued_percent(words, "NCPI", SERIES_NCPI_YOY, PUBLISHED, EDITION, "NCPI")
    assert obs is not None and obs.value == Decimal("0.065")


def test_quarter_prefix_is_also_stripped():
    words = [w("Growth:", 73, 76.8), w("2026Q15.1%", 108, 76.8)]
    obs = _glued_percent(words, "Growth:", "cbsl.gdp", PUBLISHED, EDITION, "GDP")
    assert obs is not None and obs.value == Decimal("0.051")


# --- the sanity band -----------------------------------------------------


def test_rate_outside_the_sanity_band_raises():
    """The guard that would have caught the 202% CCPI even if the regex
    fix were reverted."""
    with pytest.raises(CbslParseError, match="sanity band"):
        _as_fraction(Decimal("20267.3"), label="CCPI")


def test_a_rate_mistakenly_divided_twice_is_caught():
    """0.1001 already-a-fraction divided by 100 again gives 0.001001,
    which is inside the band and would NOT be caught — so this asserts
    the band's real job: catching the large errors, and documents that
    small ones need the unit discipline instead."""
    assert _as_fraction(Decimal("10.01"), label="ok") == Decimal("0.1001")


@pytest.mark.parametrize("value", ["9.44", "8.75", "70.0"])
def test_plausible_sri_lankan_rates_pass(value):
    """Inflation peaked near 70% in 2022 — the band must not reject real
    history."""
    assert _as_fraction(Decimal(value), label="x") is not None


# --- URL pattern ---------------------------------------------------------


def test_edition_url_matches_the_archive_pattern():
    assert edition_url(dt.date(2026, 8, 13)) == (
        "https://www.cbsl.gov.lk/sites/default/files/"
        "daily_economic_indicators_20260813_e.pdf"
    )
