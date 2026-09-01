"""float_data.published_price — the exchange's own last traded price,
captured in the same payload as marketCap and shares_issued

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-01

`docs/CSE_Data_Health_Diagnosis_And_Protocol.md` E3. The market-cap
identity check compares `price × shares` against the exchange's published
market cap, but `price` is our latest stored close on a possibly-later
date — so a few days of market drift shows up as a "mismatch" that has
nothing to do with the share count the check is actually trying to
validate. `companyInfoSummery.reqSymbolInfo` already carries
`lastTradedPrice` alongside `marketCap` and `quantityIssued`; storing it
lets the check compute `implied_shares = published_market_cap /
published_price` from one self-consistent payload, with no price-timing
confound. Nullable — populated on the next `enrich_securities` run; until
then the E3 check reports not-evaluable for the affected lines.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("float_data", sa.Column("published_price", sa.Numeric(20, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("float_data", "published_price")
