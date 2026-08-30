"""
R1 T2.5 — "is this AI-assisted figure independently corroborated?", the
one check the confirm queue treats as safe to act on without a human
looking at each individual value.

Lifted verbatim out of `app.api.routes.fundamentals` (where it was
route-private as `_corroborated_ids`) so BOTH the route's
`confirm-batch-corroborated` endpoint AND the scheduled
`auto_confirm_corroborated_fundamentals` job (`app.jobs.runner`) run the
identical logic and cannot drift. The route re-imports `corroborated_ids`
from here; its behaviour is unchanged.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental


def corroborated_ids(db: Session, rows: list[Fundamental]) -> set[int]:
    """One bulk query for every REPORTED row matching ANY of these rows'
    (ticker, period_end, statement_line) keys — not N queries per row,
    same discipline every other bulk lookup in this codebase already
    applies — then an in-Python exact-value-and-different-`source_url`
    check, since SQLAlchemy has no clean portable "tuple IN (values)"
    across both SQLite (dev) and Postgres (prod).

    DELIBERATELY NOT keyed on `period_type` too, found live (23 Aug
    2026, ABAN.N0000's real total_assets for 2019-03-31): the same
    point-in-time balance-sheet figure is genuinely reported once as
    `period_type="annual"` (that year's own annual report) and again as
    `period_type="quarterly"` (a later interim report's own comparative
    prior-year-end column) — the first version of this function required
    both to match, which meant it never fired for exactly the shape of
    corroboration that's most common in this data. Safe to drop: a real
    flow figure (`revenue`, `net_income`, ...) genuinely measures a
    different span in each period_type and would essentially never
    coincidentally match to the exact rupee AND land at a different
    `source_url` AND land on the same `period_end` — the value+source
    check below already carries the real safety property, not the
    period_type match.
    """
    if not rows:
        return set()
    keys = {(r.ticker, r.period_end, r.statement_line) for r in rows}
    tickers = {k[0] for k in keys}
    candidates = db.scalars(
        select(Fundamental).where(
            Fundamental.ticker.in_(tickers),
            Fundamental.provenance_tier == ProvenanceTier.REPORTED,
        )
    ).all()
    reported_by_key: dict[tuple, list[Fundamental]] = {}
    for c in candidates:
        reported_by_key.setdefault((c.ticker, c.period_end, c.statement_line), []).append(c)

    corroborated: set[int] = set()
    for r in rows:
        key = (r.ticker, r.period_end, r.statement_line)
        for c in reported_by_key.get(key, ()):
            if c.value == r.value and c.source_url != r.source_url:
                corroborated.add(r.id)
                break
    return corroborated


def _pending_ai_assisted(db: Session, *, limit: int, offset: int) -> list[Fundamental]:
    return list(
        db.scalars(
            select(Fundamental)
            .where(
                Fundamental.provenance_tier == ProvenanceTier.AI_ASSISTED,
                Fundamental.confirmed_by.is_(None),
            )
            .order_by(Fundamental.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def all_corroborated_pending_ids(db: Session, *, batch_size: int = 500) -> list[int]:
    """Every pending AI-assisted fundamental the server can independently
    verify as corroborated right now, across the whole queue — paged so a
    queue past 11,000 rows (a real backfill state, see
    `app.api.routes.fundamentals.FundamentalsPage`) is never loaded whole.
    Used by the nightly auto-confirm job and by Data health's
    "N corroborated, cleared automatically" count."""
    found: list[int] = []
    offset = 0
    while True:
        batch = _pending_ai_assisted(db, limit=batch_size, offset=offset)
        if not batch:
            break
        hits = corroborated_ids(db, batch)
        found.extend(r.id for r in batch if r.id in hits)
        offset += len(batch)
        if len(batch) < batch_size:
            break
    return found
