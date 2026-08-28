"""Unique constraint on fundamentals(ticker, period_end, period_type, statement_line, version)

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-26

Closes a real, structurally-possible gap named while investigating a
product-owner question about duplicate ingestion: nothing in the schema
ever enforced that this 5-tuple is unique — `Fundamental.__table_args__`
had only plain (non-unique) indexes, and every ingestion path relied
SOLELY on an application-level check-then-insert (`_already_ingested`,
`_already_ingested_by_source`) with no database-level backstop, the same
class of gap already disclosed for `JobRun` concurrency
(`app.models.job_run`'s own docstring). Two ingestion processes hitting
the exact same filing at the exact same moment (e.g. a manually-run
`backfill-financials` overlapping the scheduled daily `capture_filings`
job) could both pass their own "not yet ingested" check before either
commits, and both insert.

VERIFIED SAFE TO APPLY BEFORE WRITING THIS: queried the real dev
database (105,618 rows) for this exact 5-tuple — zero existing
violations. Every legitimate code path already independently avoids
producing one on purpose: `build_fundamental_drafts` keeps only the
first occurrence per canonical key (or sums every occurrence into ONE
draft for the few keys in `SUM_ACROSS_OCCURRENCES`); `derive_additional_
line_items` explicitly skips a key already directly extracted; and
`ingest_archived_report`'s `reconcile=True` path explicitly filters out
any `statement_line` already on file for that exact `source_url`/
version before inserting. This constraint backs an invariant every real
code path already upholds — it has never fired in practice, and is not
expected to under normal operation; it exists only to turn the narrow
concurrent-run race into a loud `IntegrityError` instead of a silent
duplicate row.

DELIBERATELY NOT applied to `ingested_filing_log(ticker, source_url)` —
investigated as the same candidate fix and REJECTED: the real dev
database has 53 real, legitimate repeats of that pair, every one of
them a `reconcile=True` pass on a LATER day finding genuinely new
`statement_line`s the first pass missed (see `ingest_archived_report`'s
own docstring — a reconciliation pass that finds nothing new correctly
skips logging again, but one that DOES find something new is meant to
log a second time, with its own `drafted_count`). All 53 are calendar-
day-apart, zero same-day/near-simultaneous pairs — real evidence this is
the intended reconcile behaviour, not the race this migration guards
against. A unique constraint there would have been enforcing a false
invariant and broken a real, working feature.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_fundamentals_ticker_period_type_line_version"
_TABLE = "fundamentals"
_COLS = "(ticker, period_end, period_type, statement_line, version)"


def upgrade() -> None:
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME} ON {_TABLE} {_COLS}")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
