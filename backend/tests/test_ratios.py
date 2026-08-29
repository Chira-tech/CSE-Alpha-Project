"""
Ratio engine, tested against J.F. Packaging PLC's real FY2025/26 figures
(the annual report downloaded and parsed during Phase 1 — see
app/ingestion/README_ENDPOINTS.md). Expected values are computed by hand
from those statements so a wrong formula fails rather than a wrong
formula agreeing with itself.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.ratios import (
    DEFINITIONS_BY_KEY,
    NOT_YET_COMPUTABLE,
    LineItem,
    compute_all,
    compute_ratio,
)
from app.models.enums import ProvenanceTier

R = ProvenanceTier.REPORTED
A = ProvenanceTier.AI_ASSISTED

# Real Group-column figures, LKR '000, from the filed statements.
JFP = {
    "revenue": Decimal("4504801"),
    "cost_of_sales": Decimal("-3335742"),
    "gross_profit": Decimal("1169059"),
    "operating_profit": Decimal("524378"),
    "profit_before_tax": Decimal("320460"),
    "income_tax_expense": Decimal("-130552"),
    "net_income": Decimal("189908"),
    "total_assets": Decimal("3807110"),
    "total_current_assets": Decimal("2181825"),
    "total_non_current_assets": Decimal("1625285"),
    "total_equity": Decimal("1643031"),
    "total_liabilities": Decimal("2164079"),
    "total_current_liabilities": Decimal("1728581"),
    # Statement of cash flow, same FY2025/26 filing — added once
    # financial_statement_parsing.py started extracting this page
    # (verified against the real PDF, not re-typed by hand from a
    # different source than the figures above).
    "cash_flow_from_operations": Decimal("174382"),
    "depreciation_and_amortisation": Decimal("111039"),
    "net_cash_from_investing_activities": Decimal("-244852"),
    "net_cash_from_financing_activities": Decimal("12302"),
    "net_increase_in_cash": Decimal("-58168"),
}


def items(source=JFP, provenance=R) -> dict[str, LineItem]:
    return {k: LineItem(value=v, provenance=provenance) for k, v in source.items()}


def _value(key: str, line_items) -> Decimal | None:
    return compute_ratio(DEFINITIONS_BY_KEY[key], line_items).value


@pytest.mark.parametrize(
    ("key", "expected", "places"),
    [
        # 189,908 / 1,643,031 = 0.115581...
        ("return_on_equity", Decimal("0.1156"), 4),
        # 189,908 / 3,807,110 = 0.049882...
        ("return_on_assets", Decimal("0.0499"), 4),
        # 1,169,059 / 4,504,801 = 0.259512...
        ("gross_margin", Decimal("0.2595"), 4),
        # 524,378 / 4,504,801 = 0.116404...
        ("operating_margin", Decimal("0.1164"), 4),
        # 189,908 / 4,504,801 = 0.042157...
        ("net_margin", Decimal("0.0422"), 4),
        # 1,169,059 / 3,807,110 = 0.307074...
        ("gross_profitability", Decimal("0.3071"), 4),
        # 2,181,825 / 1,728,581 = 1.262208...
        ("current_ratio", Decimal("1.2622"), 4),
        # 2,164,079 / 1,643,031 = 1.317132...
        ("liabilities_to_equity", Decimal("1.3171"), 4),
        # 1,643,031 / 3,807,110 = 0.431553...
        ("equity_ratio", Decimal("0.4316"), 4),
        # 130,552 / 320,460 = 0.407390...
        ("effective_tax_rate", Decimal("0.4074"), 4),
        # 174,382 / 189,908 = 0.918245...
        ("cash_conversion", Decimal("0.9182"), 4),
        # 174,382 / 4,504,801 = 0.038710...
        ("operating_cash_flow_margin", Decimal("0.0387"), 4),
        # (189,908 - 174,382) / 3,807,110 = 0.004078...
        ("sloan_accrual_ratio", Decimal("0.0041"), 4),
    ],
)
def test_matches_hand_computed_values_from_a_real_filing(key, expected, places):
    got = _value(key, items())
    assert got is not None
    assert round(got, places) == expected


def test_accounting_identity_holds_on_the_source_figures():
    """Sanity check on the fixture itself: if assets != equity +
    liabilities the test data is wrong and every ratio above is
    meaningless."""
    assert JFP["total_assets"] == JFP["total_equity"] + JFP["total_liabilities"]
    assert JFP["total_assets"] == JFP["total_current_assets"] + JFP["total_non_current_assets"]
    assert JFP["revenue"] + JFP["cost_of_sales"] == JFP["gross_profit"]


def test_effective_tax_rate_is_positive_despite_tax_being_stored_negative():
    """Tax expense reduces profit and is stored negative; a rate of
    -40% would be nonsense to display and wrong to feed §18.2's
    'converging to statutory by Y5' logic."""
    rate = _value("effective_tax_rate", items())
    assert rate is not None and rate > 0


# --- the guards ---------------------------------------------------------


def test_negative_equity_returns_not_meaningful_rather_than_a_flattering_roe():
    """A loss-making company with negative equity produces a POSITIVE ROE
    arithmetically. A screener sorting on it would rank the most
    distressed company first — so the honest answer is None."""
    broken = dict(JFP, total_equity=Decimal("-100000"), net_income=Decimal("-50000"))
    result = compute_ratio(DEFINITIONS_BY_KEY["return_on_equity"], items(broken))
    assert result.value is None
    assert result.note is not None and "negative" in result.note.lower()
    # prove the trap is real: naive arithmetic would have said +50%
    assert (broken["net_income"] / broken["total_equity"]) > 0


def test_zero_denominator_returns_none_not_an_exception():
    zeroed = dict(JFP, revenue=Decimal("0"))
    result = compute_ratio(DEFINITIONS_BY_KEY["gross_margin"], items(zeroed))
    assert result.value is None
    assert result.note is not None


def test_pre_tax_loss_makes_the_effective_tax_rate_not_meaningful():
    loss = dict(JFP, profit_before_tax=Decimal("-50000"))
    result = compute_ratio(DEFINITIONS_BY_KEY["effective_tax_rate"], items(loss))
    assert result.value is None


# --- missing inputs -----------------------------------------------------


def test_missing_input_names_exactly_what_is_missing():
    partial = {k: v for k, v in items().items() if k != "total_equity"}
    result = compute_ratio(DEFINITIONS_BY_KEY["return_on_equity"], partial)
    assert result.value is None
    assert result.missing_inputs == ("total_equity",)
    assert not result.computable


def test_compute_all_returns_every_definition_even_when_uncomputable():
    empty: dict[str, LineItem] = {}
    results = compute_all(empty)
    assert len(results) == len(DEFINITIONS_BY_KEY)
    assert all(not r.computable for r in results)
    assert all(r.missing_inputs for r in results)


# --- provenance ---------------------------------------------------------


def test_ratio_inherits_the_weakest_provenance_of_its_inputs():
    """§8: 'A composite score inherits the weakest provenance among its
    material inputs.' One unconfirmed AI-extracted input must taint the
    whole ratio."""
    mixed = items()
    mixed["total_equity"] = LineItem(value=JFP["total_equity"], provenance=A)
    result = compute_ratio(DEFINITIONS_BY_KEY["return_on_equity"], mixed)
    assert result.provenance is ProvenanceTier.AI_ASSISTED


def test_all_reported_inputs_give_a_reported_ratio():
    result = compute_ratio(DEFINITIONS_BY_KEY["return_on_equity"], items())
    assert result.provenance is ProvenanceTier.REPORTED


def test_uncomputable_ratio_has_no_provenance():
    result = compute_ratio(DEFINITIONS_BY_KEY["return_on_equity"], {})
    assert result.provenance is None


# --- honesty about what is not implemented ------------------------------


def test_leverage_ratio_is_not_called_debt_to_equity():
    """Total liabilities includes payables and deferred tax. Naming this
    debt/equity would invite comparison against a conventional D/E screen
    and produce a wrong conclusion."""
    assert "debt_to_equity" not in DEFINITIONS_BY_KEY
    definition = DEFINITIONS_BY_KEY["liabilities_to_equity"]
    assert "not debt" in (definition.guard_note or "").lower()


def test_unimplemented_spec_ratios_are_declared_with_their_missing_inputs():
    """§12 specifies these; none is computable from the line items the
    extractor pulls today. They are listed rather than silently absent so
    the UI can say what is needed. altman_z is deliberately NOT in this
    list — see TestAltmanZDoublePrime below for why the emerging-market
    Z" variant this system implements needed a different input (book
    value of equity, not market_cap) and is now real."""
    keys = {k for k, _label, _needs in NOT_YET_COMPUTABLE}
    for expected in ("roic", "piotroski_f_score", "beneish_m"):
        assert expected in keys
    assert "altman_z" not in keys
    for _key, _label, needs in NOT_YET_COMPUTABLE:
        assert needs, "every unimplemented ratio must name what it is missing"
    # and none of them accidentally got implemented without their inputs
    assert not (keys & set(DEFINITIONS_BY_KEY))


class TestAltmanZDoublePrime:
    """§27's distress detection — Altman's emerging-market Z"-Score
    (Altman, Hartzell & Peck, 1995): Z" = 6.56 X1 + 3.26 X2 + 6.72 X3 +
    1.05 X4 + 3.25. Hand-worked against clean, synthetic numbers (never
    the real J.F. Packaging fixture above — this system has no real,
    confirmed `retained_earnings` figure for that company, and inventing
    one to extend a "real filing" fixture would be exactly the kind of
    fabricated number this project's own standing rule forbids)."""

    def _items(self, **overrides):
        base = dict(
            total_current_assets=Decimal(500), total_current_liabilities=Decimal(200),
            retained_earnings=Decimal(150), operating_profit=Decimal(100),
            total_assets=Decimal(1000), total_equity=Decimal(300), total_liabilities=Decimal(500),
        )
        base.update(overrides)
        return items(source=base)

    def test_hand_worked_example(self):
        """X1=300/1000=0.3, X2=150/1000=0.15, X3=100/1000=0.1,
        X4=300/500=0.6 (all exact divisions) ->
        Z" = 6.56(0.3) + 3.26(0.15) + 6.72(0.1) + 1.05(0.6) + 3.25
           = 1.968 + 0.489 + 0.672 + 0.63 + 3.25 = 7.009"""
        result = compute_ratio(DEFINITIONS_BY_KEY["altman_z"], self._items())
        assert result.value == Decimal("7.009")
        assert result.provenance is ProvenanceTier.REPORTED

    def test_a_distressed_company_scores_well_below_the_safe_band(self):
        """Negative working capital, accumulated losses, an operating
        loss: X1=-0.2, X2=-0.5, X3=-0.05, X4=90/900=0.1 ->
        Z" = 6.56(-0.2)+3.26(-0.5)+6.72(-0.05)+1.05(0.1)+3.25
           = -1.312-1.63-0.336+0.105+3.25 = 0.077, well under the widely-
        cited 4.35 distress threshold."""
        result = compute_ratio(
            DEFINITIONS_BY_KEY["altman_z"],
            self._items(
                total_current_assets=Decimal(100), total_current_liabilities=Decimal(300),
                retained_earnings=Decimal(-500), operating_profit=Decimal(-50),
                total_equity=Decimal(90), total_liabilities=Decimal(900),
            ),
        )
        assert result.value == Decimal("0.077")

    def test_non_positive_total_assets_is_not_meaningful_not_a_crash(self):
        result = compute_ratio(
            DEFINITIONS_BY_KEY["altman_z"], self._items(total_assets=Decimal(0))
        )
        assert result.value is None
        assert "not meaningful" in (result.note or "").lower()

    def test_non_positive_total_liabilities_is_not_meaningful_not_a_crash(self):
        result = compute_ratio(
            DEFINITIONS_BY_KEY["altman_z"], self._items(total_liabilities=Decimal(0))
        )
        assert result.value is None
