"""Real user-uploaded portfolio holdings snapshots

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-18

A user-uploaded CDS/broker portfolio export becomes one immutable
`portfolio_snapshots` row plus its `portfolio_positions` rows — never an
overwrite of a prior snapshot, the same point-in-time discipline this
whole system already applies everywhere else. `portfolio_positions.
ticker` is deliberately NOT a foreign key to `securities.ticker` — see
`app/models/portfolio.py` for why a real held position must never be
silently dropped just because this system's own `securities` table
doesn't (yet) recognise it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("stated_total_cost", sa.Numeric(20, 2), nullable=True),
        sa.Column("stated_total_market_value", sa.Numeric(20, 2), nullable=True),
        sa.Column("identity_check_passed", sa.Boolean(), nullable=False),
        sa.Column("identity_check_note", sa.String(500), nullable=False),
    )

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id", sa.Integer(), sa.ForeignKey("portfolio_snapshots.id"), nullable=False
        ),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("avg_price", sa.Numeric(18, 5), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 2), nullable=False),
        sa.Column("traded_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("market_value", sa.Numeric(20, 2), nullable=True),
        sa.Column("unrealized_gain_loss", sa.Numeric(20, 2), nullable=True),
    )
    op.create_index("ix_portfolio_positions_snapshot_id", "portfolio_positions", ["snapshot_id"])
    op.create_index("ix_portfolio_positions_ticker", "portfolio_positions", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_positions_ticker", table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_snapshot_id", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")
    op.drop_table("portfolio_snapshots")
