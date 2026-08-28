"""§36 DB-wired — app.domain.carhart_view."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.carhart_regression import MIN_OBSERVATIONS_FOR_CARHART
from app.domain.carhart_view import carhart_certification_for, portfolio_carhart_for
from app.domain.factor_series import ALL_FACTOR_SERIES_IDS
from app.domain.cbsl_parsing import SERIES_TBILL_91D
from app.models.macro import MacroSeries
from app.models.prices import PriceDaily
from app.models.securities import Security

START = dt.date(2023, 1, 6)
N_WEEKS = MIN_OBSERVATIONS_FOR_CARHART + 10


def _seed_factor_series(db, seed_offset: int = 0) -> list[dt.date]:
    import random

    dates = [START + dt.timedelta(weeks=i) for i in range(N_WEEKS)]
    for fi, sid in enumerate(ALL_FACTOR_SERIES_IDS):
        rng = random.Random(seed_offset + fi)
        for d in dates:
            db.add(MacroSeries(
                series_id=sid, obs_date=d, first_available_date=d,
                value=Decimal(str(round(rng.gauss(0, 0.02), 8))), source="test",
            ))
    for d in dates:
        db.add(MacroSeries(
            series_id=SERIES_TBILL_91D, obs_date=d, first_available_date=d, value=Decimal("0.10"), source="test",
        ))
    db.commit()
    return dates


def _seed_ticker_prices(db, ticker: str, dates: list[dt.date], seed: int) -> None:
    import random

    now = dt.datetime.now(dt.timezone.utc)
    rng = random.Random(seed)
    db.add(Security(ticker=ticker, name=ticker))
    price = Decimal("100")
    for d in dates:
        price = price * (Decimal("1") + Decimal(str(round(rng.gauss(0.001, 0.02), 6))))
        db.add(PriceDaily(ticker=ticker, date=d, close=price, adj_factor=Decimal("1"), fetched_at=now))
    db.commit()


class TestCarhartCertificationFor:
    def test_no_factor_series_gives_a_warning_and_insufficient_data(self, db_session):
        view = carhart_certification_for(db_session, "NOPE.N0000", dt.date(2026, 1, 1))
        assert view.regression.insufficient_data is True
        assert any("factor series" in w for w in view.warnings)

    def test_a_real_seeded_ticker_produces_a_real_certification(self, db_session):
        dates = _seed_factor_series(db_session)
        _seed_ticker_prices(db_session, "T1.N0000", dates, seed=5)

        view = carhart_certification_for(db_session, "T1.N0000", dates[-1])
        assert view.factor_series_available_weeks == N_WEEKS
        assert view.regression.insufficient_data is False
        assert len(view.regression.betas) == 5
        assert view.regression.observation_count >= MIN_OBSERVATIONS_FOR_CARHART


class TestPortfolioCarhartFor:
    def test_equal_weighted_portfolio_of_two_tickers(self, db_session):
        dates = _seed_factor_series(db_session)
        _seed_ticker_prices(db_session, "T1.N0000", dates, seed=5)
        _seed_ticker_prices(db_session, "T2.N0000", dates, seed=6)

        view = portfolio_carhart_for(
            db_session, [("T1.N0000", Decimal("0.5")), ("T2.N0000", Decimal("0.5"))], dates[-1]
        )
        assert view.ticker is None
        assert view.regression.insufficient_data is False

    def test_zero_weight_sum_is_a_named_warning_not_a_crash(self, db_session):
        dates = _seed_factor_series(db_session)
        view = portfolio_carhart_for(db_session, [("T1.N0000", Decimal("0"))], dates[-1])
        assert any("weight" in w for w in view.warnings)
