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
from app.domain.dcf import DCFAssumptions, dcf_equity_value
from app.domain.valuation_view import (
    _confirmable_line_items,
    _confirmed_dividends_as_of,
    _confirmed_statement_line_history,
    _latest_shares_issued,
    _steady_state_growth,
    _trailing_cagr,
    _trailing_dividend_per_share,
    current_period_fcff_for,
    dcf_for,
    gordon_growth_ddm_for,
    hard_book_for,
    justified_price_to_book_for,
    residual_income_for,
    valuation_summary_for,
    wacc_for,
)
from app.models.corporate_actions import CorporateAction
from app.models.enums import (
    CorporateActionType,
    NationalProjectImpactMetric,
    NationalProjectStatus,
    NationalProjectTransmissionChannel,
    ProvenanceTier,
)
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.national_projects import NationalProject, NationalProjectTickerImpact
from app.models.securities import Security

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)
AS_OF = dt.date(2022, 6, 1)


def _fake_ke(ke: Decimal | None, rf: Decimal | None = Decimal("0.12")):
    def _fn(db, ticker, as_of=None, *, regime=None):
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


def _seed_dcf_fundamentals(db, ticker="SWAD.N0000"):
    """Every line `dcf_for` needs for one confirmed period, chosen so its
    embedded WACC reproduces `TestWACCFor`'s own hand-worked case exactly
    (same debt, interest, tax rate, shares, price, Ke) rather than
    introducing a second, un-cross-checked WACC number."""
    lines = {
        "revenue": Decimal(10000),
        "operating_profit": Decimal(1000),  # margin = 0.10
        "profit_before_tax": Decimal(900),
        "income_tax_expense": Decimal(-252),  # 252/900 = 0.28 effective rate
        "depreciation_and_amortisation": Decimal(50),
        "capital_expenditure": Decimal(-80),  # cash-flow-statement sign convention
        "net_working_capital": Decimal(500),
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


class TestConfirmedStatementLineHistory:
    def test_returns_confirmed_only_sorted_oldest_first(self, db_session):
        _seed_security(db_session, ticker="SWAD.N0000")
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=dt.date(2020, 12, 31), period_type="annual",
                    first_available_date=dt.date(2021, 3, 1), version=1, statement_line="revenue",
                    value=Decimal(8000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line="revenue",
                    value=Decimal(10000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                # A later, unconfirmed period must be excluded — §8, same
                # gate `_confirmable_line_items` already applies within one
                # period, applied here across periods instead.
                Fundamental(
                    ticker="SWAD.N0000", period_end=dt.date(2022, 12, 31), period_type="annual",
                    first_available_date=dt.date(2023, 3, 1), version=1, statement_line="revenue",
                    value=Decimal(20000), provenance_tier=ProvenanceTier.AI_ASSISTED,
                ),
            ]
        )
        db_session.commit()
        history = _confirmed_statement_line_history(db_session, "SWAD.N0000", "revenue", AS_OF)
        assert history == [(dt.date(2020, 12, 31), Decimal(8000)), (PERIOD_END, Decimal(10000))]


class TestTrailingCagr:
    def test_none_with_fewer_than_two_periods(self):
        assert _trailing_cagr([(PERIOD_END, Decimal(10000))]) is None
        assert _trailing_cagr([]) is None

    def test_hand_worked_two_periods_one_year_apart(self):
        history = [(dt.date(2020, 12, 31), Decimal(10000)), (dt.date(2021, 12, 31), Decimal(11000))]
        result = _trailing_cagr(history)
        # 11000/10000 - 1 = 0.10 exactly over ~365 days; 365/365.25 is
        # near-enough 1 year that the annualised rate should land very
        # close to 0.10, not exactly (elapsed time isn't assumed to be a
        # whole year).
        assert abs(result - Decimal("0.10")) < Decimal("0.001")

    def test_none_when_oldest_value_not_positive(self):
        history = [(dt.date(2020, 12, 31), Decimal(-100)), (PERIOD_END, Decimal(10000))]
        assert _trailing_cagr(history) is None

    def test_none_when_newest_value_not_positive(self):
        history = [(dt.date(2020, 12, 31), Decimal(10000)), (PERIOD_END, Decimal(-100))]
        assert _trailing_cagr(history) is None


class TestDCFFor:
    def test_hand_worked_flat_no_growth_view(self, db_session, monkeypatch):
        """Only ONE confirmed revenue period is seeded, so §18.2's
        trailing-CAGR source for Y1/Y2 growth isn't available yet and
        `dcf_for` must fall back to the same steady-state g used for
        stage-2/terminal growth — making the whole 10-year growth path
        flat. Cross-checked against `dcf_equity_value` called directly
        with the SAME real figures (querying `wacc_for`/`compute_all`
        the exact same way `dcf_for` does internally, rather than
        hand-re-deriving WACC/effective-tax-rate's own precision), the
        same "cross-check against the module's own computation" pattern
        `test_dcf.py` already uses for FCFF.
        """
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_dcf_fundamentals(db_session)
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = dcf_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is not None
        assert view.fair_value_per_share is not None
        assert view.fair_value_per_share > 0

        wacc_view = wacc_for(db_session, "SWAD.N0000", Decimal(20), AS_OF)
        expected = dcf_equity_value(
            DCFAssumptions(
                base_revenue=Decimal(10000),
                revenue_growth_y1=Decimal("0.05"),
                revenue_growth_y2=Decimal("0.05"),
                revenue_growth_stage2_target=Decimal("0.05"),
                terminal_growth=Decimal("0.05"),
                operating_margin_current=Decimal("0.1"),
                operating_margin_target=Decimal("0.1"),
                effective_tax_rate_current=Decimal(252) / Decimal(900),
                statutory_tax_rate=Decimal("0.30"),
                depreciation_amortisation_pct_revenue=Decimal(50) / Decimal(10000),
                capex_pct_revenue=Decimal(80) / Decimal(10000),
                working_capital_pct_revenue=Decimal(500) / Decimal(10000),
                risk_free_rate=Decimal("0.12"),
                discount_rate=wacc_view.result.wacc,
                total_debt=Decimal(500),
                diluted_shares_outstanding=Decimal(100),
            )
        )
        assert view.result.value_per_share == expected.value_per_share
        assert view.result.equity_value == expected.equity_value

        # The two directionally-unsafe zeroed bridge items are flagged
        # every time, not silently trusted — same discipline as
        # app.domain.wacc's missing-cost-of-debt rule.
        assert any("minority_interest" in w for w in view.warnings)
        assert any("pension_deficit" in w for w in view.warnings)
        assert any("no growth view" in w for w in view.warnings)

    def test_prefers_real_trailing_cagr_over_the_steady_state_fallback(self, db_session, monkeypatch):
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_dcf_fundamentals(db_session)  # confirmed revenue = 10000 at PERIOD_END
        # A second, earlier confirmed revenue period — now a real 2-period
        # trailing CAGR exists and must be preferred over the flat
        # steady-state fallback.
        db_session.add(
            Fundamental(
                ticker="SWAD.N0000", period_end=dt.date(2020, 12, 31), period_type="annual",
                first_available_date=dt.date(2021, 3, 1), version=1, statement_line="revenue",
                value=Decimal(8000), provenance_tier=ProvenanceTier.REPORTED,
            )
        )
        db_session.commit()
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = dcf_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is not None
        # 10000/8000 - 1 = 0.25 trailing CAGR — well above the 0.05
        # steady-state fallback, so Y1 revenue growth must reflect it.
        assert view.result.years[0].revenue_growth > Decimal("0.05")
        assert any("trailing CAGR" in w for w in view.warnings)
        assert not any("no growth view" in w for w in view.warnings)

    def test_missing_net_working_capital_is_named_not_silently_zeroed(self, db_session, monkeypatch):
        _seed_security(db_session, ticker="SWAD.N0000")
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line=line,
                    value=value, provenance_tier=ProvenanceTier.REPORTED,
                )
                for line, value in {
                    "revenue": Decimal(10000),
                    "operating_profit": Decimal(1000),
                    "profit_before_tax": Decimal(900),
                    "income_tax_expense": Decimal(-252),
                    "depreciation_and_amortisation": Decimal(50),
                    "capital_expenditure": Decimal(-80),
                    "total_interest_bearing_debt": Decimal(500),
                    "interest_expense": Decimal(50),
                    # net_working_capital deliberately omitted
                }.items()
            ]
        )
        db_session.commit()
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        view = dcf_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is None
        assert view.fair_value_per_share is None
        assert any("net_working_capital" in w for w in view.warnings)

    def test_no_fundamentals_at_all(self, db_session):
        _seed_security(db_session, ticker="SWAD.N0000")
        view = dcf_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is None
        assert view.period_end is None

    def test_confirmed_national_project_adjusts_y1_y2_growth(self, db_session, monkeypatch):
        """§18.2's own words: Y1/Y2 revenue growth is adjusted by "any
        confirmed project in the register (§34)". Same flat, one-period
        fixture as `test_hand_worked_flat_no_growth_view` (so the
        baseline 0.05 steady-state growth is already independently
        verified there), plus one confirmed, financing-closed §34
        project naming this ticker's revenue — the resulting Y1 growth
        should be exactly 0.05 + the project's own quantified impact."""
        _seed_security(db_session, ticker="SWAD.N0000")
        _seed_dcf_fundamentals(db_session)
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        project = NationalProject(
            name="Test reconstruction project",
            status=NationalProjectStatus.FINANCING_CLOSED,
            confirmed_by="analyst",
            confirmed_at=dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc),
        )
        db_session.add(project)
        db_session.flush()
        db_session.add(
            NationalProjectTickerImpact(
                project_id=project.id, ticker="SWAD.N0000",
                transmission_channel=NationalProjectTransmissionChannel.MATERIALS_SUPPLIER,
                impact_metric=NationalProjectImpactMetric.REVENUE,
                quantified_impact_pct=Decimal("0.01"),
                impact_description="Test fixture.", provenance_tag=ProvenanceTier.ESTIMATED,
            )
        )
        db_session.commit()

        view = dcf_for(db_session, "SWAD.N0000", current_price=Decimal(20), as_of=AS_OF)
        assert view.result is not None
        # Baseline (no project) is 0.05 (test_hand_worked_flat_no_growth_view) + 0.01 project adjustment.
        assert view.result.years[0].revenue_growth == Decimal("0.06")
        assert any("national-project-register" in w for w in view.warnings)


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


class TestHardBookFor:
    def test_hand_worked_with_a_real_reserve(self, db_session):
        """AHPL-shaped fixture: a real, non-zero revaluation_reserves
        line present alongside total_equity."""
        _seed_security(db_session, ticker="AHPL.N0000")
        db_session.add_all(
            [
                Fundamental(
                    ticker="AHPL.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                    value=Decimal("33549127"), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker="AHPL.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line="revaluation_reserves",
                    value=Decimal("21752125"), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.commit()
        _seed_shares(db_session, ticker="AHPL.N0000", shares=100)

        view = hard_book_for(db_session, "AHPL.N0000", AS_OF)
        assert view.result is not None
        assert view.result.reported_book_value == Decimal("33549127")
        assert view.result.revaluation_reserves == Decimal("21752125")
        # 33,549,127 - 21,752,125 = 11,797,002
        assert view.result.hard_book_value == Decimal("11797002")
        assert view.result.hard_book_per_share == Decimal("117970.02")
        # A real reserve WAS found — no ambiguity warning about a missing line.
        assert not any("No revaluation_reserves line found" in w for w in view.warnings)

    def test_no_revaluation_reserve_line_defaults_to_zero_but_warns(self, db_session):
        """Kelani-Valley-Plantations-shaped fixture: total_equity exists,
        no revaluation_reserves line at all. Per `hard_book_for`'s own
        documented choice, this still returns a result (absence is
        usually the real, correct case) but ALWAYS flags the ambiguity —
        this could be a genuine zero or an unmatched real reserve."""
        _seed_security(db_session, ticker="KVPL.N0000")
        db_session.add(
            Fundamental(
                ticker="KVPL.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            )
        )
        db_session.commit()
        _seed_shares(db_session, ticker="KVPL.N0000", shares=100)

        view = hard_book_for(db_session, "KVPL.N0000", AS_OF)
        assert view.result is not None
        assert view.result.revaluation_reserves == Decimal(0)
        assert view.result.hard_book_value == Decimal(1000)  # unchanged — no reserve to strip
        assert any("No revaluation_reserves line found" in w for w in view.warnings)

    def test_missing_total_equity_gives_no_result(self, db_session):
        _seed_security(db_session, ticker="AHPL.N0000")
        # A confirmed period exists (net_income), but not total_equity —
        # distinct from the "no fundamentals visible at all" case.
        db_session.add(
            Fundamental(
                ticker="AHPL.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=Decimal(100), provenance_tier=ProvenanceTier.REPORTED,
            )
        )
        db_session.commit()
        view = hard_book_for(db_session, "AHPL.N0000", AS_OF)
        assert view.result is None
        assert any("total_equity not available" in w for w in view.warnings)

    def test_unconfirmed_line_excludes_from_the_figure(self, db_session):
        _seed_security(db_session, ticker="AHPL.N0000")
        db_session.add(
            Fundamental(
                ticker="AHPL.N0000", period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.AI_ASSISTED,
            )
        )
        db_session.commit()

        view = hard_book_for(db_session, "AHPL.N0000", AS_OF)
        assert view.result is None
        assert "total_equity" in view.excluded_unconfirmed_lines


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

    def test_dcf_joins_residual_income_as_a_second_intrinsic_anchor(self, db_session, monkeypatch):
        """A Swadeshi-shaped fixture with every §18 DCF input present:
        `dcf_for`'s own fair value must both be non-None AND actually
        feed the "intrinsic" triangulation bucket alongside residual
        income — the whole point of wiring the multi-year forecast, not
        just of the pure `dcf_equity_value` arithmetic being correct in
        isolation (already covered by `test_dcf.py`)."""
        _seed_security(db_session, ticker="SWAD.N0000")
        # total_equity/net_income for the residual-income anchor — seeded
        # directly rather than via `_seed_confirmed_fundamentals`, which
        # also seeds an unconfirmed `revenue` line at the SAME period that
        # would otherwise collide with `_seed_dcf_fundamentals`' own
        # confirmed `revenue` line for that key.
        db_session.add_all(
            [
                Fundamental(
                    ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                    value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
                ),
                Fundamental(
                    ticker="SWAD.N0000", period_end=PERIOD_END, period_type="annual",
                    first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                    value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
                ),
            ]
        )
        db_session.commit()
        _seed_dcf_fundamentals(db_session, ticker="SWAD.N0000")  # revenue/EBIT/D&A/capex/NWC/debt → DCF anchor
        _seed_shares(db_session, ticker="SWAD.N0000", shares=100)
        monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke(Decimal("0.15")))

        summary = valuation_summary_for(
            db_session, "SWAD.N0000", archetype="manufacturing", current_price=Decimal(20), as_of=AS_OF
        )

        assert summary.dcf.fair_value_per_share is not None
        assert summary.residual_income.result is not None
        assert summary.residual_income.result.value_per_share is not None
        # Both anchors are real, distinct numbers, both counted — not one
        # silently overwriting the other because they share a category.
        assert "intrinsic" in summary.triangulation.category_averages
        assert summary.triangulation.blended_fair_value_per_share is not None
