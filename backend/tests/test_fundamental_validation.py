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
