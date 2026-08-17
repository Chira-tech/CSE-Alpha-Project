"""issuer registry — the exchange's own list, including delisted names

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17

`securities` is built from `tradeSummary`, which returns only what
traded, so it is a survivors-only universe by construction — precisely
what Master Spec §7 forbids and Part N #1 names as a headline failure
mode.

`cntSecurity` (GET, undocumented, verified live 17 Aug 2026) lists 369
issuers against the 264 that traded, and carries a `deleted` flag marking
11 of them as gone. Separate table because it is issuer-level: its
symbols have no line suffix (`COMB`, not `COMB.N0000`), so writing them
into `securities` would mean inventing suffixes the exchange never
published. `securities.issuer_code` (migration 0006) is the join.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "issuer_registry",
        sa.Column("issuer_code", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=True),
        sa.Column("board_id", sa.Integer(), nullable=True),
        sa.Column("delisted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currently_trading", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
    )
    op.create_index("ix_issuer_registry_delisted", "issuer_registry", ["delisted"])


def downgrade() -> None:
    op.drop_index("ix_issuer_registry_delisted", table_name="issuer_registry")
    op.drop_table("issuer_registry")
