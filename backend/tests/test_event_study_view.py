"""§30 step 5 wired to real stored data — app.domain.event_study_view."""
from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from app.domain.event_study_view import event_study_for, policy_rate_change_dates
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily

TICKER = "COMB.N0000"
AS_OF = dt.date(2026, 8, 18)


def _seed_prices(db, ticker: str, returns_by_date: dict[dt.date, float], start_price: float = 100.0):
    now = dt.datetime.now(dt.timezone.utc)
    price = start_price
    rows = []
    for d in sorted(returns_by_date):
        price *= 1 + returns_by_date[d]
        rows.append(
            PriceDaily(
                ticker=ticker, date=d, close=Decimal(str(round(price, 4))),
                adj_factor=Decimal("1"), fetched_at=now,
            )
        )
    db.add_all(rows)
    db.commit()


def _seed_aspi(db, levels_by_date: dict[dt.date, float]):
    db.add_all(
        MacroSeries(
            series_id="cse.aspi", obs_date=d, first_available_date=d,
            value=Decimal(str(round(v, 4))), source="test",
        )
        for d, v in levels_by_date.items()
    )
    db.commit()


def _seed_policy_rate(db, changes: dict[dt.date, float]):
    db.add_all(
        MacroSeries(
            series_id="cbsl.policy_rate", obs_date=d, first_available_date=d,
            value=Decimal(str(v)), source="test",
        )
        for d, v in changes.items()
    )
    db.commit()


def _weekdays(start: dt.date, n: int) -> list[dt.date]:
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += dt.timedelta(days=1)
    return dates


class TestPolicyRateChangeDates:
    def test_only_real_changes_are_events_not_every_observation(self, db_session):
        dates = _weekdays(dt.date(2026, 1, 1), 5)
        _seed_policy_rate(db_session, {
            dates[0]: 8.5, dates[1]: 8.5, dates[2]: 8.75, dates[3]: 8.75, dates[4]: 9.0,
        })
        changes = policy_rate_change_dates(db_session, AS_OF, 400)
        assert changes == [dates[2], dates[4]]


class TestEventStudyFor:
    def test_no_price_data_gives_no_events(self, db_session):
        view = event_study_for(db_session, TICKER, AS_OF)
        assert view.trading_day_count == 0
        assert view.events == ()
        assert view.aggregate is None

    def test_unsupported_event_type_raises(self, db_session):
        try:
            event_study_for(db_session, TICKER, AS_OF, event_type="ccpi_release")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_real_market_model_recovers_a_known_injected_reaction(self, db_session):
        """A real, known abnormal reaction on ONE real policy rate change
        date, embedded in an otherwise pure market-model price series —
        end to end through real stored prices_daily/macro_series rows,
        real trading-day window alignment, and the real event-study
        fit, the same "real plumbing, known ground truth" proof as
        every other §30 view test this phase."""
        rng = random.Random(1)
        n = 200
        dates = _weekdays(dt.date(2025, 10, 1), n)
        alpha, beta = 0.0003, 1.1

        market_returns = {d: rng.gauss(0.0003, 0.01) for d in dates}
        asset_returns = {
            d: alpha + beta * market_returns[d] + rng.gauss(0, 0.004) for d in dates
        }
        # A real, known 4% abnormal jump on the event day itself.
        event_idx = 150
        event_date = dates[event_idx]
        asset_returns[event_date] += 0.04

        # Reconstruct real price/index LEVEL series from these returns
        # (what the view layer itself will independently re-derive
        # returns from).
        _seed_prices(db_session, TICKER, asset_returns)
        aspi_levels: dict[dt.date, float] = {}
        level = 10000.0
        for d in dates:
            level *= 1 + market_returns[d]
            aspi_levels[d] = level
        _seed_aspi(db_session, aspi_levels)
        # A real preceding observation is needed for a genuine "change"
        # to be detected — see TestPolicyRateChangeDates.
        _seed_policy_rate(db_session, {dates[0]: 9.0, event_date: 9.25})

        view = event_study_for(db_session, TICKER, AS_OF, estimation_length=120)
        assert view.trading_day_count >= 190
        assert len(view.events) == 1
        outcome = view.events[0]
        assert outcome.event_date == event_date
        assert outcome.result is not None
        assert outcome.skip_reason is None
        assert outcome.result.significant is True
        assert abs(outcome.result.cumulative_abnormal_return - Decimal("0.04")) < Decimal("0.03")

    def test_an_event_too_close_to_the_start_of_history_is_skipped_and_named(self, db_session):
        rng = random.Random(2)
        n = 200
        dates = _weekdays(dt.date(2025, 10, 1), n)
        market_returns = {d: rng.gauss(0.0003, 0.01) for d in dates}
        asset_returns = {d: 0.0003 + 1.0 * market_returns[d] + rng.gauss(0, 0.004) for d in dates}
        _seed_prices(db_session, TICKER, asset_returns)
        aspi_levels: dict[dt.date, float] = {}
        level = 10000.0
        for d in dates:
            level *= 1 + market_returns[d]
            aspi_levels[d] = level
        _seed_aspi(db_session, aspi_levels)
        # An event only 10 real trading days into the available history —
        # not enough room for a 120-day estimation window before it.
        _seed_policy_rate(db_session, {dates[0]: 9.0, dates[10]: 9.25})

        view = event_study_for(db_session, TICKER, AS_OF, estimation_length=120)
        assert len(view.events) == 1
        assert view.events[0].result is None
        assert "real trading days before the event window" in view.events[0].skip_reason
