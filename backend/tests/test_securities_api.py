"""Company list and company file endpoints."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.corporate_actions import CorporateAction
from app.models.corporate_actions import CorporateActionType as ActionType
from app.models.data_quality import DataAlert
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security

NOW = dt.datetime.now(dt.timezone.utc)


def _seed(db):
    db.add_all(
        [
            Security(ticker="JKH.N0000", name="JOHN KEELLS HOLDINGS PLC"),
            Security(ticker="AAF.N0000", name="ASIA ASSET FINANCE PLC"),
            Security(ticker="NOPRICE.N0000", name="NO PRICE YET PLC"),
        ]
    )
    db.add_all(
        [
            PriceDaily(
                ticker="JKH.N0000",
                date=dt.date(2026, 8, 13),
                close=Decimal("19.50"),
                fetched_at=NOW,
            ),
            PriceDaily(
                ticker="JKH.N0000",
                date=dt.date(2026, 8, 14),
                open=Decimal("20.00"),
                high=Decimal("20.10"),
                low=Decimal("19.90"),
                close=Decimal("20.00"),
                volume=1577810,
                turnover=Decimal("31559409.70"),
                fetched_at=NOW,
            ),
            PriceDaily(
                ticker="AAF.N0000",
                date=dt.date(2026, 8, 14),
                close=Decimal("49.10"),
                fetched_at=NOW,
            ),
        ]
    )
    db.commit()


def test_list_returns_every_security_including_those_without_prices(db_session, client):
    """§10 — the universe is complete by design. A company with no price
    row must still appear, with nulls, never silently dropped."""
    _seed(db_session)
    rows = client.get("/securities").json()

    tickers = {r["ticker"] for r in rows}
    assert tickers == {"JKH.N0000", "AAF.N0000", "NOPRICE.N0000"}

    no_price = next(r for r in rows if r["ticker"] == "NOPRICE.N0000")
    assert no_price["last_close"] is None  # null, never 0
    assert no_price["last_price_date"] is None


def test_list_uses_the_most_recent_price_not_an_arbitrary_one(db_session, client):
    _seed(db_session)
    rows = client.get("/securities").json()
    jkh = next(r for r in rows if r["ticker"] == "JKH.N0000")
    assert Decimal(jkh["last_close"]) == Decimal("20.00")  # the 14th, not the 13th
    assert jkh["last_price_date"] == "2026-08-14"


def test_list_includes_return_on_equity_for_the_screener(db_session, client):
    """The first ratio made screenable across the universe (ROADMAP.md's
    Phase 3 section) — computed in bulk, so most tickers (no ingested
    fundamentals at all) get null, honestly, not a guessed figure."""
    _seed(db_session)
    db_session.add_all(
        [
            Fundamental(
                ticker="JKH.N0000", period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line="net_income",
                value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker="JKH.N0000", period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            ),
        ]
    )
    db_session.commit()

    rows = client.get("/securities").json()
    jkh = next(r for r in rows if r["ticker"] == "JKH.N0000")
    assert Decimal(jkh["return_on_equity"]) == Decimal("0.2")
    assert jkh["return_on_equity_provenance"] == "R"

    no_fundamentals = next(r for r in rows if r["ticker"] == "AAF.N0000")
    assert no_fundamentals["return_on_equity"] is None
    assert no_fundamentals["return_on_equity_provenance"] is None


def test_list_search_matches_ticker_or_name_case_insensitively(db_session, client):
    _seed(db_session)
    by_ticker = client.get("/securities", params={"search": "jkh"}).json()
    assert [r["ticker"] for r in by_ticker] == ["JKH.N0000"]

    by_name = client.get("/securities", params={"search": "asia asset"}).json()
    assert [r["ticker"] for r in by_name] == ["AAF.N0000"]


def test_list_flags_quarantined_tickers(db_session, client):
    _seed(db_session)
    db_session.add(
        DataAlert(
            ticker="AAF.N0000",
            alert_type="reconciliation_mismatch",
            detail="test",
            raised_at=NOW,
            resolved=False,
        )
    )
    db_session.commit()

    rows = {r["ticker"]: r for r in client.get("/securities").json()}
    assert rows["AAF.N0000"]["quarantined"] is True
    assert rows["JKH.N0000"]["quarantined"] is False


def test_detail_returns_price_history_oldest_first(db_session, client):
    """Charts want ascending dates; the query fetches descending (to take
    the most recent N) and reverses."""
    _seed(db_session)
    detail = client.get("/securities/JKH.N0000").json()
    dates = [p["date"] for p in detail["price_history"]]
    assert dates == ["2026-08-13", "2026-08-14"]


def test_detail_includes_corporate_actions_and_fundamentals(db_session, client):
    _seed(db_session)
    db_session.add(
        CorporateAction(
            ticker="JKH.N0000",
            ex_date=dt.date(2026, 7, 24),
            type=ActionType.DIVIDEND_CASH,
            cash_amount=Decimal("0.70"),
            confirmed_by="analyst",
            confirmed_at=NOW,
        )
    )
    db_session.add(
        Fundamental(
            ticker="JKH.N0000",
            period_end=dt.date(2026, 3, 31),
            period_type="annual",
            first_available_date=dt.date(2026, 8, 14),
            version=1,
            statement_line="total_assets",
            value=Decimal("3807110"),
            provenance_tier=ProvenanceTier.AI_ASSISTED,
        )
    )
    db_session.commit()

    detail = client.get("/securities/JKH.N0000").json()
    assert len(detail["corporate_actions"]) == 1
    assert detail["corporate_actions"][0]["confirmed"] is True
    assert len(detail["fundamentals"]) == 1
    assert detail["fundamentals"][0]["provenance_tier"] == "A"
    assert detail["fundamentals"][0]["confirmed"] is False


def test_detail_never_exposes_a_score_or_fair_value(db_session, client):
    """The engines that would compute these don't exist yet. The UI spec
    forbids placeholder numbers outright, so the fields must be ABSENT,
    not null — a null is too easy to render as "0"."""
    _seed(db_session)
    detail = client.get("/securities/JKH.N0000").json()
    for forbidden in ("composite_score", "fair_value", "buy_below", "coverage_tier"):
        assert forbidden not in detail
    assert len(detail["not_yet_built"]) >= 4


def test_detail_unknown_ticker_404s(client):
    assert client.get("/securities/NOPE.X0000").status_code == 404
