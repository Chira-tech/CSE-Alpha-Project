"""
Master Spec §45: "The decision record — why this ships early." The
spec's own words: "Freezing the full model state at decision time is
what makes learning possible. Without it you can never answer the only
question that matters for improvement: was the model wrong, or was I?"
And explicitly: "SHIP THIS IN PHASE 3, BEFORE MOST MODELS EXIST... Start
recording the day you can see a price and a score, even if the score is
only the fundamental one."

This is exactly the state this system is in: the §38 composite score,
Carhart certification (§36) and the timing battery (§37) don't exist
yet, so several of §45's own named fields (`fundamental_score`,
`pillar_scores_json`, `integrity_flags_json`, `timing_score`,
`timing_branch`, `timing_signals_json`, `alpha`, `alpha_tstat`,
`betas_json`, `residual_vol`, `agreement_score`, `override_flag`) stay
genuinely `None` on every row this system writes today — not omitted
from the schema (a later model landing must never need a migration just
to have somewhere to write its own frozen state), just honestly empty
until the layer that produces them exists. See `app.domain.decision_
record_view`'s own module docstring for exactly which fields ARE real
today and where each one comes from.

Every column below is named to match §45's own schema comment verbatim,
so a reader can check this model against the spec line by line."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Index, JSON, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DecisionAction


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
    # Declared here to match what the migrations actually created. These
    # indexes existed in the database but not on the model, so
    # `alembic revision --autogenerate` would have emitted a migration
    # DROPPING them (found in the 29 Aug audit via `alembic check`).
        Index("ix_decisions_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    """Deliberately NOT a foreign key to `securities` — same reasoning as
    `PortfolioPosition.ticker`: a decision recorded about a name that is
    later delisted must remain readable, not orphaned by a cascading
    delete or blocked by a constraint."""

    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """§45: "config_hash" — meant to identify which exact model
    configuration produced the frozen state below, so a later
    re-computation can tell "the model changed" apart from "the world
    changed". This system has no versioned model-configuration registry
    yet (every parameter in `app.config.Settings` is a live default, not
    a hashed, stored config), so this is `None` on every row today,
    disclosed rather than filled with a value that would falsely imply
    reproducibility this system doesn't yet guarantee."""

    action: Mapped[DecisionAction] = mapped_column(Enum(DecisionAction), nullable=False)
    size_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    conviction_1_5: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """§45: "lets you later test whether your own confidence is
    calibrated — most people's is not, and finding out is worth a great
    deal." Never computed by this system; always the human's own
    real-time self-assessment, 1-5."""

    reasoning_text: Mapped[str] = mapped_column(Text, nullable=False)
    falsification_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """§45: "what would prove me wrong?" — "written before the trade, is
    what makes post-mortems honest instead of retrospective
    storytelling." Nullable because not every action (a `pass`, say)
    necessarily has one, but the domain layer strongly encourages it for
    `buy`."""

    # --- Full model state frozen at decision time (§45's own schema) --------
    fundamental_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    pillar_scores_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    integrity_flags_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """The three fields above stay `None` on every row today — §38's
    composite score and §14's automated integrity veto don't exist
    yet."""

    fv_by_method_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """REAL: `{anchor_name: fair_value_per_share}` from `app.domain.
    triangulation`'s own real anchors at decision time — e.g. `{"Justified
    P/B": "93.05", "Residual income": "88.20"}`."""

    fv_blended: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    dispersion: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    mos_components_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """REAL: `app.domain.margin_of_safety`'s own component breakdown
    (base/dispersion/liquidity/regime/quality_integrity/data_completeness
    pct, and `is_lower_bound`) at decision time."""

    buy_below: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    fair_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    trim_above: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    """REAL, from `app.domain.price_ladder`'s own real result at decision
    time: `buy_below` = `buy_below_price`, `fair_value` =
    `trim_threshold` (this implementation's own fair value, per §26),
    `trim_above` = `exit_threshold`."""

    timing_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    timing_branch: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timing_signals_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """§37's timing/contrarian battery doesn't exist yet — always
    `None`."""

    macro_regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    macro_prob: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    sector_fit: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    """`macro_regime`/`macro_prob` ARE real, live reads from `app.domain.
    macro_engine_view.regime_for` when it can fit one — but see that
    function's own docstring for the standing, disclosed caveat: this
    system's real macro series don't yet span enough history to validate
    the classifier against a known historical Sri Lankan regime, so a
    non-`None` value here is a real live statistical fit, not yet a
    validated one. `sector_fit` stays `None` — no ticker-level sector-
    sensitivity read exists in a form this field could hold yet (§33's
    matrix is sector-wide, not per-ticker)."""

    alpha: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    alpha_tstat: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    betas_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    residual_vol: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    """§36's Carhart certification doesn't exist yet — always `None`."""

    market_price_at_decision: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    """REAL: the latest real `PriceDaily.close` on or before the decision
    date."""

    data_completeness_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    agreement_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    override_flag: Mapped[bool | None] = mapped_column(nullable=True)
    """`data_completeness_pct` (§8: "a data-completeness percentage on
    every company card") and `agreement_score` ("how aligned the layers
    were") have no formally-defined computation anywhere in this system
    yet — inventing an undisclosed formula here would be exactly the
    kind of silent guess this whole project refuses, so both stay
    `None`. `override_flag` ("did the human go against the composite?")
    is uncomputable by definition until §38's composite score exists to
    compare against — always `None`, never inferred."""

    outcome: Mapped["Outcome | None"] = relationship(
        back_populates="decision", uselist=False, cascade="all, delete-orphan"
    )
    """`cascade="all, delete-orphan"` — without it, SQLAlchemy's default
    one-to-one behaviour on delete is to NULL the child's foreign key
    rather than delete the child, which fails outright here since
    `Outcome.decision_id` is `nullable=False` (a real error found live
    while cleaning up a test row: `NOT NULL constraint failed: outcomes.
    decision_id`). No real application code path deletes a `Decision`
    today — both rows are meant to be permanent, matching Design Law
    2 — but an orphaned `Outcome` pointing at a deleted decision would be
    real data corruption if one ever did, so the cascade is configured
    correctly regardless of whether anything calls it yet."""


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False, unique=True)

    exit_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    exit_trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    """Free text today — §28's five formal exit triggers don't exist as
    an enumerable set yet, so this records the human's own real,
    honest description of why (e.g. "hit buy-below-derived target",
    "thesis broken", "needed cash") rather than forcing a choice from a
    list that doesn't yet correspond to anything this system computed."""

    gross_return: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    net_return: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    """REAL: `net_return` applies `settings.round_trip_transaction_cost_
    pct` (§2.1's own sourced figure) to `gross_return` — see
    `app.domain.decision_record_view.record_outcome_for`'s own
    docstring for the exact arithmetic."""

    holding_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_adverse_excursion: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    max_favourable_excursion: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    """REAL when real daily price history exists for the whole holding
    period: the worst/best real close-to-close return relative to
    `market_price_at_decision` seen on any day between decision and
    exit, from `PriceDaily`. `None` when the real price history doesn't
    fully cover the holding period, named rather than computed from a
    partial window and passed off as complete."""

    attribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """§45: "model / execution / macro / luck" decomposition — needs the
    Carhart/macro machinery §36/§29-34 haven't finished providing at the
    per-decision level yet. Always `None`."""

    decision: Mapped["Decision"] = relationship(back_populates="outcome")
