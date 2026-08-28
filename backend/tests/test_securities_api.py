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
    # Only one ticker in the whole seed has a computable ROE at all, so
    # there is nothing to rank it against — no fabricated percentile.
    assert jkh["return_on_equity_sector_percentile"] is None


def test_list_ranks_roe_sector_percentile_once_enough_peers_exist(db_session, client):
    """§12's sector-relative percentile on the screener column — real
    once MIN_CONSTITUENTS_FOR_SECTOR_PERCENTILE peers share a sector."""
    _seed(db_session)
    db_session.query(Security).filter(Security.ticker == "JKH.N0000").update({"cse_sector": "Banks"})
    db_session.query(Security).filter(Security.ticker == "AAF.N0000").update({"cse_sector": "Banks"})
    db_session.add(Security(ticker="THIRD.N0000", name="THIRD BANK PLC", cse_sector="Banks"))
    db_session.add_all(
        [
            Fundamental(
                ticker=t, period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line=line,
                value=Decimal(value), provenance_tier=ProvenanceTier.REPORTED,
            )
            for t, line, value in [
                ("JKH.N0000", "net_income", 200), ("JKH.N0000", "total_equity", 1000),  # ROE 20%
                ("AAF.N0000", "net_income", 100), ("AAF.N0000", "total_equity", 1000),  # ROE 10%
                ("THIRD.N0000", "net_income", 300), ("THIRD.N0000", "total_equity", 1000),  # ROE 30%
            ]
        ]
    )
    db_session.commit()

    rows = {r["ticker"]: r for r in client.get("/securities").json()}
    assert Decimal(rows["THIRD.N0000"]["return_on_equity_sector_percentile"]) == Decimal(100)
    assert Decimal(rows["AAF.N0000"]["return_on_equity_sector_percentile"]) == Decimal(0)
    assert Decimal(rows["JKH.N0000"]["return_on_equity_sector_percentile"]) == Decimal(50)


def test_detail_includes_ratio_percentiles(db_session, client):
    _seed(db_session)
    db_session.query(Security).filter(Security.ticker == "JKH.N0000").update({"cse_sector": "Banks"})
    db_session.query(Security).filter(Security.ticker == "AAF.N0000").update({"cse_sector": "Banks"})
    db_session.add(Security(ticker="THIRD.N0000", name="THIRD BANK PLC", cse_sector="Banks"))
    db_session.add_all(
        [
            Fundamental(
                ticker=t, period_end=dt.date(2025, 12, 31), period_type="annual",
                first_available_date=dt.date(2026, 3, 1), version=1, statement_line=line,
                value=Decimal(value), provenance_tier=ProvenanceTier.REPORTED,
            )
            for t, line, value in [
                ("JKH.N0000", "net_income", 200), ("JKH.N0000", "total_equity", 1000),
                ("AAF.N0000", "net_income", 100), ("AAF.N0000", "total_equity", 1000),
                ("THIRD.N0000", "net_income", 300), ("THIRD.N0000", "total_equity", 1000),
            ]
        ]
    )
    db_session.commit()

    detail = client.get("/securities/JKH.N0000").json()
    roe_pct = next(p for p in detail["ratio_percentiles"] if p["ratio_key"] == "return_on_equity")
    assert Decimal(roe_pct["percentile"]) == Decimal(50)
    assert roe_pct["group_label"] == "Banks"
    assert roe_pct["group_size"] == 3
    assert roe_pct["used_wider_sector"] is False


def test_detail_includes_ratio_series_for_the_company_file_ratio_card_path(db_session, client):
    """R1 T4.3.1: the ratio card grid draws a real numeric path where >=3
    periods exist — this is the raw `(period_end, value)` history that
    path is built from, oldest first."""
    _seed(db_session)
    db_session.add_all(
        [
            Fundamental(
                ticker="JKH.N0000", period_end=period_end, period_type="annual",
                first_available_date=period_end, version=1, statement_line=line,
                value=Decimal(value), provenance_tier=ProvenanceTier.REPORTED,
            )
            for period_end, line, value in [
                (dt.date(2023, 12, 31), "net_income", 100), (dt.date(2023, 12, 31), "total_equity", 1000),
                (dt.date(2024, 12, 31), "net_income", 140), (dt.date(2024, 12, 31), "total_equity", 1000),
                (dt.date(2025, 12, 31), "net_income", 200), (dt.date(2025, 12, 31), "total_equity", 1000),
            ]
        ]
    )
    db_session.commit()

    detail = client.get("/securities/JKH.N0000").json()
    roe_series = detail["ratio_series"]["return_on_equity"]
    assert [p["period_end"] for p in roe_series] == ["2023-12-31", "2024-12-31", "2025-12-31"]
    assert Decimal(roe_series[0]["value"]) == Decimal("0.1")
    assert Decimal(roe_series[-1]["value"]) == Decimal("0.2")


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
    """`fair_value`/`buy_below`/`coverage_tier` genuinely have no engine
    behind them on THIS response yet (`coverage_tier`'s engine exists but
    isn't wired to real data anywhere — see `_NOT_YET_BUILT`). `composite_
    score` DOES have a real, live engine now, just on its own endpoint
    (`GET /composite-score/{ticker}`) rather than flattened onto
    `SecurityDetail` — so its absence here is a deliberate response-shape
    choice, not a "doesn't exist" claim. The UI spec forbids placeholder
    numbers outright either way, so any of these fields must be ABSENT
    from this response, not null — a null is too easy to render as "0"."""
    _seed(db_session)
    detail = client.get("/securities/JKH.N0000").json()
    for forbidden in ("composite_score", "fair_value", "buy_below", "coverage_tier"):
        assert forbidden not in detail
    assert len(detail["not_yet_built"]) >= 3


def test_detail_unknown_ticker_404s(client):
    assert client.get("/securities/NOPE.X0000").status_code == 404


def _seed_seven_days_of_jkh(db_session):
    """Seven daily rows so a 5-per-page default leaves a real second page,
    without seeding anywhere near a real year of history."""
    if db_session.get(Security, "JKH.N0000") is None:
        db_session.add(Security(ticker="JKH.N0000", name="JOHN KEELLS HOLDINGS PLC"))
    db_session.add_all(
        [
            PriceDaily(
                ticker="JKH.N0000",
                date=dt.date(2026, 8, 3) + dt.timedelta(days=i),
                close=Decimal("10.00") + i,
                fetched_at=NOW,
            )
            for i in range(7)
        ]
    )
    db_session.commit()


def test_prices_endpoint_defaults_to_five_most_recent_descending(db_session, client):
    _seed_seven_days_of_jkh(db_session)
    page = client.get("/securities/JKH.N0000/prices").json()
    assert page["limit"] == 5
    assert page["offset"] == 0
    assert page["total"] == 7
    assert len(page["items"]) == 5
    assert [p["date"] for p in page["items"]] == [
        "2026-08-09", "2026-08-08", "2026-08-07", "2026-08-06", "2026-08-05",
    ]


def test_prices_endpoint_second_page_via_limit_and_offset(db_session, client):
    _seed_seven_days_of_jkh(db_session)
    page = client.get("/securities/JKH.N0000/prices", params={"limit": 5, "offset": 5}).json()
    assert page["total"] == 7
    assert [p["date"] for p in page["items"]] == ["2026-08-04", "2026-08-03"]


def test_prices_endpoint_page_size_options(db_session, client):
    _seed_seven_days_of_jkh(db_session)
    page = client.get("/securities/JKH.N0000/prices", params={"limit": 25}).json()
    assert page["total"] == 7
    assert len(page["items"]) == 7  # fewer rows exist than the page size


def test_prices_endpoint_rejects_page_sizes_outside_the_ui_options(client):
    assert client.get("/securities/JKH.N0000/prices", params={"limit": 51}).status_code == 422
    assert client.get("/securities/JKH.N0000/prices", params={"limit": 0}).status_code == 422


def test_prices_endpoint_unknown_ticker_404s(client):
    assert client.get("/securities/NOPE.X0000/prices").status_code == 404


def test_list_includes_real_price_change_windows(db_session, client):
    """R1 T4.4.1 — real session-count price appreciation, not calendar
    days. Seeds real closes at known session offsets from today and
    checks the computed % change against hand math."""
    db_session.add(Security(ticker="TREND.N0000", name="Trend PLC"))
    today = dt.date.today()
    # 6 real sessions: today, and 5/10/... days back is approximated by
    # just seeding one row per calendar day for the last 12 days — the
    # function counts SESSIONS (stored rows), not calendar gaps, so this
    # gives an exact, hand-computable 5-session-ago reference.
    closes = {}
    for i in range(12):
        d = today - dt.timedelta(days=i)
        close = Decimal(100 + i)  # oldest ago -> smallest date -> largest i -> close = 100+i
        closes[d] = close
        db_session.add(PriceDaily(ticker="TREND.N0000", date=d, close=close, fetched_at=NOW))
    db_session.commit()

    body = {r["ticker"]: r for r in client.get("/securities").json()}
    row = body["TREND.N0000"]
    latest_close = closes[today]  # 100
    five_sessions_ago_close = closes[today - dt.timedelta(days=5)]  # 105
    expected_5d = float((latest_close - five_sessions_ago_close) / five_sessions_ago_close * 100)
    assert row["price_change_5d_pct"] is not None
    assert abs(float(row["price_change_5d_pct"]) - expected_5d) < 0.01
    # Only 12 sessions of real history exist — a 30-session window must
    # be None, never a change computed from fewer real sessions than claimed.
    assert row["price_change_30d_pct"] is None
