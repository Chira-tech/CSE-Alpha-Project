"""§37 DB-wired — app.domain.timing_battery_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.timing_battery_view import timing_battery_for
from app.models.securities import Security
from app.models.prices import PriceDaily

AS_OF = dt.date(2026, 6, 1)


def _seed_rising_ticker(db, ticker: str, weeks: int = 60) -> None:
    """Real daily prices, a genuine (if simple) uptrend with real
    day-to-day noise, so 52wk-high proximity/momentum aren't degenerate,
    plus real volume for the confirmation signal."""
    import random

    now = dt.datetime.now(dt.timezone.utc)
    rng = random.Random(3)
    db.add(Security(ticker=ticker, name=ticker))
    price = Decimal("50")
    d = AS_OF - dt.timedelta(weeks=weeks)
    while d <= AS_OF:
        if d.weekday() < 5:
            price = price * (Decimal("1") + Decimal(str(round(rng.gauss(0.002, 0.01), 6))))
            volume = 10_000 + rng.randint(-2000, 5000)
            db.add(PriceDaily(ticker=ticker, date=d, close=price, adj_factor=Decimal("1"), volume=volume, fetched_at=now))
        d += dt.timedelta(days=1)
    db.commit()


class TestTimingBatteryFor:
    def test_no_data_gives_no_signals_and_no_composite(self, db_session):
        result = timing_battery_for(db_session, "NOPE.N0000", AS_OF)
        assert result.composite_score is None
        assert all(not s.included for s in result.signals)

    def test_a_real_rising_ticker_produces_real_signals(self, db_session):
        _seed_rising_ticker(db_session, "T1.N0000", weeks=60)
        result = timing_battery_for(db_session, "T1.N0000", AS_OF)

        w52 = next(s for s in result.signals if s.key == "week52_high_proximity")
        assert w52.included is True
        assert Decimal(0) <= w52.value <= Decimal(100)

        mom = next(s for s in result.signals if s.key == "mom_12_2")
        assert mom.included is True
        # A real, consistent uptrend -> momentum score above the 50 midpoint.
        assert mom.value > Decimal(50)

        # residual_momentum needs a real Carhart regression this fixture
        # has no factor series for -> honestly excluded, not fabricated.
        rm = next(s for s in result.signals if s.key == "residual_momentum")
        assert rm.included is False
        assert "Carhart" in rm.reason

        assert result.composite_score is not None
        assert Decimal(0) <= result.composite_score <= Decimal(100)

    def test_crash_guard_flows_through_to_the_result(self, db_session):
        _seed_rising_ticker(db_session, "T2.N0000", weeks=60)
        result = timing_battery_for(db_session, "T2.N0000", AS_OF, crash_guard_active=True)
        assert result.crash_guard_active is True
        rev_1m_weight = next(s.weight_pct for s in result.signals if s.key == "rev_1m")
        assert rev_1m_weight == Decimal(65)  # CRASH_GUARD_REV_1M_WEIGHT

    def test_contrarian_inputs_are_wired_through(self, db_session):
        _seed_rising_ticker(db_session, "T3.N0000", weeks=60)
        result = timing_battery_for(
            db_session, "T3.N0000", AS_OF,
            business_quality_score=Decimal(80), integrity_red_flag=False, sector_macro_shock_active=False,
        )
        assert result.contrarian.business_quality_ge_70 is True
        assert result.contrarian.no_integrity_red_flag is True
        assert result.contrarian.no_active_sector_macro_shock is True
        assert result.contrarian.no_adverse_disclosure_60d == "unknown"
        assert result.contrarian.all_conditions_met is False  # condition 4 always blocks it
