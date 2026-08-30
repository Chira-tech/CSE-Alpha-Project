"""composite_ranking_snapshots table for the precomputed §38 scoreboard

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-30

See app/models/composite_ranking_snapshot.py for the full design — why the
per-run result is stored as one JSON payload rather than a wide table, and
why dated rows are kept rather than overwritten (the week-over-week
insights and score sparklines in docs/CSE_Alpha_Engine_Scoreboard_Queue_
Redesign.md depend on real history between two real snapshots).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "composite_ranking_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Numeric(8, 2), nullable=False),
        sa.Column("ranked_count", sa.Integer, nullable=False),
        sa.Column("excluded_count", sa.Integer, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_composite_ranking_snapshots_as_of", "composite_ranking_snapshots", ["as_of"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_composite_ranking_snapshots_as_of", table_name="composite_ranking_snapshots"
    )
    op.drop_table("composite_ranking_snapshots")
