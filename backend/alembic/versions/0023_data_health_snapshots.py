"""data_health_snapshots — daily freeze of the check ledger for trends

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-01

`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` §9.1 / §10.11 — the
ledger table needs "one sparkline per row", and §11's "one number to
watch" (the checkable share of the universe) is only meaningful as a
trend. One row per calendar day, written opportunistically by
`GET /data-health`; no separate job.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_health_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ledger_json", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_data_health_snapshots_as_of", "data_health_snapshots", ["as_of"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_data_health_snapshots_as_of", table_name="data_health_snapshots")
    op.drop_table("data_health_snapshots")
