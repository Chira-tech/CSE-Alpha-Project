"""§33 sector sensitivity matrix wired to real stored data —
app.domain.sector_sensitivity_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.sector_sensitivity import MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE
from app.domain.sector_sensitivity_view import (
    real_macro_shocks,
    sector_returns_for,
    sector_sensitivity_matrix_for,
)
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 17)


def _seed_security(db, ticker: str, sector: str):
    db.add(Security(ticker=ticker, name=f"{ticker} PLC", cse_sector=sector))
    db.commit()


def _seed_prices(db, ticker: str, closes: dict[dt.date, Decimal], adj_factor: Decimal = Decimal(1)):
    now = dt.datetime.now(dt.timezone.utc)
    db.add_all(
        PriceDaily(ticker=ticker, date=d, close=c, adj_factor=adj_factor, fetched_at=now)
        for d, c in closes.items()
    )
    db.commit()


def _seed_macro(db, series_id: str, obs: dict[dt.date, Decimal]):
    db.add_all(
        MacroSeries(series_id=series_id, obs_date=d, first_available_date=d, value=v, source="manual")
        for d, v in obs.items()
    )
    db.commit()


class TestSectorReturnsFor:
    def test_equal_weights_available_constituents_per_date(self, db_session):
        d1, d2, d3 = dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)
        _seed_prices(db_session, "A.N0000", {d1: Decimal(100), d2: Decimal(110), d3: Decimal(121)})
        # B is missing on d3 — that date should still use A alone, not be blank.
        _seed_prices(db_session, "B.N0000", {d1: Decimal(50), d2: Decimal(45)})

        result = sector_returns_for(db_session, "Banks", ["A.N0000", "B.N0000"], AS_OF, 400)
        assert result.constituent_count == 2
        # d2: A returns 0.10, B returns -0.10 -> equal-weighted average 0.0
        assert result.returns_by_date[d2] == Decimal("0")
        # d3: only A has a return (0.10) -> the sector return IS that value, not blank/zero.
        assert result.returns_by_date[d3] == Decimal("0.10")

    def test_adjusted_price_used_not_raw_close(self, db_session):
        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        # Raw close looks flat, but adj_factor jumps (e.g. a bonus issue) —
        # the real adjusted-price return should reflect that, not read as 0.
        now = dt.datetime.now(dt.timezone.utc)
        db_session.add_all(
            [
                PriceDaily(ticker="A.N0000", date=d1, close=Decimal(100), adj_factor=Decimal(1), fetched_at=now),
                PriceDaily(ticker="A.N0000", date=d2, close=Decimal(100), adj_factor=Decimal("1.1"), fetched_at=now),
            ]
        )
        db_session.commit()
        result = sector_returns_for(db_session, "Banks", ["A.N0000"], AS_OF, 400)
        assert result.returns_by_date[d2] == Decimal("0.1")


class TestRealMacroShocks:
    def test_step_function_shock_only_on_change_dates(self, db_session):
        d1, d2, d3 = dt.date(2026, 1, 1), dt.date(2026, 3, 1), dt.date(2026, 6, 1)
        _seed_macro(
            db_session, "cbsl.policy_rate",
            {d1: Decimal("0.0775"), d2: Decimal("0.0875"), d3: Decimal("0.0875")},
        )
        shocks = real_macro_shocks(db_session, AS_OF)
        policy_shock = next(s for s in shocks if s.name == "Policy rate change")
        # Changed d1->d2 (+0.01), unchanged d2->d3 (0.0) — both are real
        # observations, both present (a zero shock IS a real data point
        # here, since d3 genuinely has an observation, unlike a day with
        # no observation at all, which is simply absent).
        assert policy_shock.values_by_date[d2] == Decimal("0.01")
        assert policy_shock.values_by_date[d3] == Decimal("0")
        assert d1 not in policy_shock.values_by_date  # no prior observation to diff against

    def test_pct_change_shock_for_currency(self, db_session):
        d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
        _seed_macro(db_session, "cbsl.usd_lkr_tt_buying", {d1: Decimal(300), d2: Decimal(309)})
        shocks = real_macro_shocks(db_session, AS_OF)
        fx_shock = next(s for s in shocks if s.name == "LKR/USD % change")
        assert fx_shock.values_by_date[d2] == Decimal("0.03")


class TestSectorSensitivityMatrixFor:
    def test_no_sectors_at_all(self, db_session):
        view = sector_sensitivity_matrix_for(db_session, AS_OF)
        assert view.rows == ()
        assert any("No securities have a cse_sector" in w for w in view.warnings)

    def test_thin_sector_is_named_not_silently_dropped(self, db_session):
        _seed_security(db_session, "A.N0000", "Banks")
        _seed_security(db_session, "B.N0000", "Banks")  # only 2 -- below MIN_CONSTITUENTS
        view = sector_sensitivity_matrix_for(db_session, AS_OF)
        assert ("Banks", 2) in view.thin_sectors
        assert view.rows == ()

    def test_real_sector_with_enough_history_produces_a_real_row(self, db_session):
        rng = random.Random(21)
        tickers = ["A.N0000", "B.N0000", "C.N0000"]
        assert len(tickers) >= MIN_CONSTITUENTS_FOR_SECTOR_ESTIMATE
        for t in tickers:
            _seed_security(db_session, t, "Banks")

        # Build a policy-rate shock series with real changes, and price
        # series for each ticker that respond negatively to rate rises
        # (a real, coded-in relationship, same pattern test_sector_
        # sensitivity.py's pure-module tests already use).
        base = dt.date(2025, 1, 1)
        rate = Decimal("0.08")
        rate_obs: dict[dt.date, Decimal] = {}
        prices: dict[str, dict[dt.date, Decimal]] = {t: {} for t in tickers}
        price_levels = {t: Decimal(100) for t in tickers}
        for i in range(150):
            date = base + dt.timedelta(days=i)
            if i % 20 == 0:
                rate = rate + Decimal(str(rng.choice([-0.005, 0.005])))
            rate_obs[date] = rate
            shock = float(rate_obs.get(date) - rate_obs.get(date - dt.timedelta(days=1), rate))
            for t in tickers:
                daily_return = -0.5 * shock + rng.gauss(0, 0.004)
                price_levels[t] = price_levels[t] * Decimal(str(1 + daily_return))
                prices[t][date] = price_levels[t]

        _seed_macro(db_session, "cbsl.policy_rate", rate_obs)
        for t in tickers:
            _seed_prices(db_session, t, prices[t])

        as_of = base + dt.timedelta(days=160)
        view = sector_sensitivity_matrix_for(db_session, as_of)
        assert view.thin_sectors == ()
        assert len(view.rows) == 1
        row = view.rows[0]
        assert row.sector == "Banks"
        assert row.constituent_count == 3
        # A real estimate for the policy-rate shock should exist, given
        # 150 days of real overlapping history — whether it reaches
        # significance depends on the noise draw, so only existence and
        # correct shock naming are asserted, not a specific direction.
        assert any(e.shock_name == "Policy rate change" for e in row.estimates)
