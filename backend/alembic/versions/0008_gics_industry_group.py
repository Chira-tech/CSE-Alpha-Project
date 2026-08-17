"""store the GICS industry group the exchange publishes

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-17

`cse_sector` and `archetype` had been NULL for every company since the
first commit, on the conclusion that no endpoint carried sector
membership. That conclusion was wrong: `listBySector` (POST form,
`sectorId`) returns the constituents of each of the 20 GICS industry
groups the exchange publishes, covering 257 of the 283 traded lines.

The four-digit code is stored alongside the name because the GICS sector
above it is derivable from its first two digits (see
`app.domain.gics`) — keeping only the name would throw that away and
leave the wider grouping to be re-guessed from strings.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "securities", sa.Column("gics_industry_group_code", sa.String(8), nullable=True)
    )
    op.add_column(
        "securities", sa.Column("sector_source", sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("securities", "sector_source")
    op.drop_column("securities", "gics_industry_group_code")
