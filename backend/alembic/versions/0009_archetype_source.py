"""track where archetype came from, so a proposal never overwrites a human

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-17

Companion to 0008's `sector_source`. `app.domain.archetype` proposes a
§16 valuation archetype from the GICS classification 0008 introduced, but
Appendix P2 requires the mapping to be hand-correctable — this column is
what lets `app.ingestion.archetype_loader` tell a proposed value apart
from a corrected one and refuse to clobber the latter.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("archetype_source", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("securities", "archetype_source")
