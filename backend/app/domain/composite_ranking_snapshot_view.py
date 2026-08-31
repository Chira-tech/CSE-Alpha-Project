"""
Read/write glue for `app.models.composite_ranking_snapshot.
CompositeRankingSnapshot` — plus the ONE canonical serialization of a
`CompositeRankingView` into the exact JSON body `GET /composite-ranking`
returns, so the stored snapshot and a live-computed response can never
drift in shape.

WHY SERIALIZATION LIVES HERE, NOT IN THE ROUTE. The scheduled/manual
`recompute_composite_ranking` job (`app.jobs.runner`) has to write the
same body the API serves, and a job module importing an API route module
would invert this codebase's layering (nothing under `app/jobs` or
`app/domain` imports `app/api`). So the domain owns the mapping; the
route's Pydantic `CompositeRankingOut` is kept purely as the response
schema and is fed the dict this module produces.

The three read-time-only fields — `computed_at`, `is_stale`,
`snapshot_available`, `insights`, and each row's `score_series` — are NOT
part of the stored payload: staleness is relative to "now", and both
`insights` and `score_series` are diffs BETWEEN snapshots, assembled by
the route from several rows of this table. The stored payload is just one
run's ranking.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.composite_ranking_view import CompositeRankingView, RankedComposite
from app.domain.composite_score_view import PillarScore
from app.models.composite_ranking_snapshot import CompositeRankingSnapshot

#: How many recent snapshots feed each row's score-over-time sparkline
#: (`RankedCompositeOut.score_series`). Six scheduled runs ≈ a working
#: week and a bit — enough to see "newly attractive" vs "long-standing"
#: without turning the sparkline into noise.
SCORE_SERIES_DEPTH = 6

#: A score move smaller than this (in points, 0-100) is not worth a
#: headline in the Top Insights strip — it's inside the noise of a
#: universe re-rank where one peer's new filing shifts everyone's
#: percentile slightly.
INSIGHT_MIN_SCORE_MOVE = Decimal(4)

#: Don't headline a score move for a row scored from a thin pillar basis —
#: a 2-pillar score swinging 10 points is far less meaningful than a
#: 6-pillar one moving 4. Same discipline as the board's own
#: `pillars_included` disclosure.
INSIGHT_MIN_PILLARS = 5

#: A verdict-transition sentence names at most this many tickers, then
#: "and N more" — enough to scan, not a wall of text on a heavy week.
INSIGHT_MAX_VERDICT_NAMES = 10


# --------------------------------------------------------------------------
# Canonical serialization: CompositeRankingView -> plain JSON-able dict
# --------------------------------------------------------------------------
def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _pillar_dict(p: PillarScore) -> dict:
    return {
        "key": p.key,
        "label": p.label,
        "weight_pct": _dec(p.weight_pct),
        "score": _dec(p.score),
        "included": p.included,
        "reason": p.reason,
    }


def _row_dict(r: RankedComposite) -> dict:
    return {
        "ticker": r.ticker,
        "name": r.name,
        "archetype": r.archetype,
        "cse_sector": r.cse_sector,
        "verdict": r.verdict,
        "decision_confidence": r.decision_confidence,
        "total_score": _dec(r.total_score),
        "pillars": [_pillar_dict(p) for p in r.pillars],
        "pillars_included": r.pillars_included,
        "weight_covered_pct": _dec(r.weight_covered_pct),
        "weight_used_pct": {k: _dec(v) for k, v in r.weight_used_pct.items()},
        "integrity": {
            "evaluable": r.integrity.evaluable,
            "vetoed": r.integrity.vetoed,
            "reason": r.integrity.reason,
        },
        "blended_fair_value_per_share": _dec(r.blended_fair_value_per_share),
        "current_price": _dec(r.current_price),
        "discount_to_fair_value_pct": _dec(r.discount_to_fair_value_pct),
        "valuation_pillar_percentile": _dec(r.valuation_pillar_percentile),
        "warnings": list(r.warnings),
    }


def serialize_ranking(view: CompositeRankingView) -> dict:
    """The exact `{as_of, ranked, excluded}` body the API serves, minus
    the cross-snapshot fields the route layers on. Used both to build the
    live response and to freeze a snapshot payload."""
    return {
        "as_of": view.as_of.isoformat(),
        "ranked": [_row_dict(r) for r in view.ranked],
        "excluded": [_row_dict(r) for r in view.excluded],
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def write_snapshot(
    db: Session,
    view: CompositeRankingView,
    *,
    computed_at: dt.datetime,
    duration_seconds: Decimal,
) -> CompositeRankingSnapshot:
    """Freeze one completed run. One row per run — never an update; dated
    history is what makes `build_insights` and `score_series_by_ticker`
    real diffs (see the model's own docstring)."""
    payload = serialize_ranking(view)
    row = CompositeRankingSnapshot(
        as_of=view.as_of,
        computed_at=computed_at,
        duration_seconds=duration_seconds,
        ranked_count=len(view.ranked),
        excluded_count=len(view.excluded),
        payload=json.dumps(payload),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_snapshot(db: Session) -> CompositeRankingSnapshot | None:
    return db.scalar(
        select(CompositeRankingSnapshot).order_by(CompositeRankingSnapshot.computed_at.desc()).limit(1)
    )


def recent_snapshots(db: Session, limit: int = SCORE_SERIES_DEPTH) -> list[CompositeRankingSnapshot]:
    """Newest first."""
    return list(
        db.scalars(
            select(CompositeRankingSnapshot)
            .order_by(CompositeRankingSnapshot.computed_at.desc())
            .limit(limit)
        ).all()
    )


def snapshot_on_or_before(db: Session, cutoff: dt.date) -> CompositeRankingSnapshot | None:
    """The newest snapshot whose `as_of` is on or before `cutoff` — the
    "roughly a week ago" reference the Top Insights strip diffs against.
    `None` when this install has no snapshot that old yet, in which case
    the strip honestly shows nothing rather than a fabricated delta."""
    return db.scalar(
        select(CompositeRankingSnapshot)
        .where(CompositeRankingSnapshot.as_of <= cutoff)
        .order_by(CompositeRankingSnapshot.as_of.desc(), CompositeRankingSnapshot.computed_at.desc())
        .limit(1)
    )


def load_payload(snapshot: CompositeRankingSnapshot) -> dict:
    return json.loads(snapshot.payload)


# --------------------------------------------------------------------------
# Cross-snapshot reads
# --------------------------------------------------------------------------
def _score(row: dict) -> Decimal | None:
    raw = row.get("total_score")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def score_series_by_ticker(
    snapshots: list[CompositeRankingSnapshot],
) -> dict[str, list[dict]]:
    """`{ticker: [{"as_of": iso, "total_score": "83.1"}, ...]}` oldest
    first, from the given snapshots (pass `recent_snapshots(db)`). Only
    ranked rows contribute a point; a run where the ticker wasn't ranked
    simply has no point for that date, never a zero."""
    series: dict[str, list[dict]] = defaultdict(list)
    for snap in sorted(snapshots, key=lambda s: s.computed_at):
        payload = load_payload(snap)
        for row in payload.get("ranked", []):
            if row.get("total_score") is None:
                continue
            series[row["ticker"]].append(
                {"as_of": payload["as_of"], "total_score": row["total_score"]}
            )
    return dict(series)


def build_insights(latest_payload: dict, prior_payload: dict | None) -> list[str]:
    """Plain factual week-over-week sentences, each backed by a real delta
    between two real snapshots. Returns `[]` when there is no prior
    snapshot to diff against — the strip then shows its own honest empty
    state rather than inventing movement (§1 law 4)."""
    if prior_payload is None:
        return []

    insights: list[str] = []
    latest_rows = {r["ticker"]: r for r in latest_payload.get("ranked", [])}
    prior_rows = {r["ticker"]: r for r in prior_payload.get("ranked", [])}

    # --- Verdict transitions
    #
    # Only transitions between two REAL calls count as a decision. A move
    # in or out of "Insufficient data" / "Withheld" is the engine gaining
    # or losing coverage for a name, not a view changing — reporting it
    # here (especially in bulk, the week a backlog of filings lands or a
    # backfill runs) would bury the handful of genuine re-rates under a
    # coverage-churn list. Coverage is the trust bar's job, not this one.
    improved: list[str] = []
    softened: list[str] = []
    _RANK = {
        "Strong Buy": 0, "Buy": 1, "Accumulate": 2, "Hold": 3, "Trim": 4, "Sell": 5,
    }
    for ticker, row in latest_rows.items():
        prior = prior_rows.get(ticker)
        if prior is None:
            continue
        now_v, was_v = row.get("verdict"), prior.get("verdict")
        if now_v == was_v or now_v not in _RANK or was_v not in _RANK:
            continue
        if _RANK[now_v] < _RANK[was_v]:
            improved.append(f"{ticker} {was_v}→{now_v}")
        else:
            softened.append(f"{ticker} {was_v}→{now_v}")

    def _verdict_sentence(lead: str, items: list[str]) -> str:
        shown = sorted(items)[:INSIGHT_MAX_VERDICT_NAMES]
        rest = len(items) - len(shown)
        tail = f", and {rest} more" if rest > 0 else ""
        return f"{lead}: " + ", ".join(shown) + tail

    if improved:
        insights.append(_verdict_sentence("Verdict improved since last week", improved))
    if softened:
        insights.append(_verdict_sentence("Verdict softened since last week", softened))

    # --- Biggest score movers (well-corroborated rows only)
    movers: list[tuple[Decimal, str]] = []
    for ticker, row in latest_rows.items():
        prior = prior_rows.get(ticker)
        if prior is None:
            continue
        now_s, was_s = _score(row), _score(prior)
        if now_s is None or was_s is None:
            continue
        if row.get("pillars_included", 0) < INSIGHT_MIN_PILLARS:
            continue
        move = now_s - was_s
        if abs(move) >= INSIGHT_MIN_SCORE_MOVE:
            movers.append((move, ticker))
    for move, ticker in sorted(movers, key=lambda m: abs(m[0]), reverse=True)[:3]:
        sign = "+" if move >= 0 else ""
        insights.append(
            f"{ticker} composite {sign}{move.quantize(Decimal('1'))} pts week-over-week"
        )

    # --- Sector average-score shifts
    def _sector_means(payload: dict) -> dict[str, Decimal]:
        buckets: dict[str, list[Decimal]] = defaultdict(list)
        for r in payload.get("ranked", []):
            s = _score(r)
            if s is not None and r.get("cse_sector"):
                buckets[r["cse_sector"]].append(s)
        return {k: sum(v, Decimal(0)) / len(v) for k, v in buckets.items() if v}

    now_means, was_means = _sector_means(latest_payload), _sector_means(prior_payload)
    sector_moves: list[tuple[Decimal, str]] = []
    for sector, now_mean in now_means.items():
        if sector in was_means:
            delta = now_mean - was_means[sector]
            if abs(delta) >= INSIGHT_MIN_SCORE_MOVE:
                sector_moves.append((delta, sector))
    for delta, sector in sorted(sector_moves, key=lambda m: abs(m[0]), reverse=True)[:2]:
        sign = "+" if delta >= 0 else ""
        insights.append(
            f"{sector} sector average {sign}{delta.quantize(Decimal('1'))} pts week-over-week"
        )

    return insights
