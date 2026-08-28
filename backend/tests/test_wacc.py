"""§18.1's WACC — hand-worked reference values, including the
FCFF-vs-Ke mispricing this module exists specifically to prevent."""
from __future__ import annotations

from decimal import Decimal

from app.domain.wacc import compute_cost_of_debt, compute_wacc


class TestComputeCostOfDebt:
    def test_hand_worked(self):
        # Swadeshi's real figures: 48,834,907 / 645,836,104 = 0.0756150...
        result = compute_cost_of_debt(
            interest_expense=Decimal("48834907"),
            total_interest_bearing_debt=Decimal("645836104"),
            effective_tax_rate=Decimal("0.28"),
        )
        assert abs(result.pre_tax_cost_of_debt - Decimal("0.0756150")) < Decimal("0.0000001")
        # after-tax: 0.0756150 * 0.72 = 0.0544428
        assert abs(result.after_tax_cost_of_debt - Decimal("0.0544428")) < Decimal("0.0000001")

    def test_missing_inputs_gives_none_not_a_guess(self):
        result = compute_cost_of_debt(None, Decimal(100), Decimal("0.28"))
        assert result.pre_tax_cost_of_debt is None
        assert result.after_tax_cost_of_debt is None

    def test_zero_debt_is_not_meaningful(self):
        result = compute_cost_of_debt(Decimal(10), Decimal(0), Decimal("0.28"))
        assert result.pre_tax_cost_of_debt is None

    def test_pre_tax_computable_without_tax_rate_but_after_tax_is_not(self):
        result = compute_cost_of_debt(Decimal(10), Decimal(100), None)
        assert result.pre_tax_cost_of_debt == Decimal("0.1")
        assert result.after_tax_cost_of_debt is None

    def test_a_negative_signed_interest_expense_does_not_produce_a_negative_cost_of_debt(self):
        """REAL BUG, found live (27 Aug 2026): LGL.N0000's real confirmed
        `interest_expense` for its FY2013 annual filing is stored as
        -5,053,018 — a faithful read of that filing's own real
        parenthesised "Finance Costs 6.3 (5,053,018) ..." line — while
        its own real quarterly filing for an adjacent period shows the
        identical LKR 5,053,018 figure unparenthesised (positive). Both
        are correct reads of genuinely inconsistent real source
        documents; only the magnitude is reliable. Without abs(), this
        would produce a NEGATIVE cost of debt, pulling WACC down and
        overstating every DCF value built on it — the same dangerous
        direction this module already guards against for a MISSING cost
        of debt."""
        negative = compute_cost_of_debt(
            interest_expense=Decimal("-5053018"),
            total_interest_bearing_debt=Decimal("100000000"),
            effective_tax_rate=Decimal("0.28"),
        )
        positive = compute_cost_of_debt(
            interest_expense=Decimal("5053018"),
            total_interest_bearing_debt=Decimal("100000000"),
            effective_tax_rate=Decimal("0.28"),
        )
        assert negative.pre_tax_cost_of_debt > 0
        assert negative.pre_tax_cost_of_debt == positive.pre_tax_cost_of_debt
        assert negative.after_tax_cost_of_debt == positive.after_tax_cost_of_debt


class TestComputeWACC:
    def test_hand_worked(self):
        # E = 100 shares * 20 = 2000; D = 500
        # We = 2000/2500 = 0.8; Wd = 500/2500 = 0.2
        # WACC = 0.8*0.15 + 0.2*0.054445 = 0.12 + 0.010889 = 0.130889
        result = compute_wacc(
            shares_outstanding=Decimal(100),
            current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(500),
            cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=Decimal("0.054445"),
        )
        assert result.market_value_of_equity == Decimal(2000)
        assert result.equity_weight == Decimal("0.8")
        assert result.debt_weight == Decimal("0.2")
        expected = Decimal("0.8") * Decimal("0.15") + Decimal("0.2") * Decimal("0.054445")
        assert abs(result.wacc - expected) < Decimal("0.000001")

    def test_a_negative_signed_debt_balance_does_not_invert_the_weights(self):
        """REAL BUG, found live (27 Aug 2026): LVEF.N0000's real confirmed
        `total_interest_bearing_debt` for its FY2025 annual filing is
        stored as -2,851,407,000 — a faithful read of that filing's own
        real parenthesised debt-maturity-split line — while its own real
        quarterly filing shows the identical figure unparenthesised
        (positive). A debt BALANCE can never legitimately be negative;
        without abs(), this would make `debt_weight` negative and
        `equity_weight` exceed 1.0 — an uninterpretable weighted average,
        not just a wrong number."""
        negative = compute_wacc(
            shares_outstanding=Decimal(100),
            current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(-500),
            cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=Decimal("0.054445"),
        )
        positive = compute_wacc(
            shares_outstanding=Decimal(100),
            current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(500),
            cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=Decimal("0.054445"),
        )
        assert negative.debt_weight == positive.debt_weight == Decimal("0.2")
        assert negative.equity_weight == positive.equity_weight == Decimal("0.8")
        assert negative.wacc == positive.wacc

    def test_wacc_is_lower_than_ke_alone_for_a_levered_company(self):
        """The whole point of this module: a levered company's discount
        rate for an UNLEVERED cash flow (FCFF) must differ from Ke — if
        WACC ever silently equalled Ke for a company with real debt on
        its balance sheet, that would BE the exact mispricing bug this
        module exists to prevent. Kd (after tax, ~5.4%) is meaningfully
        below Ke (15%) here, as it normally is, so WACC must land
        strictly between them."""
        ke = Decimal("0.15")
        result = compute_wacc(
            shares_outstanding=Decimal(100), current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(500), cost_of_equity=ke,
            after_tax_cost_of_debt=Decimal("0.054445"),
        )
        assert result.wacc < ke
        assert result.wacc > Decimal("0.054445")

    def test_missing_cost_of_debt_with_real_debt_gives_no_wacc_not_a_lower_bound(self):
        """The core design decision this module makes differently from
        cost_of_equity.py: a missing Kd is NEVER treated as zero, because
        zero would understate WACC and overstate every DCF value built
        on it — the dangerous direction, unlike a missing risk premium."""
        result = compute_wacc(
            shares_outstanding=Decimal(100), current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(500), cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=None,
        )
        assert result.wacc is None
        assert result.equity_weight == Decimal("0.8")  # weights ARE still shown
        assert result.debt_weight == Decimal("0.2")
        assert "after_tax_cost_of_debt" in result.missing_components
        assert "understate" in result.note

    def test_missing_shares_or_price_blocks_equity_value(self):
        result = compute_wacc(
            shares_outstanding=None, current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(500), cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=Decimal("0.05"),
        )
        assert result.wacc is None
        assert any("market value of equity" in m for m in result.missing_components)

    def test_zero_debt_company_still_needs_a_computable_cost_of_debt_field_absent(self):
        """A debt-free company (total_interest_bearing_debt=0) would have
        debt_weight=0, at which point WACC collapses to We×Ke exactly —
        but compute_wacc still requires after_tax_cost_of_debt to be
        supplied (even if irrelevant at a 0 weight) rather than silently
        assuming 0 debt means "no cost-of-debt data needed," keeping the
        function's contract simple and impossible to misuse by omission."""
        result = compute_wacc(
            shares_outstanding=Decimal(100), current_price=Decimal(20),
            total_interest_bearing_debt=Decimal(0), cost_of_equity=Decimal("0.15"),
            after_tax_cost_of_debt=Decimal("0.05"),
        )
        assert result.debt_weight == Decimal("0")
        assert result.equity_weight == Decimal("1")
        assert result.wacc == Decimal("0.15")  # collapses to Ke exactly at zero debt weight
