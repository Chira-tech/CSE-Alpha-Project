"""
Dimson-corrected, Blume-adjusted beta.

The 50-session window below is real: COMB.N0000 closes from
`companyChartDataByStock`, and ASPI closes reconstructed by
`app.domain.index_history` from `chartData`, both captured live on
17 Aug 2026 (19 Aug 2025 - 30 Oct 2025, the first 50 trading days common
to both series). It is a genuine subset of the full backfilled year, cut
down for a manageable test file, not synthetic data — the expected
coefficients below are what this module's own code produced against it,
recorded so a future change that silently alters the regression shows up
as a failing test rather than a quietly different number.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.domain.beta import PriceSeriesPoint, compute_dimson_beta

STOCK = [
    PriceSeriesPoint(dt.date(2025, 8, 19), Decimal("196.75")),
    PriceSeriesPoint(dt.date(2025, 8, 20), Decimal("197.75")),
    PriceSeriesPoint(dt.date(2025, 8, 21), Decimal("197.5")),
    PriceSeriesPoint(dt.date(2025, 8, 22), Decimal("195.25")),
    PriceSeriesPoint(dt.date(2025, 8, 25), Decimal("193.25")),
    PriceSeriesPoint(dt.date(2025, 8, 26), Decimal("194.25")),
    PriceSeriesPoint(dt.date(2025, 8, 27), Decimal("194.5")),
    PriceSeriesPoint(dt.date(2025, 8, 28), Decimal("193.75")),
    PriceSeriesPoint(dt.date(2025, 8, 29), Decimal("194.75")),
    PriceSeriesPoint(dt.date(2025, 9, 1), Decimal("194.75")),
    PriceSeriesPoint(dt.date(2025, 9, 2), Decimal("193.25")),
    PriceSeriesPoint(dt.date(2025, 9, 3), Decimal("192.5")),
    PriceSeriesPoint(dt.date(2025, 9, 4), Decimal("192.5")),
    PriceSeriesPoint(dt.date(2025, 9, 8), Decimal("190.75")),
    PriceSeriesPoint(dt.date(2025, 9, 9), Decimal("190.0")),
    PriceSeriesPoint(dt.date(2025, 9, 10), Decimal("191.0")),
    PriceSeriesPoint(dt.date(2025, 9, 11), Decimal("190.0")),
    PriceSeriesPoint(dt.date(2025, 9, 12), Decimal("187.0")),
    PriceSeriesPoint(dt.date(2025, 9, 15), Decimal("182.75")),
    PriceSeriesPoint(dt.date(2025, 9, 16), Decimal("186.5")),
    PriceSeriesPoint(dt.date(2025, 9, 17), Decimal("190.0")),
    PriceSeriesPoint(dt.date(2025, 9, 18), Decimal("190.0")),
    PriceSeriesPoint(dt.date(2025, 9, 19), Decimal("190.25")),
    PriceSeriesPoint(dt.date(2025, 9, 22), Decimal("193.25")),
    PriceSeriesPoint(dt.date(2025, 9, 23), Decimal("192.5")),
    PriceSeriesPoint(dt.date(2025, 9, 24), Decimal("194.0")),
    PriceSeriesPoint(dt.date(2025, 9, 25), Decimal("193.0")),
    PriceSeriesPoint(dt.date(2025, 9, 26), Decimal("193.5")),
    PriceSeriesPoint(dt.date(2025, 9, 29), Decimal("193.0")),
    PriceSeriesPoint(dt.date(2025, 9, 30), Decimal("192.75")),
    PriceSeriesPoint(dt.date(2025, 10, 1), Decimal("193.75")),
    PriceSeriesPoint(dt.date(2025, 10, 2), Decimal("193.25")),
    PriceSeriesPoint(dt.date(2025, 10, 3), Decimal("194.75")),
    PriceSeriesPoint(dt.date(2025, 10, 7), Decimal("196.25")),
    PriceSeriesPoint(dt.date(2025, 10, 8), Decimal("197.0")),
    PriceSeriesPoint(dt.date(2025, 10, 9), Decimal("203.25")),
    PriceSeriesPoint(dt.date(2025, 10, 10), Decimal("205.0")),
    PriceSeriesPoint(dt.date(2025, 10, 13), Decimal("203.5")),
    PriceSeriesPoint(dt.date(2025, 10, 14), Decimal("204.0")),
    PriceSeriesPoint(dt.date(2025, 10, 15), Decimal("204.25")),
    PriceSeriesPoint(dt.date(2025, 10, 16), Decimal("205.0")),
    PriceSeriesPoint(dt.date(2025, 10, 17), Decimal("206.5")),
    PriceSeriesPoint(dt.date(2025, 10, 21), Decimal("206.75")),
    PriceSeriesPoint(dt.date(2025, 10, 22), Decimal("206.0")),
    PriceSeriesPoint(dt.date(2025, 10, 23), Decimal("205.0")),
    PriceSeriesPoint(dt.date(2025, 10, 24), Decimal("205.5")),
    PriceSeriesPoint(dt.date(2025, 10, 27), Decimal("205.0")),
    PriceSeriesPoint(dt.date(2025, 10, 28), Decimal("204.0")),
    PriceSeriesPoint(dt.date(2025, 10, 29), Decimal("204.5")),
    PriceSeriesPoint(dt.date(2025, 10, 30), Decimal("204.75")),
]

MARKET = [
    PriceSeriesPoint(dt.date(2025, 8, 19), Decimal("20571.07")),
    PriceSeriesPoint(dt.date(2025, 8, 20), Decimal("20714.80")),
    PriceSeriesPoint(dt.date(2025, 8, 21), Decimal("20715.49")),
    PriceSeriesPoint(dt.date(2025, 8, 22), Decimal("20649.2")),
    PriceSeriesPoint(dt.date(2025, 8, 25), Decimal("20575.59")),
    PriceSeriesPoint(dt.date(2025, 8, 26), Decimal("20613.39")),
    PriceSeriesPoint(dt.date(2025, 8, 27), Decimal("20753.21")),
    PriceSeriesPoint(dt.date(2025, 8, 28), Decimal("20800.26")),
    PriceSeriesPoint(dt.date(2025, 8, 29), Decimal("20997.36")),
    PriceSeriesPoint(dt.date(2025, 9, 1), Decimal("21062.45")),
    PriceSeriesPoint(dt.date(2025, 9, 2), Decimal("20990.67")),
    PriceSeriesPoint(dt.date(2025, 9, 3), Decimal("20975.73")),
    PriceSeriesPoint(dt.date(2025, 9, 4), Decimal("20991.98")),
    PriceSeriesPoint(dt.date(2025, 9, 8), Decimal("20905.83")),
    PriceSeriesPoint(dt.date(2025, 9, 9), Decimal("20674.11")),
    PriceSeriesPoint(dt.date(2025, 9, 10), Decimal("20769.34")),
    PriceSeriesPoint(dt.date(2025, 9, 11), Decimal("20641.83")),
    PriceSeriesPoint(dt.date(2025, 9, 12), Decimal("20612.40")),
    PriceSeriesPoint(dt.date(2025, 9, 15), Decimal("20355.39")),
    PriceSeriesPoint(dt.date(2025, 9, 16), Decimal("20619.37")),
    PriceSeriesPoint(dt.date(2025, 9, 17), Decimal("20775.42")),
    PriceSeriesPoint(dt.date(2025, 9, 18), Decimal("20965.26")),
    PriceSeriesPoint(dt.date(2025, 9, 19), Decimal("21085.09")),
    PriceSeriesPoint(dt.date(2025, 9, 22), Decimal("21226.87")),
    PriceSeriesPoint(dt.date(2025, 9, 23), Decimal("21282.84")),
    PriceSeriesPoint(dt.date(2025, 9, 24), Decimal("21338.45")),
    PriceSeriesPoint(dt.date(2025, 9, 25), Decimal("21521.06")),
    PriceSeriesPoint(dt.date(2025, 9, 26), Decimal("21598.99")),
    PriceSeriesPoint(dt.date(2025, 9, 29), Decimal("21676.3")),
    PriceSeriesPoint(dt.date(2025, 9, 30), Decimal("21778.6")),
    PriceSeriesPoint(dt.date(2025, 10, 1), Decimal("21851.3")),
    PriceSeriesPoint(dt.date(2025, 10, 2), Decimal("21951.79")),
    PriceSeriesPoint(dt.date(2025, 10, 3), Decimal("22094.89")),
    PriceSeriesPoint(dt.date(2025, 10, 7), Decimal("22163.23")),
    PriceSeriesPoint(dt.date(2025, 10, 8), Decimal("22097.99")),
    PriceSeriesPoint(dt.date(2025, 10, 9), Decimal("22174.74")),
    PriceSeriesPoint(dt.date(2025, 10, 10), Decimal("22318.72")),
    PriceSeriesPoint(dt.date(2025, 10, 13), Decimal("22321.08")),
    PriceSeriesPoint(dt.date(2025, 10, 14), Decimal("22372.57")),
    PriceSeriesPoint(dt.date(2025, 10, 15), Decimal("22292.28")),
    PriceSeriesPoint(dt.date(2025, 10, 16), Decimal("22416.15")),
    PriceSeriesPoint(dt.date(2025, 10, 17), Decimal("22633.80")),
    PriceSeriesPoint(dt.date(2025, 10, 21), Decimal("22783.62")),
    PriceSeriesPoint(dt.date(2025, 10, 22), Decimal("22791.07")),
    PriceSeriesPoint(dt.date(2025, 10, 23), Decimal("22850.95")),
    PriceSeriesPoint(dt.date(2025, 10, 24), Decimal("22812.52")),
    PriceSeriesPoint(dt.date(2025, 10, 27), Decimal("22788.79")),
    PriceSeriesPoint(dt.date(2025, 10, 28), Decimal("22689.22")),
    PriceSeriesPoint(dt.date(2025, 10, 29), Decimal("22777.12")),
    PriceSeriesPoint(dt.date(2025, 10, 30), Decimal("22839.53")),
]


class TestRealDataRegression:
    def test_comb_n0000_dimson_beta_against_this_modules_own_recorded_output(self):
        """Not a hand-derived expectation (a 4-parameter multiple
        regression over 47 points isn't hand-checkable) — this pins the
        real output down so a future change to the solver, the alignment
        logic or the Blume weights is caught rather than silently
        shipped. See the module docstring for the full-year comparison
        against CSE's own published beta for this same stock."""
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=50)
        assert not result.insufficient_data
        assert result.observations == 47
        assert result.dimson_beta == Decimal("1.196828")
        assert result.blume_adjusted_beta == Decimal("1.131218")

    def test_blume_adjustment_is_exactly_two_thirds_one_third(self):
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=50)
        expected = (Decimal(2) / 3) * result.dimson_beta + (Decimal(1) / 3)
        assert abs(result.blume_adjusted_beta - expected) < Decimal("0.000001")

    def test_the_three_coefficients_sum_to_the_dimson_beta(self):
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=50)
        total = result.lag_coefficient + result.contemporaneous_coefficient + result.lead_coefficient
        assert abs(total - result.dimson_beta) < Decimal("0.000001")

    def test_not_thin_trading_at_50_of_50_sessions(self):
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=50)
        assert not result.thin_trading


class TestThinTradingFlag:
    def test_below_45_of_60_sessions_is_flagged_thin(self):
        """§17.2's own threshold for when bottom-up sector beta should
        dominate — this module cannot supply the blend, but it can and
        must say when the spec would have wanted it."""
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=30)
        assert result.thin_trading

    def test_a_thin_stock_still_gets_a_number_not_a_refusal(self):
        """Throwing the estimate away entirely would be worse than
        flagging it — a caller building Ke needs SOME beta, clearly
        marked as one the spec would rather replace."""
        result = compute_dimson_beta(STOCK, MARKET, sessions_traded_in_window=30)
        assert not result.insufficient_data
        assert result.dimson_beta is not None


class TestInsufficientData:
    def test_below_the_minimum_observation_floor_refuses_to_compute(self):
        short_stock = STOCK[:10]
        short_market = MARKET[:10]
        result = compute_dimson_beta(short_stock, short_market, sessions_traded_in_window=10)
        assert result.insufficient_data
        assert result.dimson_beta is None
        assert "need at least" in result.reason

    def test_empty_series_is_insufficient_data_not_a_crash(self):
        result = compute_dimson_beta([], [], sessions_traded_in_window=0)
        assert result.insufficient_data
        assert result.observations == 0

    def test_no_date_overlap_at_all_is_insufficient_data(self):
        disjoint_market = [
            PriceSeriesPoint(dt.date(2030, 1, 1) + dt.timedelta(days=i), Decimal("100") + i)
            for i in range(40)
        ]
        result = compute_dimson_beta(STOCK[:40], disjoint_market, sessions_traded_in_window=40)
        assert result.insufficient_data


class TestDegenerateInputs:
    def test_a_zero_variance_market_series_does_not_crash(self):
        """A market return series that never moves makes the regression
        singular — must be reported, not raise an unhandled exception a
        caller three layers up has to guess the cause of."""
        flat_market = [
            PriceSeriesPoint(dt.date(2025, 1, 1) + dt.timedelta(days=i), Decimal("20000"))
            for i in range(40)
        ]
        moving_stock = [
            PriceSeriesPoint(dt.date(2025, 1, 1) + dt.timedelta(days=i), Decimal("100") + i)
            for i in range(40)
        ]
        result = compute_dimson_beta(moving_stock, flat_market, sessions_traded_in_window=40)
        assert result.insufficient_data
        assert result.dimson_beta is None

    def test_a_non_positive_close_does_not_produce_a_return(self):
        """Should never occur in real data, but a return computed against
        a zero or negative price is undefined, not merely large."""
        bad = [
            PriceSeriesPoint(dt.date(2025, 1, 1), Decimal("0")),
            PriceSeriesPoint(dt.date(2025, 1, 2), Decimal("100")),
        ]
        from app.domain.beta import daily_returns

        assert daily_returns(bad) == []
