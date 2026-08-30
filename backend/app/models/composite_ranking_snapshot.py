"""
One completed run of §38's universe-wide composite ranking, frozen so the
Opportunities screen can read a finished result in a single fast query
instead of triggering the real ~70s valuation pass on the request path.

WHY A STORED SNAPSHOT AND NOT JUST THE TTL CACHE. `app.domain.composite_
ranking_view` already caches its result in a module-level dict with a
short disclosed TTL (45s) — that collapses a burst of near-simultaneous
callers into one compute, but the FIRST caller after any TTL expiry still
pays the full ~70s pass (measured live, 30 Aug 2026, ~280-ticker
confirmed universe on the dev SQLite database). That is the real
"Opportunities takes forever to load" symptom. The fix, per
`docs/CSE_Alpha_Engine_Scoreboard_Queue_Redesign.md` §2: run the pass on
a schedule (`app.jobs.scheduler._job_recompute_composite_ranking`, plus a
manual `recompute_composite_ranking` trigger), write the finished result
here, and have `GET /composite-ranking` only ever READ this table. A cold
install with no snapshot row yet falls back to a live compute so the
endpoint is never broken, just slow that once.

WHY DATED ROWS ARE KEPT, NEVER OVERWRITTEN. Same Design Law 2 the rest of
this system already follows (see `app.models.portfolio.PortfolioSnapshot`'s
own docstring). Keeping every run's result is what makes the redesign's
week-over-week "Top Insights" strip and the per-row score-over-time
sparkline REAL diffs between two real snapshots, rather than fabricated
movement. `computed_at` orders runs; "latest" is a query concern (see
`app.domain.composite_ranking_snapshot_view`), not a column.

WHY THE PAYLOAD IS ONE JSON BLOB, NOT A WIDE NORMALISED TABLE. The §38
pillar set and per-row shape are still evolving (Growth blends in once
register coverage reaches 3 tickers; §39 fusion and §14's integrity veto
are still unbuilt). Storing the serialised `CompositeRankingOut` verbatim
keeps that shape entirely out of the database schema — a later pillar or
field never needs a migration just to be storable. History queries only
ever need each run's per-ticker `total_score`, which is a cheap in-Python
read over a handful of recent blobs, not something the database must
index.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompositeRankingSnapshot(Base):
    __tablename__ = "composite_ranking_snapshots"
    __table_args__ = (Index("ix_composite_ranking_snapshots_as_of", "as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    """The market date the ranking was computed FOR — `CompositeRankingView.
    as_of`. Distinct from `computed_at`: a run kicked off just after
    midnight, or a manual re-run on a quiet Sunday, is still "for" a
    trading date."""

    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Wall-clock UTC the pass actually finished. Orders runs, and is what
    the screen shows as "Last computed:" so staleness is visible rather
    than silent (§8 / the redesign doc's §2)."""

    duration_seconds: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    """How long the pass took — kept so a regression in the ~70s figure is
    observable without re-timing it by hand."""

    ranked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    """Denormalised counts, so a caller listing recent runs doesn't have to
    parse `payload` just to show "281 ranked / 6 excluded"."""

    payload: Mapped[str] = mapped_column(Text, nullable=False)
    """The full serialised `app.api.routes.composite_ranking.
    CompositeRankingOut` JSON for this run — see the module docstring for
    why the row shape lives here as text rather than as columns."""
