"""§45's decision record — "ship this in Phase 3, before most models exist"

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-18

See `app/models/decisions.py` for the full field-by-field rationale,
especially which of §45's own named fields are real and live today
(fv_by_method_json, fv_blended, dispersion, mos_components_json,
buy_below, fair_value, trim_above, market_price_at_decision, and —
with a disclosed caveat — macro_regime/macro_prob) versus genuinely
`None` on every row because the layer that would compute them (§38
composite score, §36 Carhart, §37 timing) doesn't exist yet.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTION_VALUES = ("buy", "watchlist", "pass", "partial", "sell", "trim")


def upgrade() -> None:
    action = sa.Enum(*_ACTION_VALUES, name="decisionaction")

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("action", action, nullable=False),
        sa.Column("size_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("limit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("conviction_1_5", sa.Integer(), nullable=True),
        sa.Column("reasoning_text", sa.Text(), nullable=False),
        sa.Column("falsification_text", sa.Text(), nullable=True),
        sa.Column("fundamental_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("pillar_scores_json", sa.JSON(), nullable=True),
        sa.Column("integrity_flags_json", sa.JSON(), nullable=True),
        sa.Column("fv_by_method_json", sa.JSON(), nullable=True),
        sa.Column("fv_blended", sa.Numeric(18, 4), nullable=True),
        sa.Column("dispersion", sa.Numeric(10, 6), nullable=True),
        sa.Column("mos_components_json", sa.JSON(), nullable=True),
        sa.Column("buy_below", sa.Numeric(18, 4), nullable=True),
        sa.Column("fair_value", sa.Numeric(18, 4), nullable=True),
        sa.Column("trim_above", sa.Numeric(18, 4), nullable=True),
        sa.Column("timing_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("timing_branch", sa.String(50), nullable=True),
        sa.Column("timing_signals_json", sa.JSON(), nullable=True),
        sa.Column("macro_regime", sa.String(20), nullable=True),
        sa.Column("macro_prob", sa.Numeric(6, 4), nullable=True),
        sa.Column("sector_fit", sa.Numeric(10, 6), nullable=True),
        sa.Column("alpha", sa.Numeric(10, 6), nullable=True),
        sa.Column("alpha_tstat", sa.Numeric(10, 4), nullable=True),
        sa.Column("betas_json", sa.JSON(), nullable=True),
        sa.Column("residual_vol", sa.Numeric(10, 6), nullable=True),
        sa.Column("market_price_at_decision", sa.Numeric(18, 4), nullable=True),
        sa.Column("data_completeness_pct", sa.Numeric(6, 4), nullable=True),
        sa.Column("agreement_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("override_flag", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_decisions_ticker", "decisions", ["ticker"])

    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False, unique=True),
        sa.Column("exit_date", sa.Date(), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("exit_trigger", sa.String(100), nullable=False),
        sa.Column("gross_return", sa.Numeric(10, 6), nullable=False),
        sa.Column("net_return", sa.Numeric(10, 6), nullable=False),
        sa.Column("holding_days", sa.Integer(), nullable=False),
        sa.Column("max_adverse_excursion", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_favourable_excursion", sa.Numeric(10, 6), nullable=True),
        sa.Column("attribution_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("outcomes")
    op.drop_index("ix_decisions_ticker", table_name="decisions")
    op.drop_table("decisions")
    sa.Enum(name="decisionaction").drop(op.get_bind(), checkfirst=True)
