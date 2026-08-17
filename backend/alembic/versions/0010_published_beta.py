"""store the exchange's own published beta, which enrichment already fetches but never kept

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-17

`security_enrichment.py`'s own module docstring has claimed since it was
written that per-company enrichment covers "CSE's own published beta" —
`companyInfoSummery`'s `reqSymbolBetaInfo.triASIBetaValue` /
`betaValueSPSL`, already modelled in `CompanyBetaInfo`
(app/ingestion/schemas.py). It was never actually written to the
database; the claim was true of the schema, not of what the loader did
with it. No new API call needed — this data has been arriving in every
enrichment response the whole time.

Real value, not decoration: `app.domain.beta`'s Dimson-Blume computation
needs an independent figure to check itself against, the same way the
CBSL/TradingView/GICS work earlier in this project always sought one out
rather than trusting a single pipeline.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("published_beta_asi", sa.Numeric(10, 6), nullable=True))
    op.add_column("securities", sa.Column("published_beta_sp_sl20", sa.Numeric(10, 6), nullable=True))
    op.add_column("securities", sa.Column("published_beta_period", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("securities", "published_beta_period")
    op.drop_column("securities", "published_beta_sp_sl20")
    op.drop_column("securities", "published_beta_asi")
