"""
GET /composite-ranking — API-layer wiring for §38's universe-wide
composite ranking. The domain logic has its own test module
(test_composite_ranking_view.py); this exists to catch dict/enum
serialization bugs at the domain-to-API boundary, same role
test_composite_score_api.py plays for the single-ticker route.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.domain import valuation_view
from app.domain.composite_ranking_snapshot_view import write_snapshot
from app.domain.composite_ranking_view import CompositeRankingView, RankedComposite
from app.domain.composite_score import PILLAR_SPECS
from app.domain.composite_score_view import PillarScore, UNEVALUABLE_INTEGRITY
from app.models.enums import ProvenanceTier
from app.models.float_data import FloatData
from app.models.fundamentals import Fundamental
from app.models.prices import PriceDaily
from app.models.securities import Security
from tests.test_composite_ranking_view import _fake_ke

PERIOD_END = dt.date(2021, 12, 31)
FIRST_AVAILABLE = dt.date(2022, 3, 7)


def _seed_full_ticker(db, ticker, name, price, cse_sector="Banks"):
    now = dt.datetime.now(dt.timezone.utc)
    db.add(Security(ticker=ticker, name=name, archetype="bank", cse_sector=cse_sector))
    db.add_all(
        [
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="total_equity",
                value=Decimal(1000), provenance_tier=ProvenanceTier.REPORTED,
            ),
            Fundamental(
                ticker=ticker, period_end=PERIOD_END, period_type="annual",
                first_available_date=FIRST_AVAILABLE, version=1, statement_line="net_income",
                value=Decimal(200), provenance_tier=ProvenanceTier.REPORTED,
            ),
            FloatData(ticker=ticker, as_of=dt.date(2022, 1, 1), shares_issued=100),
            PriceDaily(ticker=ticker, date=PERIOD_END, close=price, volume=1_000_000, adj_factor=Decimal(1), fetched_at=now),
        ]
    )
    db.add_all(
        PriceDaily(
            ticker=ticker, date=dt.date(2022, 6, 1) - dt.timedelta(days=i), close=price,
            volume=1_000_000, adj_factor=Decimal(1), fetched_at=now,
        )
        for i in range(0, 60)
    )
    db.commit()


def test_empty_universe_returns_200_with_empty_lists(client):
    r = client.get("/composite-ranking")
    assert r.status_code == 200
    body = r.json()
    assert body["ranked"] == []
    assert body["excluded"] == []
    assert "as_of" in body


def test_ranked_rows_are_score_descending_and_fully_shaped(client, db_session, monkeypatch):
    monkeypatch.setattr(valuation_view, "cost_of_equity_for", _fake_ke())
    _seed_full_ticker(db_session, "CHEAP.N0000", "Cheap Bank", Decimal(5))
    _seed_full_ticker(db_session, "MID.N0000", "Mid Bank", Decimal(8))
    _seed_full_ticker(db_session, "DEAR.N0000", "Dear Bank", Decimal(10))

    r = client.get("/composite-ranking")
    assert r.status_code == 200
    body = r.json()

    tickers = [row["ticker"] for row in body["ranked"]]
    assert tickers == ["CHEAP.N0000", "MID.N0000", "DEAR.N0000"]

    scores = [row["total_score"] for row in body["ranked"]]
    assert all(s is not None for s in scores)
    assert scores == sorted(scores, key=lambda s: float(s), reverse=True)

    row = body["ranked"][0]
    assert {p["key"] for p in row["pillars"]} == {
        "valuation", "business_quality", "growth",
        "financial_strength", "macro_sector_fit", "timing_momentum", "risk",
    }
    assert row["integrity"]["evaluable"] is False
    valuation = next(p for p in row["pillars"] if p["key"] == "valuation")
    assert valuation["included"] is True
    assert row["discount_to_fair_value_pct"] is not None
    assert row["pillars_included"] == sum(1 for p in row["pillars"] if p["included"])
    assert 0 < float(row["weight_covered_pct"]) <= 100
    # New redesign fields, carried through from the same valuation pass.
    assert row["verdict"] and row["decision_confidence"] in {"high", "medium", "low"}
    assert row["cse_sector"] == "Banks"
    assert row["score_series"] == []  # cold start, no snapshot history


# --- snapshot-backed reads (redesign doc §2) --------------------------


def _fake_row(ticker, score, verdict="Buy"):
    pillars = tuple(
        PillarScore(s.key, s.label, s.weight_pct, Decimal("70"), True, None) for s in PILLAR_SPECS
    )
    return RankedComposite(
        ticker=ticker, name=f"{ticker} Ltd", archetype="bank", cse_sector="Banks",
        verdict=verdict, decision_confidence="high", total_score=Decimal(str(score)),
        pillars=pillars, pillars_included=7, weight_covered_pct=Decimal("100"),
        weight_used_pct={}, integrity=UNEVALUABLE_INTEGRITY,
        blended_fair_value_per_share=Decimal("100"), current_price=Decimal("80"),
        discount_to_fair_value_pct=Decimal("0.2"), valuation_pillar_percentile=Decimal("65"),
        warnings=(),
    )


def test_endpoint_serves_the_latest_snapshot_when_one_exists(client, db_session):
    today = dt.date.today()
    write_snapshot(
        db_session,
        CompositeRankingView(as_of=today, ranked=(_fake_row("AAA.N0000", 88),), excluded=()),
        computed_at=dt.datetime.now(dt.timezone.utc),
        duration_seconds=Decimal("70.0"),
    )

    body = client.get("/composite-ranking").json()

    assert body["snapshot_available"] is True
    assert body["computed_at"] is not None
    assert body["is_stale"] is False
    assert [r["ticker"] for r in body["ranked"]] == ["AAA.N0000"]


def test_endpoint_flags_a_snapshot_computed_for_an_earlier_date_as_stale(client, db_session):
    yesterday = dt.date.today() - dt.timedelta(days=1)
    write_snapshot(
        db_session,
        CompositeRankingView(as_of=yesterday, ranked=(_fake_row("AAA.N0000", 88),), excluded=()),
        computed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        duration_seconds=Decimal("70.0"),
    )

    body = client.get("/composite-ranking").json()
    assert body["snapshot_available"] is True
    assert body["is_stale"] is True


def test_endpoint_builds_week_over_week_insights_and_score_series_from_two_snapshots(client, db_session):
    old = dt.date.today() - dt.timedelta(days=8)
    write_snapshot(
        db_session,
        CompositeRankingView(as_of=old, ranked=(_fake_row("AAA.N0000", 60, verdict="Hold"),), excluded=()),
        computed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8),
        duration_seconds=Decimal("70.0"),
    )
    write_snapshot(
        db_session,
        CompositeRankingView(
            as_of=dt.date.today(), ranked=(_fake_row("AAA.N0000", 80, verdict="Buy"),), excluded=()
        ),
        computed_at=dt.datetime.now(dt.timezone.utc),
        duration_seconds=Decimal("70.0"),
    )

    body = client.get("/composite-ranking").json()

    assert any("AAA.N0000" in s and "Hold→Buy" in s for s in body["insights"])
    assert [p["total_score"] for p in body["ranked"][0]["score_series"]] == ["60", "80"]
