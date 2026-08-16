"""add source_snippet/confirmed_by/confirmed_at to fundamentals

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fundamentals", sa.Column("source_snippet", sa.Text(), nullable=True))
    op.add_column("fundamentals", sa.Column("confirmed_by", sa.String(100), nullable=True))
    op.add_column("fundamentals", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fundamentals", "confirmed_at")
    op.drop_column("fundamentals", "confirmed_by")
    op.drop_column("fundamentals", "source_snippet")
