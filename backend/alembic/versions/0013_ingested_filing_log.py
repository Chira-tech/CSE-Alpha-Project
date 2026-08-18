"""Real bug fix: record every processed archived filing, drafts or not

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-18

A REAL, structural bug, found live 18 Aug 2026, independent of any
specific ticker: `app.ingestion.financial_reports_archive_loader.
ingest_archived_report` only recorded that a filing had been processed
by inserting `Fundamental` rows carrying its `source_url` — and only did
that when at least one draft was produced. A filing that legitimately
produces 0 real drafts (a real, confirmed case: PAP.N0000's 31 March
2026 interim statement, a genuinely scanned PDF with no text layer) left
no trace anywhere that it had been attempted, so a naive retry would
re-download and re-parse the identical PDF from scratch, forever, with
no way to tell "already tried, genuinely got nothing" apart from "never
attempted". See `app/models/ingestion_log.py` for the full finding.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingested_filing_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("drafted_count", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingested_filing_log_ticker", "ingested_filing_log", ["ticker"])
    op.create_index(
        "ix_ingested_filing_log_source_url", "ingested_filing_log", ["source_url"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingested_filing_log_source_url", table_name="ingested_filing_log")
    op.drop_index("ix_ingested_filing_log_ticker", table_name="ingested_filing_log")
    op.drop_table("ingested_filing_log")
