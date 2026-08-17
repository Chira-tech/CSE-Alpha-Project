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
    _confirmed_dividends_as_of,
    _latest_shares_issued,
    _steady_state_growth,
    _trailing_dividend_per_share,
    current_period_fcff_for,
    gordon_growth_ddm_for,
    justified_price_to_book_for,
    residual_income_for,
    valuation_summary_for,
    wacc_for,
)
from app.models.corporate_actions import CorporateAction
from app.models.enums import CorporateActionType, ProvenanceTier
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


def _seed_confirmed_dividend(
    db, ticker="COMB.N0000", ex_date=dt.date(2022, 1, 15), cash_amount=Decimal("2.00")
):
    db.add(
        CorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=CorporateActionType.DIVIDEND_CASH,
            cash_amount=cash_amount,
            confirmed_by="test",
            confirmed_at=dt.datetime(2022, 1, 20, tzinfo=dt.timezone.utc),
        )
    )
    db.commit()


def _seed_unconfirmed_dividend(
    db, ticker="COMB.N0000", ex_date=dt.date(2022, 1, 15), cash_amount=Decimal("2.00")
):
    db.add(
        CorporateAction(
            ticker=ticker,
            ex_date=ex_date,
            type=CorporateActionType.DIVIDEND_CASH,
            cash_amount=cash_amount,
            confirmed_by=None,
            confirmed_at=None,
        )
    )
    db.commit()


def _seed_wacc_fundamentals(db, ticker="SWAD.N0000"):
    """Adds the two WACC-specific lines to whatever's already seeded —
    profit_before_tax/income_tax_expense (0.28 effective rate, same as
    _seed_fcff_fundamentals) supply the tax rate WACC's cost-of-debt
    needs too."""
    lines = {
        "profit_before_tax": Decimal(900),
        "income_tax_expense": Decimal(-252),
        "total_interest_bearing_debt": Decimal(500),
        "interest_expense": Decimal(50),  # pre-tax Kd = 50/500 = 0.10
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


class TestWACCFor:
    def test_hand_worked(self, db_session, monkeypatch):
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_wacc_fundamentals(db_session)
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = wacc_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is not None
        # E = 100*20 = 2000; D = 500; We=0.8, Wd=0.2
        # Kd pre-tax = 50/500 = 0.10; after-tax = 0.10*0.72 = 0.072
        # WACC = 0.8*0.15 + 0.2*0.072 = 0.12 + 0.0144 = 0.1344
        assert view.result.equity_weight == Decimal("0.8")
        assert view.result.debt_weight == Decimal("0.2")
        assert abs(view.result.wacc - Decimal("0.1344")) < Decimal("0.0001")
        assert view.result.wacc < Decimal("0.15")  # strictly below Ke — the whole point of WACC existing

    def test_missing_debt_gives_no_wacc(self, db_session, monkeypatch):
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = wacc_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is None or view.result.wacc is None
        assert view.warnings


class TestConfirmedDividendsAsOf:
    def test_excludes_unconfirmed_and_future_ex_date(self, db_session):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2022, 1, 15), cash_amount=Decimal("2.00"))
        _seed_unconfirmed_dividend(db_session, ex_date=dt.date(2022, 2, 15), cash_amount=Decimal("9.00"))
        # Confirmed but ex_date is AFTER AS_OF (2022-06-01) — not yet point-in-time visible.
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2022, 7, 1), cash_amount=Decimal("3.00"))

        rows = _confirmed_dividends_as_of(db_session, "COMB.N0000", AS_OF)
        assert len(rows) == 1
        assert rows[0].cash_amount == Decimal("2.00")

    def test_no_confirmed_rows_at_all(self, db_session):
        _seed_security(db_session)
        assert _confirmed_dividends_as_of(db_session, "COMB.N0000", AS_OF) == ()

    def test_ordered_oldest_to_newest(self, db_session):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2022, 2, 1), cash_amount=Decimal("1.50"))
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2021, 8, 1), cash_amount=Decimal("1.00"))
        rows = _confirmed_dividends_as_of(db_session, "COMB.N0000", AS_OF)
        assert [r.ex_date for r in rows] == [dt.date(2021, 8, 1), dt.date(2022, 2, 1)]


class TestTrailingDividendPerShare:
    def _ca(self, ex_date, cash_amount):
        return CorporateAction(
            ticker="COMB.N0000", ex_date=ex_date, type=CorporateActionType.DIVIDEND_CASH,
            cash_amount=cash_amount,
        )

    def test_sums_multiple_payments_within_the_trailing_window(self):
        divs = (
            self._ca(dt.date(2021, 8, 1), Decimal("1.00")),
            self._ca(dt.date(2022, 2, 1), Decimal("1.50")),
        )
        dps, count = _trailing_dividend_per_share(divs, AS_OF)  # AS_OF = 2022-06-01
        assert dps == Decimal("2.50")
        assert count == 2

    def test_excludes_a_payment_older_than_twelve_months(self):
        divs = (self._ca(dt.date(2020, 1, 1), Decimal("5.00")),)
        dps, count = _trailing_dividend_per_share(divs, AS_OF)
        assert dps is None
        assert count == 0

    def test_mixed_window_only_sums_the_recent_one(self):
        divs = (
            self._ca(dt.date(2019, 1, 1), Decimal("9.00")),  # stale, excluded
            self._ca(dt.date(2022, 1, 1), Decimal("1.00")),  # within window
        )
        dps, count = _trailing_dividend_per_share(divs, AS_OF)
        assert dps == Decimal("1.00")
        assert count == 1


class TestGordonGrowthDDMFor:
    def test_no_confirmed_dividends_returns_none_with_named_reason(self, db_session, monkeypatch):
        _seed_security(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is None
        assert view.warnings
        assert "No confirmed DIVIDEND_CASH" in view.warnings[0]

    def test_unconfirmed_dividend_is_excluded_not_used(self, db_session, monkeypatch):
        """§8/§9 regression, mirroring `test_unconfirmed_line_excludes_
        from_the_figure` for Fundamental rows: an unconfirmed
        CorporateAction must never silently feed a valuation."""
        _seed_security(db_session)
        _seed_unconfirmed_dividend(db_session, ex_date=dt.date(2022, 1, 15), cash_amount=Decimal("2.00"))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))
        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is None
        assert "No confirmed DIVIDEND_CASH" in view.warnings[0]

    def test_hand_worked_single_dividend(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2022, 1, 15), cash_amount=Decimal("2.00"))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))  # rf=0.12 -> g=0.05

        # D0 = 2.00 (single confirmed payment in the trailing 12 months);
        # D1 = D0*(1+g) = 2.00*1.05 = 2.10; V0 = D1/(Ke-g) = 2.10/0.10 = 21.0
        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is not None
        assert abs(view.result.value_per_share - Decimal("21.0")) < Decimal("0.0001")

    def test_hand_worked_sums_interim_and_final_dividends(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2021, 8, 1), cash_amount=Decimal("1.00"))
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2022, 2, 1), cash_amount=Decimal("1.50"))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        # D0 = 1.00 + 1.50 = 2.50; D1 = 2.50*1.05 = 2.625; V0 = 2.625/0.10 = 26.25
        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert abs(view.result.value_per_share - Decimal("26.25")) < Decimal("0.0001")
        assert any("sum of 2 confirmed payments" in w for w in view.warnings)

    def test_stale_dividend_outside_trailing_window_gives_no_result(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session, ex_date=dt.date(2020, 1, 1), cash_amount=Decimal("5.00"))
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is None
        assert "none fall within the trailing twelve months" in view.warnings[0]

    def test_none_ke_gives_no_result(self, db_session, monkeypatch):
        _seed_security(db_session)
        _seed_confirmed_dividend(db_session)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(None))
        view = gordon_growth_ddm_for(db_session, "COMB.N0000", AS_OF)
        assert view.result is None
        assert any("Cost of equity not computable" in w for w in view.warnings)


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
        # No confirmed dividends seeded either — the expected state for every
        # ticker today (§8/§9's confirm-queue workflow isn't built yet).
        assert summary.gordon_growth_ddm.result is None
        assert "No confirmed DIVIDEND_CASH" in summary.gordon_growth_ddm.warnings[0]

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
