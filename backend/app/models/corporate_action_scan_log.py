from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CorporateActionScanLog(Base):
    """A real, structural gap this table exists to close, found live (18
    Aug 2026): `python -m app.cli ingest-corporate-actions` (§7's
    full-universe sweep) always started from ticker #1 every single
    invocation, with no memory of how far a PREVIOUS run got. On its own
    this is fine for a normal completed run — but this environment's
    background processes were repeatedly observed dying a few minutes
    into a real, ~283-ticker, >=2s-paced sweep (a genuine 10+ minute job)
    — so every restart re-scanned the same first handful of tickers from
    scratch, never making net progress past whatever a single few-minute
    window could cover.

    Unlike `IngestedFilingLog` (a specific, immutable PDF filing —
    "already processed, never redo"), a corporate-actions scan is
    genuinely time-bounded, not permanent: §52's own real production
    design runs this scan DAILY, because a company can file a new
    announcement at any time. So this table doesn't mean "never scan
    this ticker again" — it means "scanned recently enough that a sweep
    resuming after an interruption should move on to a ticker it hasn't
    covered yet, rather than a real HTTP round-trip re-confirming what a
    scan from minutes ago already found." `app.cli.cmd_ingest_corporate_
    actions`'s own `--rescan-after-hours` default (20h) is deliberately
    just under the real daily cadence, so a normal scheduled daily run
    is never accidentally skipped, while a sweep interrupted and resumed
    within the same session converges on full coverage instead of
    looping on the same few tickers forever."""

    __tablename__ = "corporate_action_scan_log"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_scanned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
