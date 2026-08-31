"""security.trading_status — current trading state (active/suspended/delisted)

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-31

`docs/CSE_Universe_Integrity_Rollout.md` Part 4 and golden regression case
6: a suspended or delisted line must drop out of the Opportunities ranking
and carry no verdict — the exchange has halted trading, so there is no
live price to value against. `delisting_date` records the historical fact;
this column is the current live state, so the two are kept separate.

The column backfills `delisted` from `delisting_date` here (a pure schema
consequence). `suspended` is a live-data judgement — a non-delisted line
with no trade in over 90 days — and is set by the re-runnable
`scripts.backfill_trading_status`, not baked into a migration.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "securities",
        sa.Column(
            "trading_status",
            sa.String(length=12),
            nullable=False,
            server_default="active",
        ),
    )
    op.execute(
        "UPDATE securities SET trading_status = 'delisted' "
        "WHERE delisting_date IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("securities", "trading_status")
