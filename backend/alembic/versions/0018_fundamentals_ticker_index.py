"""Index fundamentals.ticker and ingested_filing_log.ticker

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-19

Real bug, found live: neither table had an index on `ticker` at all —
`fundamentals.id` and `ingested_filing_log.id` are the only primary keys,
unlike `prices_daily`, whose composite (ticker, date) primary key gets an
implicit index for free. Every per-ticker query (point-in-time lookups
filtering `first_available_date <= t`, `_next_version`,
`_already_ingested_by_source`, the confirm-queue list, every valuation
model's own line-item selection) did a full table scan. Invisible at the
row counts these tables started at (213 fundamentals rows); very visible
after a real backfill grew `fundamentals` to 11,394 rows across 268
tickers — `GET /opportunities` measured at 20+ seconds, almost entirely
inside per-ticker fundamentals lookups for just 9 tickers, saturating
the browser's 6-connections-per-origin limit and making an unrelated
screen (Companies) LOOK broken while it was actually just queued behind
slow requests.

RECONCILED, not just written from a clean slate: the real dev database
already had 4 of these 5 indexes when this migration was first run
against it — created directly against the live SQLite file while this
exact slowness was being independently diagnosed in parallel, never
through a migration or a model declaration. `CREATE INDEX IF NOT EXISTS`
makes this migration safe to apply regardless of whether those already
exist, and the SQLAlchemy models (`Fundamental.__table_args__`,
`IngestedFilingLog.__table_args__`) now declare the exact same set, so a
FRESH database — or production Postgres, where none of this was ever
applied — gets it too, not just this one already-patched dev file.
`IF NOT EXISTS` is real, portable syntax on both engines (SQLite; Postgres
9.5+), not a SQLite-only workaround.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    ("ix_fundamentals_ticker", "fundamentals", "(ticker)"),
    ("ix_fundamentals_ticker_first_available", "fundamentals", "(ticker, first_available_date)"),
    ("ix_fundamentals_ticker_source_url", "fundamentals", "(ticker, source_url)"),
    ("ix_ingested_filing_log_ticker", "ingested_filing_log", "(ticker)"),
    ("ix_ingested_filing_log_source_url", "ingested_filing_log", "(source_url)"),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")


def downgrade() -> None:
    for name, _table, _cols in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
