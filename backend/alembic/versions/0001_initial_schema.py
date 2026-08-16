"""initial schema — Master Spec §9 core tables (Phase 1 subset)

Revision ID: 0001
Revises:
Create Date: 2026-08-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVENANCE_VALUES = ("R", "D", "N", "E", "F", "A", "-")
_ACTION_TYPE_VALUES = (
    "dividend_cash",
    "bonus_issue",
    "rights_issue",
    "stock_split",
    "consolidation",
    "delisting",
    "suspension",
)


def upgrade() -> None:
    provenance_tier = sa.Enum(*_PROVENANCE_VALUES, name="provenancetier")
    action_type = sa.Enum(*_ACTION_TYPE_VALUES, name="corporateactiontype")

    op.create_table(
        "securities",
        sa.Column("ticker", sa.String(20), primary_key=True),
        sa.Column("isin", sa.String(20), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("gics_sector", sa.String(100), nullable=True),
        sa.Column("cse_sector", sa.String(100), nullable=True),
        sa.Column("archetype", sa.String(50), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("delisting_date", sa.Date(), nullable=True),
        sa.Column("board", sa.String(50), nullable=True),
        sa.Column("fiscal_year_end", sa.String(5), nullable=True),
        sa.Column("reporting_lag_days_quarterly", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("reporting_lag_days_annual", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("currency_exposure_profile", sa.String(50), nullable=True),
    )

    op.create_table(
        "prices_daily",
        sa.Column("ticker", sa.String(20), sa.ForeignKey("securities.ticker"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("open", sa.Numeric(18, 4), nullable=True),
        sa.Column("high", sa.Numeric(18, 4), nullable=True),
        sa.Column("low", sa.Numeric(18, 4), nullable=True),
        sa.Column("close", sa.Numeric(18, 4), nullable=True),
        sa.Column("vwap", sa.Numeric(18, 4), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("turnover", sa.Numeric(20, 2), nullable=True),
        sa.Column("trades", sa.Integer(), nullable=True),
        sa.Column("adj_factor", sa.Numeric(20, 10), nullable=False, server_default="1.0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="cse.lk"),
    )

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("securities.ticker"), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("type", action_type, nullable=False),
        sa.Column("ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("cash_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("subscription_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("cum_rights_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("terp", sa.Numeric(18, 4), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("confirmed_by", sa.String(100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_corporate_actions_ticker", "corporate_actions", ["ticker"])

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("securities.ticker"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("first_available_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("statement_line", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(24, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="LKR"),
        sa.Column("provenance_tier", provenance_tier, nullable=False),
        sa.Column("restated_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_fundamentals_ticker_first_available",
        "fundamentals",
        ["ticker", "first_available_date"],
    )

    op.create_table(
        "float_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("securities.ticker"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("shares_issued", sa.Integer(), nullable=False),
        sa.Column("public_float_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("top20_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("controlling_holder", sa.String(200), nullable=True),
    )

    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(50), primary_key=True),
        sa.Column("obs_date", sa.Date(), primary_key=True),
        sa.Column("first_available_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(24, 6), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
    )

    op.create_table(
        "data_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("detail", sa.String(1000), nullable=False),
        sa.Column("mismatch_pct", sa.Numeric(8, 5), nullable=True),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_data_alerts_ticker_resolved", "data_alerts", ["ticker", "resolved"])

    # Master Spec §51: "PostgreSQL with TimescaleDB for price series."
    # Optional — degrade gracefully to a plain table if the extension isn't
    # installed, so local dev against vanilla Postgres still works.
    bind = op.get_bind()
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        bind.execute(
            sa.text(
                "SELECT create_hypertable('prices_daily', 'date', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )
    except Exception as exc:  # noqa: BLE001 — intentionally broad, this is a best-effort enhancement
        print(f"[migration] TimescaleDB not available, using plain table for prices_daily: {exc}")


def downgrade() -> None:
    op.drop_table("data_alerts")
    op.drop_table("macro_series")
    op.drop_table("float_data")
    op.drop_table("fundamentals")
    op.drop_table("corporate_actions")
    op.drop_table("prices_daily")
    op.drop_table("securities")
    sa.Enum(name="corporateactiontype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="provenancetier").drop(op.get_bind(), checkfirst=True)
