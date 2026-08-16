"""add rejected_by/rejected_at to corporate_actions

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("corporate_actions", sa.Column("rejected_by", sa.String(100), nullable=True))
    op.add_column("corporate_actions", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("corporate_actions", "rejected_at")
    op.drop_column("corporate_actions", "rejected_by")
