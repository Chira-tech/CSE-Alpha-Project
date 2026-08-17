"""§18-26 wired to real stored data — `app.domain.valuation_view`.

`cost_of_equity_for` is monkeypatched to a fixed, known Ke/Rf throughout:
that function's own correctness (Dimson-Blume beta, the T-bill
observation, ...) is already covered by `test_cost_of_equity.py` and
`test_beta.py`; what's under test here is this module's OWN new logic —
§8 confirmation filtering, book-value-per-share assembly, growth
clamping, and the triangulation/MoS/price-ladder wiring — not the whole
upstream Ke pipeline.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.cost_of_equity import CostOfEquityResult
from app.domain.valuation_view import (
    _confirmable_line_items,
    _latest_shares_issued,
    _steady_state_growth,
    current_period_fcff_for,
    justified_price_to_book_for,
    residual_income_for,
    valuation_summary_for,
)
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)
AS_OF = dt.date(2022, 6, 1)


def _fake_ke(ke: Decimal | None, rf: Decimal | None = Decimal("0.12")):
    def _fn(db, ticker, as_of=None):
        return CostOfEquityResult(
            ke=ke, risk_free_rate=rf, beta=Decimal("1.0"), erp_effective=Decimal("0.07"),
            beta_times_erp=Decimal("0.07"), size_premium=None, illiquidity_premium=None,
            implied_erp_cross_check=None, is_lower_bound=True, missing_components=(),
            note="stub",
        )
    return _fn


def _seed_security(db, ticker="COMB.N0000"):
    db.add(Security(ticker=ticker, name="Commercial Bank of Ceylon PLC"))
    db.commit()


def _seed_confirmed_fundamentals(db, ticker="COMB.N0000", total_equity=Decimal(1000), net_income=Decimal(200)):
    db.add_all(
        [
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=total_equity, provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=net_income, provenance_tier=ProvenanceTier.REPORTED,
            ),
            # An unconfirmed line for the SAME period — must be excluded from valuation.
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="revenue",
                value=Decimal(5000), provenance_tier=ProvenanceTier.AI_ASSISTED,
            ),
        ]
    )
    db.commit()


def _seed_shares(db, ticker="COMB.N0000", shares=100, as_of=dt.date(2022, 1, 1)):
    db.add(FloatData(ticker=ticker, as_of=as_of, shares_issued=shares))
    db.commit()


def _seed_fcff_fundamentals(db, ticker="SWAD.N0000"):
    """A Swadeshi-shaped confirmed period — every line §18.1's FCFF
    formula needs, all REPORTED tier. Round numbers chosen so the
    expected FCFF (670) matches the same hand-worked case already
    verified directly against `compute_fcff` in test_dcf.py, rather than
    introducing a second, un-cross-checked expected value."""
    lines = {
        "operating_profit": Decimal(1000),
        "profit_before_tax": Decimal(900),
        "income_tax_expense": Decimal(-252),  # 252/900 = 0.28 effective rate
        "depreciation_and_amortisation": Decimal(50),
        "capital_expenditure": Decimal(-80),  # cash-flow-statement sign convention
        "change_in_net_working_capital": Decimal(20),
    }
    db.add_all(
        Fundamental(
            ticker=ticker, period_end=PERIOD_END, period_type="annual",
            first_available_date=FIRST_AVAILABLE, version=1, statement_line=line,
            value=value, provenance_tier=ProvenanceTier.REPORTED,
        )
        for line, value in lines.items()
    )
    db.commit()


class TestConfirmableLineItems:
    def test_excludes_ai_assisted_but_keeps_reported(self, db_session):
        _seed_security(db_session)
        _seed_confirmed_fundamentals(db_session)
        period_end, items, excluded = _confirmable_line_items(db_session, "COMB.N0000", AS_OF)
        assert period_end == PERIOD_END
        assert set(items) == {"total_equity", "net_income"}
        assert excluded == ("revenue",)

    def test_no_fundamentals_at_all(self, db_session):
        _seed_security(db_session)
        period_end, items, excluded = _confirmable_line_items(db_session, "COMB.N0000", AS_OF)
        assert period_end is None
        assert items == {}


class TestLatestSharesIssued:
    def test_picks_latest_not_future(self, db_session):
        _seed_security(db_session)
        db_session.add_all(
            [
                FloatData(ticker="COMB.N0000", as_of=dt.date(2021, 1, 1), shares_issued=90),
                FloatData(ticker="COMB.N0000", as_of=dt.date(2022, 1, 1), shares_issued=100),
                FloatData(ticker="COMB.N0000", as_of=dt.date(2023, 1, 1), shares_issued=110),  # after AS_OF
            ]
        )
        db_session.commit()
        assert _latest_shares_issued(db_session, "COMB.N0000", AS_OF) == 100


class TestSteadyStateGrowth:
    def test_default_used_when_below_risk_free(self):
        assert _steady_state_growth(Decimal("0.12")) == Decimal("0.05")

    def test_clamped_when_risk_free_at_or_below_default(self):
        result = _steady_state_growth(Decimal("0.03"))
        assert result == Decimal("0.02")  # rf - 1pp

    def test_none_risk_free_returns_default_unclamped(self):
        assert _steady_state_growth(None) == Decimal("0.05")


class TestJustifiedPriceToBookFor:
    def test_hand_worked(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_fundamentals(db_session)  # ROE = 200/1000 = 0.20
        _seed_shares(db_session, shares=100)  # book value per share = 1000/100 = 10
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = justified_price_to_book_for(db_session, "COMB.N0000", AS_OF)
        assert view.inputs.roe == Decimal("0.2000")
        assert view.inputs.book_value_per_share == Decimal(10)
        # (0.20 - 0.05) / (0.15 - 0.05) = 1.5
        assert view.result.value == Decimal("1.5")
        # 1.5 * 10 = 15
        assert view.fair_value_per_share == Decimal("15.0000")
        assert view.inputs.excluded_unconfirmed_lines == ("revenue",)

    def test_none_ke_gives_no_result(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_fundamentals(db_session)
        _seed_shares(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(None))
        view = justified_price_to_book_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is None
        assert view.fair_value_per_share is None


class TestResidualIncomeFor:
    def test_hand_worked(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_fundamentals(db_session)  # ROE = 0.20
        _seed_shares(db_session, shares=100)  # book value per share = 10
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = residual_income_for(db_session, "COMB.N0000", AS_OF)
        # RI_1 = (0.20-0.15)*10 = 0.5; book_1 = 10.5
        # terminal_ri_next = (0.20-0.15)*10.5 = 0.525; terminal_value = 0.525/0.10 = 5.25
        # value = 10 + 0.5/1.15 + 5.25/1.15 = 10 + 5.0 = 15.0
        assert abs(view.result.value_per_share - Decimal("15.0")) < Decimal("0.0001")


class TestCurrentPeriodFCFFFor:
    def test_hand_worked(self, db_session):
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_fcff_fundamentals(db_session)

        view = current_period_fcff_for(db_session, "SWAD.N0000", AS_OF)
        assert view.period_end == PERIOD_END
        # Same case as test_dcf.py's TestComputeFCFF.test_hand_worked: 670
        assert view.fcff == Decimal(670)
        assert view.warnings == ()

    def test_capex_sign_is_flipped_from_the_stored_cash_outflow_convention(self, db_session):
        """A regression guard: capital_expenditure is stored NEGATIVE
        (the cash-flow statement's own printed convention), and
        compute_fcff wants the positive magnitude it subtracts. Passing
        the raw negative value through unflipped would ADD capex to
        FCFF instead of subtracting it — silently overstating FCFF by
        2x the capex figure, an easy, dangerous, and specifically
        checked-for mistake."""
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_fcff_fundamentals(db_session)
        view = current_period_fcff_for(db_session, "SWAD.N0000", AS_OF)
        # If the sign flip were missing: 1000*0.72 + 50 - (-80) - 20 = 730
        assert view.fcff != Decimal(730)
        assert view.fcff == Decimal(670)

    def test_missing_capex_is_named_not_silently_zeroed(self, db_session):
        _seed_security(db_session, ticker="SWAD.N0000")
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line=line,
                    value=value, provenance_tier=ProvenanceTier.REPORTED,
                )
                for line, value in {
                    "operating_profit": Decimal(1000),
                    "profit_before_tax": Decimal(900),
                    "income_tax_expense": Decimal(-252),
                    "depreciation_and_amortisation": Decimal(50),
                    # capital_expenditure and change_in_net_working_capital deliberately omitted
                }.items()
            ]
        )
        db_session.commit()

        view = current_period_fcff_for(db_session, "SWAD.N0000", AS_OF)
        assert view.fcff is None
        assert any("capital_expenditure" in w for w in view.warnings)
        assert any("change_in_net_working_capital" in w for w in view.warnings)

    def test_unconfirmed_line_excludes_from_the_figure(self, db_session):
        _seed_security(db_session, ticker="SWAD.N0000")
        db_session.add(
            Fundamental(
                ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="operating_profit",
                value=Decimal(1000), provenance_tier=ProvenanceTier.AI_ASSISTED,
            )
        )
        db_session.commit()

        view = current_period_fcff_for(db_session, "SWAD.N0000", AS_OF)
        assert view.fcff is None
        assert "operating_profit" in view.excluded_unconfirmed_lines


class TestValuationSummaryFor:
    def test_end_to_end_bank_triangulation_and_ladder(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_fundamentals(db_session)
        _seed_shares(db_session, shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        summary = valuation_summary_for(
            db_session, "COMB.N0000", archetype="bank", current_price=Decimal(12), as_of=AS_OF
        )

        assert summary.routing.archetype == "bank"
        # Both anchors land at 15.0 (see the two hand-worked tests above) →
        # dispersion is exactly zero, and "asset_sotp" has no anchor at all.
        assert summary.triangulation.missing_categories == ("asset_sotp",)
        assert abs(summary.triangulation.blended_fair_value_per_share - Decimal("15")) < Decimal("0.001")
        assert summary.triangulation.dispersion_pct == Decimal(0)

        assert summary.margin_of_safety.total_pct == Decimal("0.10")  # base only, rest unavailable
        assert summary.margin_of_safety.is_lower_bound

        # FV=15, MoS=10% → strong_accumulate = 15*0.82=12.30; current=12 is below it.
        assert summary.price_ladder is not None
        assert summary.price_ladder.current_zone == "strong_accumulate"
        assert summary.current_price == Decimal(12)
        # No capex/D&A/WC seeded for COMB.N0000 in this fixture — informational
        # only, and correctly absent rather than silently zero.
        assert summary.current_period_fcff.fcff is None

    def test_no_confirmed_data_gives_no_anchors_and_no_ladder(self, db_session, monkeypatch):
        _seed_security(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        summary = valuation_summary_for(
            db_session, "COMB.N0000", archetype="bank", current_price=Decimal(12), as_of=AS_OF
        )
        assert summary.triangulation.blended_fair_value_per_share is None
        assert summary.price_ladder is None
        # Regression: a real current price must still be reported even when
        # there's no fair value yet to build a price ladder from — caught
        # live against a real bootstrapped ticker (COMB.N0000, 17 Aug),
        # where `CompanyValuationOut.current_price` was silently None
        # because it was derived from `price_ladder.current_price` instead
        # of being carried on `CompanyValuationSummary` independently.
        assert summary.current_price == Decimal(12)
