"""fundamental_validations — the data-integrity gate's per-row verdict

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-03

The "Data Integrity, Cross-Verification & Validation Framework" spec
(3 Sep 2026): every fundamentals value must pass a check battery before
the valuation engine may use it. One row per `fundamentals` row —
`passed` is the binary gate, `failures_json` is what a reviewer sees for
a row that goes to the queue instead.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fundamental_validations",
        sa.Column(
            "fundamental_id",
            sa.Integer,
            sa.ForeignKey("fundamentals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("method", sa.String(length=60), nullable=False),
        sa.Column("failures_json", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_fundamental_validations_passed", "fundamental_validations", ["passed"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fundamental_validations_passed", table_name="fundamental_validations"
    )
    op.drop_table("fundamental_validations")
