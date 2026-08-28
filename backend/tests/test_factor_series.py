"""§35.1's factor construction pure arithmetic — app.domain.factor_series."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.factor_series import MarketWeightedInput, mom_style_value, value_weighted_return


class TestValueWeightedReturn:
    def test_none_below_minimum_tickers(self):
        constituents = [
            MarketWeightedInput(ticker=f"T{i}", market_cap=Decimal(1000), period_return=Decimal("0.01"))
            for i in range(11)
        ]
        assert value_weighted_return(constituents) is None

    def test_none_when_total_market_cap_not_positive(self):
        constituents = [
            MarketWeightedInput(ticker=f"T{i}", market_cap=Decimal(0), period_return=Decimal("0.01"))
            for i in range(12)
        ]
        assert value_weighted_return(constituents) is None

    def test_a_known_weighted_average(self):
        """Two tickers, hand-computed: cap-weighted average of a +10%
        and a -5% return, weighted 3:1 by market cap, is exactly 6.25%."""
        constituents = [
            MarketWeightedInput(ticker="BIG", market_cap=Decimal(750), period_return=Decimal("0.10")),
            MarketWeightedInput(ticker="SMALL", market_cap=Decimal(250), period_return=Decimal("-0.05")),
        ] + [
            # pad to MIN_TICKERS_FOR_MKT with zero-cap-weight-irrelevant... no:
            # market cap must stay positive per-row for a meaningful test,
            # so pad with negligible-but-real caps that don't move the average.
            MarketWeightedInput(ticker=f"T{i}", market_cap=Decimal("0.0001"), period_return=Decimal("0.10"))
            for i in range(10)
        ]
        result = value_weighted_return(constituents)
        assert result is not None
        # Dominated by the two real large-cap constituents; hand-computed
        # weighted average of 0.10 and -0.05 at 750:250 is 0.0625, with a
        # negligible pull from the ten near-zero-cap padding tickers.
        assert abs(result - Decimal("0.0625")) < Decimal("0.0001")


class TestMomStyleValue:
    def _closes(self, pairs: list[tuple[str, str]]) -> list[tuple[dt.date, Decimal]]:
        return [(dt.date.fromisoformat(d), Decimal(c)) for d, c in pairs]

    def test_none_with_no_price_history_before_the_window(self):
        closes = self._closes([("2026-08-01", "100")])
        result = mom_style_value(closes, dt.date(2026, 8, 1), skip_weeks=4, lookback_weeks=52)
        assert result is None  # no observation 52 weeks before 2026-08-01

    def test_hand_computed_cumulative_return_skipping_the_recent_window(self):
        """52 weeks before 2026-08-07 is 2025-08-08 (close=100); 4 weeks
        before is 2026-07-10 (close=120). Cumulative return over that
        window is exactly 20%, and the price points inside the skipped
        4-week window (150) must NOT affect the result."""
        closes = self._closes(
            [
                ("2025-08-08", "100"),
                ("2026-07-10", "120"),
                ("2026-07-24", "150"),  # inside the skipped window — must be ignored
                ("2026-08-07", "999"),  # as_of itself — must be ignored (only the endpoint dates matter)
            ]
        )
        result = mom_style_value(closes, dt.date(2026, 8, 7), skip_weeks=4, lookback_weeks=52)
        assert result is not None
        assert abs(result - Decimal("0.20")) < Decimal("0.0001")

    def test_none_when_start_close_is_not_positive(self):
        closes = self._closes([("2025-08-08", "0"), ("2026-07-10", "120")])
        result = mom_style_value(closes, dt.date(2026, 8, 7), skip_weeks=4, lookback_weeks=52)
        assert result is None

    def test_uses_most_recent_observation_on_or_before_each_endpoint(self):
        """No exact observation on the target dates — falls back to the
        most recent real one before each, same convention as
        cumulative_adjusted_return."""
        closes = self._closes([("2025-08-01", "100"), ("2026-07-01", "110")])
        result = mom_style_value(closes, dt.date(2026, 8, 7), skip_weeks=4, lookback_weeks=52)
        assert result is not None
        assert abs(result - Decimal("0.10")) < Decimal("0.0001")
