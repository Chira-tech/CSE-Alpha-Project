"""record what each listed line actually is, and who issued it

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

The universe comes from `tradeSummary`, which returns every line that
traded rather than every company. On 17 Aug 2026 that was 283 lines, of
which 21 were not ordinary shares: 18 non-voting lines (COMB.X0000,
HNB.X0000, SEYB.X0000, ...), 2 closed-end fund units and 1 rights line.

Stored as columns rather than derived on read for two reasons. Gate 2
(§11.1) has to reject non-equity lines, and a gate that recomputes its
own inputs from a string every time is a gate whose history cannot be
audited. And `issuer_code` is what lets one company's fundamentals attach
once across its voting and non-voting lines, so it needs to be joinable.

Both are backfilled here from the existing tickers using the same
`app.domain.instrument_type` logic the application uses, so an existing
database ends up identical to a freshly bootstrapped one.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("instrument_type", sa.String(20), nullable=True))
    op.add_column("securities", sa.Column("issuer_code", sa.String(20), nullable=True))

    # Backfill through the domain classifier rather than re-implementing
    # the suffix rules in SQL — two copies of this logic would drift, and
    # the copy in a migration is the one nobody re-reads.
    from app.domain.instrument_type import classify, issuer_code

    connection = op.get_bind()
    tickers = [row[0] for row in connection.execute(sa.text("SELECT ticker FROM securities"))]
    for ticker in tickers:
        connection.execute(
            sa.text(
                "UPDATE securities SET instrument_type = :kind, issuer_code = :issuer "
                "WHERE ticker = :ticker"
            ),
            {"kind": classify(ticker).value, "issuer": issuer_code(ticker), "ticker": ticker},
        )

    op.create_index("ix_securities_issuer_code", "securities", ["issuer_code"])


def downgrade() -> None:
    op.drop_index("ix_securities_issuer_code", table_name="securities")
    op.drop_column("securities", "issuer_code")
    op.drop_column("securities", "instrument_type")
