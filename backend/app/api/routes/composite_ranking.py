"""
GET /composite-ranking — §38's universe-wide composite ranking.

READS A PRECOMPUTED SNAPSHOT, NEVER TRIGGERS THE PASS. The real §38
universe pass is ~70s (`app.domain.composite_ranking_view`'s own
docstring) — far too slow for a page load. The scheduled/manual
`recompute_composite_ranking` job runs it and freezes the result in
`composite_ranking_snapshots`; this endpoint only ever reads the newest
row, layering on the three things that are relative to "now" rather than
frozen: `computed_at` / `is_stale` (so staleness is visible per §8),
`insights` (a week-over-week diff against the ~7-day-old snapshot), and
each row's `score_series` (its `total_score` across recent snapshots, for
the sparkline).

COLD-START FALLBACK. A fresh install (or the test suite, which has no
worker) has no snapshot row yet — the endpoint then computes live once,
exactly as before, and reports `snapshot_available: false` so the screen
can say "computed live, no scheduled snapshot yet" rather than implying a
freshness it can't back up.

See `app.domain.composite_ranking_snapshot_view` for the single canonical
serialization shared with the job, and `docs/CSE_Alpha_Engine_Scoreboard_
Queue_Redesign.md` §2 for the why.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.composite_score import IntegrityOut, PillarScoreOut
from app.db.session import get_db
from app.domain.composite_ranking_snapshot_view import (
    build_insights,
    latest_snapshot,
    load_payload,
    recent_snapshots,
    score_series_by_ticker,
    serialize_ranking,
    snapshot_on_or_before,
)
from app.domain.composite_ranking_view import composite_ranking_for

router = APIRouter(prefix="/composite-ranking", tags=["composite-ranking"])

#: The Top Insights strip diffs the latest snapshot against the newest one
#: at least this many days older — "roughly last week" without demanding
#: an exact 7-day-old run existed.
INSIGHTS_LOOKBACK_DAYS = 7


class ScorePointOut(BaseModel):
    as_of: dt.date
    total_score: Decimal


class RankedCompositeOut(BaseModel):
    ticker: str
    name: str
    archetype: str | None
    cse_sector: str | None
    verdict: str
    decision_confidence: str
    total_score: Decimal | None
    pillars: list[PillarScoreOut]
    pillars_included: int
    weight_covered_pct: Decimal
    weight_used_pct: dict[str, Decimal]
    integrity: IntegrityOut
    blended_fair_value_per_share: Decimal | None
    current_price: Decimal | None
    discount_to_fair_value_pct: Decimal | None
    valuation_pillar_percentile: Decimal | None
    score_series: list[ScorePointOut]
    """This ticker's `total_score` across recent snapshots, oldest first —
    empty until at least one snapshot carries it, never zero-filled. Backs
    the per-row sparkline (redesign doc §1.3)."""
    warnings: list[str]


class CompositeRankingOut(BaseModel):
    as_of: dt.date
    computed_at: dt.datetime | None
    """When the underlying pass actually finished (UTC). `None` on the
    cold-start live path."""
    is_stale: bool
    """The snapshot is for a market date earlier than today — the market
    has moved since it was computed."""
    snapshot_available: bool
    """`False` → this response was computed live because no snapshot row
    exists yet."""
    insights: list[str]
    """Week-over-week factual sentences (verdict transitions, big score
    movers on well-corroborated rows, sector-average shifts). Empty when
    there is no ~week-old snapshot to diff against."""
    ranked: list[RankedCompositeOut]
    excluded: list[RankedCompositeOut]


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Same SQLite-round-trips-a-tz-column-as-naive fix as
    `app.api.routes.jobs._as_utc` — every `computed_at` is written
    UTC-aware, so a naive read is unambiguously UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)


def _attach_score_series(body: dict, series: dict[str, list[dict]]) -> None:
    for bucket in ("ranked", "excluded"):
        for row in body.get(bucket, []):
            row["score_series"] = series.get(row["ticker"], [])


@router.get("", response_model=CompositeRankingOut)
def composite_ranking(db: Session = Depends(get_db)) -> dict:
    snap = latest_snapshot(db)

    if snap is None:
        # Cold start: compute once, live, exactly as before.
        body = serialize_ranking(composite_ranking_for(db))
        body.update(
            computed_at=None,
            is_stale=False,
            snapshot_available=False,
            insights=[],
        )
        _attach_score_series(body, {})
        return body

    body = load_payload(snap)
    series = score_series_by_ticker(recent_snapshots(db))
    prior = snapshot_on_or_before(db, snap.as_of - dt.timedelta(days=INSIGHTS_LOOKBACK_DAYS))
    body.update(
        computed_at=_as_utc(snap.computed_at),
        is_stale=snap.as_of < dt.date.today(),
        snapshot_available=True,
        insights=build_insights(body, load_payload(prior) if prior is not None else None),
    )
    _attach_score_series(body, series)
    return body
