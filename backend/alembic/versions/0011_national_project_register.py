"""§34's national project and outlook register

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-18

"A structured register of confirmed Sri Lankan projects and policy
programmes, each mapped to affected tickers, because for a 12-36 month
horizon these are the concrete catalysts." Confirmation is at the
project level (mirroring `corporate_actions`' own confirmed_by/
confirmed_at/rejected_by/rejected_at gate, §7/§8) — a project and all of
its affected-ticker impact rows are confirmed together as one unit, not
independently.

See `app/models/national_projects.py` for the full field-by-field
rationale, especially why capex is stored in BOTH LKR and USD rather
than one derived from the other, and why `provenance_tag` reuses
`ProvenanceTier` ("E"/"F") directly instead of a new two-value enum.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_VALUES = ("announced", "mou", "financing_closed", "under_construction", "operational")
_FINANCING_SOURCE_VALUES = ("state", "fdi", "ppp")
_TRANSMISSION_CHANNEL_VALUES = (
    "contractor",
    "materials_supplier",
    "financier",
    "landlord",
    "beneficiary_of_demand",
)
_IMPACT_METRIC_VALUES = ("revenue", "margin")
_PROVENANCE_VALUES = ("R", "D", "N", "E", "F", "A", "-")


def upgrade() -> None:
    status = sa.Enum(*_STATUS_VALUES, name="nationalprojectstatus")
    financing_source = sa.Enum(*_FINANCING_SOURCE_VALUES, name="nationalprojectfinancingsource")
    transmission_channel = sa.Enum(
        *_TRANSMISSION_CHANNEL_VALUES, name="nationalprojecttransmissionchannel"
    )
    impact_metric = sa.Enum(*_IMPACT_METRIC_VALUES, name="nationalprojectimpactmetric")
    # Reuses the SAME Postgres enum type migration 0001 already created
    # for `fundamentals.provenance_tier` — `create_type=False` tells
    # SQLAlchemy the type already exists rather than attempting (and
    # failing on) a second `CREATE TYPE provenancetier`. Not dropped in
    # this migration's own downgrade for the same reason: it's owned by
    # 0001, which already drops it, and another table (`fundamentals`)
    # still depends on it after this migration's downgrade runs.
    provenance_tier = sa.Enum(*_PROVENANCE_VALUES, name="provenancetier", create_type=False)

    op.create_table(
        "national_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sponsor", sa.String(200), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("financing_source", financing_source, nullable=True),
        sa.Column("capex_lkr", sa.Numeric(20, 2), nullable=True),
        sa.Column("capex_usd", sa.Numeric(20, 2), nullable=True),
        sa.Column("phase_start_date", sa.Date(), nullable=True),
        sa.Column("phase_expected_completion_date", sa.Date(), nullable=True),
        sa.Column("status", status, nullable=False, server_default="announced"),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.String(100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(100), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "national_project_ticker_impacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("national_projects.id"), nullable=False
        ),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("securities.ticker"), nullable=False),
        sa.Column("transmission_channel", transmission_channel, nullable=False),
        sa.Column("impact_metric", impact_metric, nullable=False),
        sa.Column("quantified_impact_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column("impact_description", sa.Text(), nullable=False),
        sa.Column("provenance_tag", provenance_tier, nullable=False),
    )
    op.create_index(
        "ix_national_project_ticker_impacts_ticker", "national_project_ticker_impacts", ["ticker"]
    )
    op.create_index(
        "ix_national_project_ticker_impacts_project_id",
        "national_project_ticker_impacts",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_national_project_ticker_impacts_project_id",
        table_name="national_project_ticker_impacts",
    )
    op.drop_index(
        "ix_national_project_ticker_impacts_ticker", table_name="national_project_ticker_impacts"
    )
    op.drop_table("national_project_ticker_impacts")
    op.drop_table("national_projects")

    # `provenancetier` itself is NOT dropped here — see upgrade()'s own
    # comment: it's owned by migration 0001, which drops it, and
    # `fundamentals` still depends on it after this downgrade runs.
    sa.Enum(name="nationalprojectimpactmetric").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="nationalprojecttransmissionchannel").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="nationalprojectfinancingsource").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="nationalprojectstatus").drop(op.get_bind(), checkfirst=True)
