"""Tests for the §24 canonical financial-data layer (STEP 2).

Figures are from J.F. Packaging PLC's real FY2025/26 statements, the same
filing `financial_statement_parsing`'s own cash-flow labels were verified
against, so the arithmetic here is checkable against a real document
rather than invented numbers.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.financial_metrics import (
    CURRENCY,
    DEFINITIONS,
    NOT_YET_COMPUTABLE,
    OPTIONAL_ASSUMPTIONS,
    compute_all,
    compute_growth,
    compute_metric,
    DEFINITIONS_BY_KEY,
)
from app.domain.ratios import LineItem
from app.models.enums import ProvenanceTier


def items(**kwargs: object) -> dict[str, LineItem]:
    """Line items at REPORTED provenance unless a (value, tier) pair."""
    out: dict[str, LineItem] = {}
    for key, raw in kwargs.items():
        if isinstance(raw, tuple):
            value, tier = raw
        else:
            value, tier = raw, ProvenanceTier.REPORTED
        out[key] = LineItem(value=Decimal(str(value)), provenance=tier)
    return out


class TestIncomeStatement:
    def test_ebit_is_operating_profit(self):
        result = compute_metric(DEFINITIONS_BY_KEY["ebit"], items(operating_profit=1_000))
        assert result.value == Decimal(1_000)
        assert result.unit == CURRENCY

    def test_ebitda_adds_back_combined_depreciation_and_amortisation(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"],
            items(operating_profit=1_000, depreciation_and_amortisation=250),
        )
        assert result.value == Decimal(1_250)

    def test_ebitda_falls_back_to_separate_depreciation_and_amortisation_lines(self):
        """The combined line exists for 10 tickers; depreciation_expense
        for 132. Falling back is what makes EBITDA computable at all."""
        result = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"],
            items(operating_profit=1_000, depreciation_expense=200, amortisation_expense=50),
        )
        assert result.value == Decimal(1_250)

    def test_ebitda_treats_depreciation_sign_as_a_magnitude(self):
        """CSE filings print depreciation negative in the income
        statement and positive as a cash-flow add-back. Both must give
        the same EBITDA."""
        negative = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"], items(operating_profit=1_000, depreciation_expense=-250)
        )
        positive = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"], items(operating_profit=1_000, depreciation_expense=250)
        )
        assert negative.value == positive.value == Decimal(1_250)

    def test_absent_amortisation_is_disclosed_as_an_assumption(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"], items(operating_profit=1_000, depreciation_expense=250)
        )
        assert result.value == Decimal(1_250)
        assert any("amortisation" in a for a in result.assumptions)

    def test_combined_line_present_means_component_absence_is_not_an_assumption(self):
        """depreciation_expense/amortisation_expense are ALTERNATIVES to
        the combined line, so their absence says nothing when it is
        present — reporting it would be noise on every well-formed
        filing."""
        result = compute_metric(
            DEFINITIONS_BY_KEY["ebitda"],
            items(operating_profit=1_000, depreciation_and_amortisation=250),
        )
        assert result.assumptions == ()

    def test_ebit_margin_needs_positive_revenue(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["ebit_margin"], items(operating_profit=100, revenue=0)
        )
        assert result.value is None
        assert result.note is not None

    def test_tax_and_interest_are_reported_as_magnitudes(self):
        tax = compute_metric(DEFINITIONS_BY_KEY["tax"], items(income_tax_expense=-350))
        interest = compute_metric(DEFINITIONS_BY_KEY["interest_expense"], items(interest_expense=-90))
        assert tax.value == Decimal(350)
        assert interest.value == Decimal(90)


class TestBalanceSheet:
    def test_debt_includes_the_overdraft(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["debt"],
            items(total_interest_bearing_debt=1_000, bank_overdraft=250),
        )
        assert result.value == Decimal(1_250)

    def test_absent_overdraft_is_treated_as_zero_and_disclosed(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["debt"], items(total_interest_bearing_debt=1_000)
        )
        assert result.value == Decimal(1_000)
        assert result.assumptions == (OPTIONAL_ASSUMPTIONS["bank_overdraft"],)

    def test_net_debt_subtracts_cash(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["net_debt"],
            items(total_interest_bearing_debt=1_000, bank_overdraft=200, cash_and_cash_equivalents=300),
        )
        assert result.value == Decimal(900)

    def test_net_debt_is_negative_for_a_net_cash_company(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["net_debt"],
            items(total_interest_bearing_debt=100, cash_and_cash_equivalents=500),
        )
        assert result.value == Decimal(-400)

    def test_net_debt_requires_cash_rather_than_assuming_zero(self):
        """Assuming zero cash would overstate net debt for every company
        — §23's fabricated number, in the pessimistic direction."""
        result = compute_metric(
            DEFINITIONS_BY_KEY["net_debt"], items(total_interest_bearing_debt=1_000)
        )
        assert result.value is None
        assert "cash_and_cash_equivalents" in result.missing_inputs

    def test_tangible_equity_removes_intangibles(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["tangible_equity"], items(total_equity=5_000, intangible_assets=800)
        )
        assert result.value == Decimal(4_200)


class TestCashFlow:
    def test_fcf_is_cfo_less_capex(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["fcf"],
            items(cash_flow_from_operations=900, capital_expenditure=-400),
        )
        assert result.value == Decimal(500)

    def test_cfo_never_substitutes_the_pre_tax_subtotal(self):
        """`cash_generated_from_operations` is the pre-tax, pre-interest
        subtotal and is extracted for far more companies. Accepting it as
        CFO would overstate every cash-flow metric."""
        result = compute_metric(
            DEFINITIONS_BY_KEY["cfo"], items(cash_generated_from_operations=900)
        )
        assert result.value is None
        assert result.missing_inputs == ("cash_flow_from_operations",)

    def test_fcff_uses_the_effective_tax_rate(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["fcff"],
            items(operating_profit=1_000, profit_before_tax=800, income_tax_expense=-200,
                  depreciation_expense=150, capital_expenditure=-300,
                  change_in_net_working_capital=50),
        )
        # tax rate 200/800 = 25%; 1000*0.75 + 150 - 300 - 50 = 550
        assert result.value == Decimal(550)

    def test_fcff_is_withheld_in_a_pre_tax_loss_year(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["fcff"],
            items(operating_profit=1_000, profit_before_tax=-800, income_tax_expense=0,
                  depreciation_expense=150, capital_expenditure=-300,
                  change_in_net_working_capital=50),
        )
        assert result.value is None
        assert result.note is not None


class TestProvenanceAndDiscipline:
    def test_metric_inherits_the_weakest_provenance_of_its_inputs(self):
        result = compute_metric(
            DEFINITIONS_BY_KEY["net_debt"],
            items(
                total_interest_bearing_debt=(1_000, ProvenanceTier.REPORTED),
                cash_and_cash_equivalents=(300, ProvenanceTier.ESTIMATED),
            ),
        )
        assert result.provenance == ProvenanceTier.ESTIMATED

    def test_missing_inputs_are_named_not_defaulted(self):
        for result in compute_all({}):
            assert result.value is None
            assert result.missing_inputs, f"{result.key} returned None without naming an input"

    def test_every_optional_input_has_a_stated_assumption(self):
        """A definition that quietly zero-fills an optional input without
        an OPTIONAL_ASSUMPTIONS entry would hide a real assumption."""
        alternatives = {"depreciation_and_amortisation"}
        for definition in DEFINITIONS:
            for key in definition.optional:
                if key in alternatives:
                    continue
                assert key in OPTIONAL_ASSUMPTIONS, f"{definition.key} optional {key} undisclosed"

    def test_uncomputable_metrics_are_declared_with_reasons(self):
        keys = {k for k, _label, _reason in NOT_YET_COMPUTABLE}
        assert {"eps", "fcfe"} <= keys
        for _key, _label, reason in NOT_YET_COMPUTABLE:
            assert len(reason) > 40

    def test_compute_all_returns_one_result_per_definition(self):
        assert len(compute_all({})) == len(DEFINITIONS)


class TestGrowth:
    def test_revenue_growth(self):
        results = {r.key: r for r in compute_growth(items(revenue=1_100), items(revenue=1_000))}
        assert results["revenue_growth"].value == Decimal("0.1")

    def test_growth_from_a_loss_base_is_withheld(self):
        """-10 -> +5 arithmetically reads -150%, the opposite of what
        happened. §26's turnaround detection is the right home for it."""
        results = {r.key: r for r in compute_growth(items(net_income=5), items(net_income=-10))}
        assert results["net_income_growth"].value is None
        assert "non-positive base" in (results["net_income_growth"].note or "")

    def test_growth_names_missing_inputs(self):
        results = {r.key: r for r in compute_growth(items(revenue=1_100), {})}
        assert results["revenue_growth"].value is None
        assert "revenue" in results["revenue_growth"].missing_inputs


@pytest.mark.parametrize("definition", DEFINITIONS, ids=lambda d: d.key)
def test_definition_is_well_formed(definition):
    assert definition.required, f"{definition.key} has no required inputs"
    assert definition.formula
    assert definition.label
