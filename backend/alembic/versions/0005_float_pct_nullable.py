"""make float_data.public_float_pct nullable

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16

`companyInfoSummery` gives shares issued and foreign holdings but NOT
public free float, which per Master Spec §5 comes from quarterly
shareholding disclosures — a source not yet wired up. With the column
NOT NULL the only ways to record the shares-issued figure we DO have
would be to invent a float percentage or to discard the real data
alongside the missing data. Design Law 3 (§4) settles it: "Missing is
displayed as missing... Silence is a lie in this system." So the column
becomes nullable and Gate 2's free-float test treats NULL as
"cannot evaluate", not as a pass.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table so this works on SQLite (dev) as well as Postgres
    # (production) — SQLite can't ALTER COLUMN in place.
    with op.batch_alter_table("float_data") as batch:
        batch.alter_column("public_float_pct", existing_type=sa.Numeric(6, 4), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("float_data") as batch:
        batch.alter_column("public_float_pct", existing_type=sa.Numeric(6, 4), nullable=False)
