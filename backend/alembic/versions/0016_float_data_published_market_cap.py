"""TASK 0.1 plausibility gate: capture CSE's own published market cap

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-18

See `app/models/float_data.py`'s `published_market_cap` docstring: this
figure (`companyInfoSummery.reqSymbolInfo.marketCap`) was already being
fetched, in the same call as `shares_issued`, by
`app.ingestion.security_enrichment.enrich_security` — but silently
discarded rather than stored. `app.domain.sanity`'s `share_count_
reconciles` rule needs a genuinely independent market-cap figure (not
`price x shares` computed locally, which would be a tautology), and this
is the real one the exchange already publishes.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "float_data", sa.Column("published_market_cap", sa.Numeric(20, 2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("float_data", "published_market_cap")
