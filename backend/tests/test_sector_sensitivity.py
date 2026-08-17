"""§33 sector sensitivity matrix — app.domain.sector_sensitivity."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.sector_sensitivity import (
    MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE,
    MIN_OBSERVATIONS_FOR_REGRESSION,
    MacroShockSeries,
    SectorReturns,
    compute_sector_sensitivity_matrix,
    estimate_sensitivity,
)


def _dates(n: int, start: dt.date = dt.date(2025, 1, 1)) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(n)]


class TestEstimateSensitivity:
    def test_none_below_minimum_observations(self):
        dates = _dates(MIN_OBSERVATIONS_FOR_REGRESSION - 1)
        returns = {d: Decimal("0.001") for d in dates}
        shock = MacroShockSeries("test", {d: Decimal("0.001") for d in dates})
        assert estimate_sensitivity(returns, shock) is None

    def test_none_when_shock_has_no_overlap_with_returns(self):
        returns = {d: Decimal("0.001") for d in _dates(50)}
        shock = MacroShockSeries("test", {d: Decimal("0.001") for d in _dates(50, dt.date(2030, 1, 1))})
        assert estimate_sensitivity(returns, shock) is None

    def test_none_when_shock_is_constant(self):
        dates = _dates(50)
        returns = {d: Decimal(str(random.Random(1).gauss(0, 0.01))) for d in dates}
        shock = MacroShockSeries("constant", {d: Decimal("0.05") for d in dates})
        assert estimate_sensitivity(returns, shock) is None

    def test_recovers_a_known_positive_sensitivity(self):
        rng = random.Random(3)
        dates = _dates(200)
        shock_values = {d: Decimal(str(rng.gauss(0, 0.01))) for d in dates}
        # True relationship: sector_return = 0.6 * shock + noise
        returns = {
            d: Decimal(str(0.6 * float(shock_values[d]) + rng.gauss(0, 0.003))) for d in dates
        }
        shock = MacroShockSeries("test shock", shock_values)

        result = estimate_sensitivity(returns, shock)
        assert result is not None
        assert result.observation_count == 200
        assert result.coefficient > Decimal("0.4")  # recovers something close to 0.6
        assert result.significant
        assert result.direction_label == "positive"

    def test_recovers_a_known_negative_sensitivity(self):
        rng = random.Random(4)
        dates = _dates(200)
        shock_values = {d: Decimal(str(rng.gauss(0, 0.01))) for d in dates}
        returns = {
            d: Decimal(str(-0.5 * float(shock_values[d]) + rng.gauss(0, 0.003))) for d in dates
        }
        shock = MacroShockSeries("test shock", shock_values)

        result = estimate_sensitivity(returns, shock)
        assert result is not None
        assert result.coefficient < Decimal("0")
        assert result.significant
        assert result.direction_label == "negative"

    def test_pure_noise_is_not_significant(self):
        rng = random.Random(5)
        dates = _dates(200)
        shock_values = {d: Decimal(str(rng.gauss(0, 0.01))) for d in dates}
        # No real relationship at all — independent draws.
        returns = {d: Decimal(str(rng.gauss(0, 0.01))) for d in dates}
        shock = MacroShockSeries("unrelated shock", shock_values)

        result = estimate_sensitivity(returns, shock)
        assert result is not None
        assert not result.significant
        assert result.direction_label == "not_significant"


class TestComputeSectorSensitivityMatrix:
    def test_thin_sectors_are_excluded_entirely(self):
        sector_returns = [
            SectorReturns("Banks", constituent_count=MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE, returns_by_date={}),
            SectorReturns("Thin Sector", constituent_count=MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE - 1, returns_by_date={}),
        ]
        rows = compute_sector_sensitivity_matrix(sector_returns, shocks=[])
        sectors = [r.sector for r in rows]
        assert "Thin Sector" not in sectors
        assert "Banks" in sectors

    def test_real_sector_row_carries_real_estimates(self):
        rng = random.Random(9)
        dates = _dates(100)
        shock_values = {d: Decimal(str(rng.gauss(0, 0.01))) for d in dates}
        returns = {d: Decimal(str(0.5 * float(shock_values[d]) + rng.gauss(0, 0.004))) for d in dates}
        shock = MacroShockSeries("rate shock", shock_values)

        sector_returns = [SectorReturns("Banks", constituent_count=5, returns_by_date=returns)]
        rows = compute_sector_sensitivity_matrix(sector_returns, shocks=[shock])
        assert len(rows) == 1
        assert rows[0].sector == "Banks"
        assert rows[0].constituent_count == 5
        assert len(rows[0].estimates) == 1
        assert rows[0].estimates[0].shock_name == "rate shock"

    def test_a_shock_with_no_overlap_is_simply_absent_from_estimates(self):
        sector_returns = [
            SectorReturns(
                "Banks", constituent_count=5,
                returns_by_date={d: Decimal("0.001") for d in _dates(50)},
            )
        ]
        no_overlap_shock = MacroShockSeries(
            "future shock", {d: Decimal("0.01") for d in _dates(50, dt.date(2040, 1, 1))}
        )
        rows = compute_sector_sensitivity_matrix(sector_returns, shocks=[no_overlap_shock])
        assert rows[0].estimates == ()
