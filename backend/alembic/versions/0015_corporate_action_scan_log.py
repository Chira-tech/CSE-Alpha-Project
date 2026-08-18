"""Real bug fix: resumable corporate-actions sweep, one row per scanned ticker

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-18

See `app/models/corporate_action_scan_log.py` for the full finding: a
real, structural gap where `python -m app.cli ingest-corporate-actions`
always restarted from ticker #1 in alphabetical order, with no memory
of a previous run — so an environment repeatedly observed killing a
long-running background process a few minutes in meant a full ~283-
ticker sweep could never progress past whatever a single few-minute
window covered, no matter how many times it was retried.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_action_scan_log",
        sa.Column("ticker", sa.String(20), primary_key=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("corporate_action_scan_log")
