from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestedFilingLog(Base):
    """A REAL, structural bug this table exists to close, found live (18
    Aug 2026) in `app.ingestion.financial_reports_archive_loader.
    ingest_archived_report`: that function only recorded that a filing
    had been processed by inserting `Fundamental` draft rows carrying its
    `source_url` — and only did that `db.add_all(drafts); db.commit()`
    when `drafts` was NON-EMPTY. A filing that legitimately produces 0
    real drafts (no canonical line item on it, e.g. a segmental-analysis-
    only page slipping past the marker filter) — or one whose processing
    crashed partway through, before any draft was ever built — left
    NO trace anywhere that it had been attempted at all. `_already_
    ingested_by_source` (this loader's own idempotency check) could only
    find a filing "already processed" by finding a `Fundamental` row for
    it — which never existed for exactly the filings this bug affected —
    so a naive retry would re-download and re-parse the IDENTICAL PDF
    from scratch every single time, forever, with no way to distinguish
    "already tried, genuinely got nothing real to extract" from "never
    attempted at all". This is independent of any specific ticker; it
    would eventually affect every company with even one filing shaped
    this way (verified live examples exist — see PAP.N0000's 31 March
    2026 filing, a genuinely scanned PDF with no text layer, 0 drafts
    every time, in test_financial_reports_archive_loader.py).

    One row per (ticker, source_url) actually processed by `ingest_
    archived_report`, REGARDLESS of `drafted_count` — including zero.
    `_already_ingested_by_source` now checks this table IN ADDITION to
    (not instead of) `Fundamental.source_url`, so filings ingested before
    this table existed (which DO have a `Fundamental` row, for every
    filing that produced at least one real draft) remain correctly
    recognised as already-ingested without needing a backfill migration
    of historical data."""

    __tablename__ = "ingested_filing_log"
    __table_args__ = (
        Index("ix_ingested_filing_log_ticker", "ticker"),
        Index("ix_ingested_filing_log_source_url", "source_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'quarterly' | 'annual'
    drafted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    """How many `Fundamental` drafts this specific filing produced —
    genuinely 0 for a real filing that had nothing extractable on it (see
    the class docstring), never a guess and never omitted just because
    it's zero."""
    processed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
