"""
R1 T4.6.4's sector drill-down: real market cap, ordered largest-first,
never fabricating a percentage or a fair-value gap this system can't
actually compute for a ticker.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain.market_cap_view import bulk_market_cap_for
from app.domain.sector_drilldown_view import sector_drilldown_for
from app.models.float_data import FloatData
from app.models.prices import PriceDaily
from app.models.securities import Security

AS_OF = dt.date(2026, 8, 20)


def _seed_company(db, ticker, name, sector, shares=None, price=None, delisted=False):
    db.add(
        Security(
            ticker=ticker, name=name, cse_sector=sector,
            delisting_date=dt.date(2020, 1, 1) if delisted else None,
        )
    )
    if shares is not None:
        db.add(FloatData(ticker=ticker, as_of=AS_OF, shares_issued=shares))
    if price is not None:
        db.add(PriceDaily(ticker=ticker, date=AS_OF, close=Decimal(str(price)), fetched_at=dt.datetime(2026, 8, 20, 10, 0)))


def test_bulk_market_cap_matches_the_per_ticker_function_for_a_full_pair(db_session):
    _seed_company(db_session, "AAA.N0000", "Company A", "Banks", shares=1000, price="10.00")
    db_session.commit()

    caps = bulk_market_cap_for(db_session, ("AAA.N0000",), AS_OF)
    assert caps["AAA.N0000"] == Decimal("10000.00")


def test_bulk_market_cap_is_none_for_a_ticker_missing_either_input(db_session):
    _seed_company(db_session, "AAA.N0000", "Company A", "Banks", shares=1000, price=None)
    db_session.commit()

    caps = bulk_market_cap_for(db_session, ("AAA.N0000",), AS_OF)
    assert caps["AAA.N0000"] is None


def test_sector_drilldown_orders_largest_market_cap_first_and_computes_real_pct_of_sector(db_session):
    _seed_company(db_session, "BIG.N0000", "Big Co", "Banks", shares=1000, price="100.00")   # cap 100,000
    _seed_company(db_session, "SML.N0000", "Small Co", "Banks", shares=1000, price="20.00")  # cap 20,000
    db_session.commit()

    view = sector_drilldown_for(db_session, "Banks", as_of=AS_OF)
    assert view is not None
    assert [c.ticker for c in view.companies] == ["BIG.N0000", "SML.N0000"]
    assert view.total_market_cap == Decimal("120000.00")
    big = next(c for c in view.companies if c.ticker == "BIG.N0000")
    assert round(big.pct_of_sector, 4) == round(Decimal("100000.00") / Decimal("120000.00"), 4)
    # Neither ticker has any fundamentals seeded, so neither is in the
    # confirmed set `opportunity_ranking_for` ranks or excludes — the
    # real, honest reason, not a fabricated gap.
    assert big.fair_value_gap_pct is None
    assert big.gap_reason == "No confirmed fundamentals for this ticker."


def test_sector_drilldown_excludes_a_missing_market_cap_from_the_pct_denominator(db_session):
    _seed_company(db_session, "KNOWN.N0000", "Known Co", "Banks", shares=1000, price="50.00")
    _seed_company(db_session, "UNKNOWN.N0000", "Unknown Co", "Banks", shares=None, price=None)
    db_session.commit()

    view = sector_drilldown_for(db_session, "Banks", as_of=AS_OF)
    assert view.excluded_from_market_cap_pct == 1
    known = next(c for c in view.companies if c.ticker == "KNOWN.N0000")
    unknown = next(c for c in view.companies if c.ticker == "UNKNOWN.N0000")
    assert known.pct_of_sector == Decimal(1)
    assert unknown.market_cap is None
    assert unknown.pct_of_sector is None


def test_sector_drilldown_excludes_delisted_constituents(db_session):
    _seed_company(db_session, "LIVE.N0000", "Live Co", "Banks", shares=1000, price="10.00")
    _seed_company(db_session, "DEAD.N0000", "Dead Co", "Banks", shares=1000, price="10.00", delisted=True)
    db_session.commit()

    view = sector_drilldown_for(db_session, "Banks", as_of=AS_OF)
    assert [c.ticker for c in view.companies] == ["LIVE.N0000"]


def test_sector_drilldown_returns_none_for_a_sector_with_no_real_constituents(db_session):
    assert sector_drilldown_for(db_session, "Nonexistent Sector", as_of=AS_OF) is None
