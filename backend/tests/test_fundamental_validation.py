"""The data-integrity gate's check battery — `app.domain.fundamental_
validation.validate_filing`. Pure, no DB.
"""
from __future__ import annotations

from decimal import Decimal

from app.domain.fundamental_validation import validate_filing


def test_a_balancing_filing_passes_every_line():
    values = {
        "total_assets": Decimal("50_000_000"),
        "total_liabilities": Decimal("32_000_000"),
        "total_equity": Decimal("18_000_000"),
        "revenue": Decimal("10_000_000"),
        "cost_of_sales": Decimal("-6_000_000"),
        "gross_profit": Decimal("4_000_000"),
    }
    result = validate_filing(values)
    assert set(result) == set(values)
    assert all(v.passed for v in result.values())


def test_a_broken_balance_sheet_fails_every_line_in_that_identity():
    values = {
        "total_assets": Decimal("48_000_000"),  # should be 50,000,000
        "total_liabilities": Decimal("32_000_000"),
        "total_equity": Decimal("18_000_000"),
    }
    result = validate_filing(values)
    assert not result["total_assets"].passed
    assert not result["total_liabilities"].passed
    assert not result["total_equity"].passed
    assert "assets = equity + liabilities" in result["total_assets"].failures[0].check


def test_an_unrelated_line_on_the_same_filing_still_passes():
    values = {
        "total_assets": Decimal("48_000_000"),  # balance sheet is broken
        "total_liabilities": Decimal("32_000_000"),
        "total_equity": Decimal("18_000_000"),
        "revenue": Decimal("10_000_000"),
        "cost_of_sales": Decimal("-6_000_000"),
        "gross_profit": Decimal("4_000_000"),  # income statement is fine
    }
    result = validate_filing(values)
    assert not result["total_assets"].passed
    assert result["revenue"].passed
    assert result["gross_profit"].passed


def test_a_magnitude_implausible_value_fails():
    # net_income is a millionth-scale corrupted read next to real
    # balance-sheet figures — the split-leading-digit failure mode.
    values = {
        "total_assets": Decimal("50_000_000"),
        "revenue": Decimal("30_000_000"),
        "net_income": Decimal("1"),
    }
    result = validate_filing(values)
    assert not result["net_income"].passed
    assert "implausibly small" in result["net_income"].failures[0].check
    assert result["total_assets"].passed
    assert result["revenue"].passed


def test_rounding_within_a_thousand_rupees_is_not_a_failure():
    # Real filings show a Rs 1-2 discrepancy from publication rounding —
    # the gate uses the Rs 1,000 tolerance, not exact equality, so this
    # passes. A genuine corruption is off by tens of millions.
    values = {
        "total_assets": Decimal("50_000_400"),
        "total_liabilities": Decimal("32_000_000"),
        "total_equity": Decimal("18_000_000"),
    }
    result = validate_filing(values)
    assert result["total_assets"].passed
    assert result["total_equity"].passed


def test_a_material_balance_sheet_gap_still_fails():
    values = {
        "total_assets": Decimal("48_000_000"),  # off by 2,000,000
        "total_liabilities": Decimal("32_000_000"),
        "total_equity": Decimal("18_000_000"),
    }
    result = validate_filing(values)
    assert not result["total_assets"].passed


# --- Phase 2: year-over-year trend check (spec §5) ---------------------
from app.domain.fundamental_validation import check_series_trend  # noqa: E402


def _hist(*values):
    return [(f"FY{2020 + i}", Decimal(str(v))) for i, v in enumerate(values)]


def test_a_steady_series_passes():
    out = check_series_trend(_hist(8_200, 8_700, 9_100, 9_600, 10_100, 10_400))
    assert out == {}


def test_a_ten_x_jump_is_flagged_on_the_jump_year():
    out = check_series_trend(_hist(9_600, 10_100, 101_000))
    assert set(out) == {"FY2022"}
    assert "jump" in out["FY2022"][0].check


def test_gradual_multi_year_growth_is_not_flagged():
    # 10x over five years, but never >10x in one step.
    out = check_series_trend(_hist(1_000, 1_800, 3_200, 5_600, 10_000))
    assert out == {}


def test_a_sign_flip_between_material_years_is_flagged():
    out = check_series_trend(_hist(5_000, 5_200, -5_100))
    assert "FY2022" in out
    assert "sign flip" in out["FY2022"][0].check


def test_fewer_than_three_periods_is_not_checked():
    assert check_series_trend(_hist(1_000, 50_000)) == {}


def test_a_swing_off_a_near_zero_base_is_not_flagged_on_ratio_alone():
    # Break-even year then a normal year — ratio is huge but the small
    # value is immaterial vs the series peak.
    out = check_series_trend(_hist(10_000, 10, 11_000, 12_000))
    assert out == {}
