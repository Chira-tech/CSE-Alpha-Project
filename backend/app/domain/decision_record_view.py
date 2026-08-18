"""
Master Spec §45: the decision record. See `app.models.decisions`'s own
module docstring for the full field-by-field picture of what's real
today versus genuinely `None` because the layer that would compute it
(§38 composite score, §36 Carhart, §37 timing) doesn't exist yet.

`record_decision_for` is the one function this whole module exists to
make trivially easy to call correctly: freeze whatever real state THIS
system can compute right now — triangulation, margin of safety, the
price ladder, the live price, and (with a disclosed caveat) the regime
read — at the exact moment a real decision is made. The spec's own
words on why this matters more than it looks: "Every decision you make
without a recorded rationale is a data point you can never recover."
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.macro_engine_view import regime_for
from app.domain.valuation_view import valuation_summary_for
from app.models.decisions import Decision, Outcome
from app.models.enums import DecisionAction
from app.models.prices import PriceDaily
from app.models.securities import Security


def _latest_price(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def _jsonable(value: Decimal | None) -> str | None:
    """JSON has no Decimal type; every `*_json` field stores strings for
    its numeric leaves so `json.dumps` never silently rounds a real
    figure to a float. `None` passes through unchanged."""
    return str(value) if value is not None else None


def record_decision_for(
    db: Session,
    ticker: str,
    action: DecisionAction,
    reasoning_text: str,
    *,
    as_of: dt.date | None = None,
    size_pct: Decimal | None = None,
    limit_price: Decimal | None = None,
    conviction_1_5: int | None = None,
    falsification_text: str | None = None,
) -> Decision:
    """Freezes real, live model state for `ticker` at `as_of` (today by
    default) and stores it as a new, permanent `Decision` row — never
    updated in place afterwards; a later re-think is a NEW decision, not
    an edit, so the frozen record stays exactly what it says: the state
    as it genuinely was at the moment of the real decision."""
    stamp = as_of or dt.date.today()
    security = db.get(Security, ticker)
    archetype = security.archetype if security is not None else None
    price = _latest_price(db, ticker, stamp)

    summary = valuation_summary_for(db, ticker, archetype, price, stamp)
    ladder = summary.price_ladder
    mos = summary.margin_of_safety

    # `TriangulationResult` (`summary.triangulation`) only keeps category
    # AVERAGES, not the individual per-method anchors that fed them — so
    # this reads the same three real anchor sources `valuation_summary_
    # for` itself builds `ValuationAnchor`s from, mirroring its own
    # "Justified P/B" / "Residual income" / "FCFF DCF" labels exactly
    # rather than inventing new ones.
    fv_by_method: dict[str, str] = {}
    if summary.justified_pb.fair_value_per_share is not None:
        fv_by_method["Justified P/B"] = _jsonable(summary.justified_pb.fair_value_per_share)
    if summary.residual_income.result is not None and summary.residual_income.result.value_per_share is not None:
        fv_by_method["Residual income"] = _jsonable(summary.residual_income.result.value_per_share)
    if summary.dcf.fair_value_per_share is not None:
        fv_by_method["FCFF DCF"] = _jsonable(summary.dcf.fair_value_per_share)

    regime_view = regime_for(db, stamp)
    macro_regime = regime_view.result.label if regime_view.result is not None else None
    macro_prob = (
        regime_view.result.probabilities[regime_view.result.label]
        if regime_view.result is not None
        else None
    )

    # The DATE component must track `stamp`, not real wall-clock "now" —
    # `record_outcome_for`'s `holding_days` and `_excursions`' price-
    # history window both derive from `decision.timestamp.date()`, and a
    # caller backfilling a real past decision (or a test fixing `as_of`
    # in the past) would otherwise get a `timestamp` days or years ahead
    # of the state it actually froze, silently producing nonsense
    # holding periods. Real time-of-day is kept for ordinary same-day
    # use, where `stamp` already defaults to today.
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = dt.datetime.combine(stamp, now.time(), tzinfo=dt.timezone.utc)

    decision = Decision(
        ticker=ticker,
        timestamp=timestamp,
        config_hash=None,  # see app/models/decisions.py's own docstring
        action=action,
        size_pct=size_pct,
        limit_price=limit_price,
        conviction_1_5=conviction_1_5,
        reasoning_text=reasoning_text,
        falsification_text=falsification_text,
        fundamental_score=None,
        pillar_scores_json=None,
        integrity_flags_json=None,
        fv_by_method_json=fv_by_method or None,
        fv_blended=summary.triangulation.blended_fair_value_per_share,
        dispersion=summary.triangulation.dispersion_pct,
        mos_components_json={
            "base_pct": _jsonable(mos.base_pct),
            "dispersion_pct": _jsonable(mos.dispersion_pct),
            "liquidity_pct": _jsonable(mos.liquidity_pct),
            "regime_pct": _jsonable(mos.regime_pct),
            "quality_integrity_pct": _jsonable(mos.quality_integrity_pct),
            "data_completeness_pct": _jsonable(mos.data_completeness_pct),
            "total_pct": _jsonable(mos.total_pct),
            "is_lower_bound": mos.is_lower_bound,
        },
        buy_below=ladder.buy_below_price if ladder is not None else None,
        fair_value=ladder.trim_threshold if ladder is not None else None,
        trim_above=ladder.exit_threshold if ladder is not None else None,
        timing_score=None,
        timing_branch=None,
        timing_signals_json=None,
        macro_regime=macro_regime,
        macro_prob=macro_prob,
        sector_fit=None,
        alpha=None,
        alpha_tstat=None,
        betas_json=None,
        residual_vol=None,
        market_price_at_decision=price,
        data_completeness_pct=None,
        agreement_score=None,
        override_flag=None,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def record_outcome_for(
    db: Session, decision_id: int, exit_date: dt.date, exit_price: Decimal, exit_trigger: str
) -> Outcome | None:
    """`None` (never a fabricated outcome) when `decision_id` doesn't
    exist or already has one — an outcome is recorded exactly once per
    decision, exactly like the decision itself is never edited in
    place."""
    decision = db.get(Decision, decision_id)
    if decision is None or decision.outcome is not None:
        return None
    if decision.market_price_at_decision is None:
        return None  # nothing to compute a return FROM — named, not guessed at zero

    entry_price = decision.market_price_at_decision
    gross_return = (exit_price - entry_price) / entry_price
    net_return = gross_return - settings.round_trip_transaction_cost_pct
    holding_days = (exit_date - decision.timestamp.date()).days

    mae, mfe = _excursions(db, decision.ticker, decision.timestamp.date(), exit_date, entry_price)

    outcome = Outcome(
        decision_id=decision_id,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_trigger=exit_trigger,
        gross_return=gross_return,
        net_return=net_return,
        holding_days=holding_days,
        max_adverse_excursion=mae,
        max_favourable_excursion=mfe,
        attribution_json=None,  # §36/§29-34's per-decision attribution doesn't exist yet
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def _excursions(
    db: Session, ticker: str, start: dt.date, end: dt.date, entry_price: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """Real worst/best close-to-close return relative to `entry_price`
    across every real `PriceDaily` row strictly between `start` and
    `end` inclusive. `(None, None)` when no real price rows exist in
    the window at all — never a computed value from an empty series."""
    rows = db.scalars(
        select(PriceDaily.close)
        .where(
            PriceDaily.ticker == ticker,
            PriceDaily.date >= start,
            PriceDaily.date <= end,
            PriceDaily.close.is_not(None),
        )
    ).all()
    if not rows:
        return None, None
    returns = [(close - entry_price) / entry_price for close in rows]
    return min(returns), max(returns)


def list_decisions(db: Session) -> list[Decision]:
    return list(db.scalars(select(Decision).order_by(Decision.timestamp.desc())).all())


def get_decision(db: Session, decision_id: int) -> Decision | None:
    return db.get(Decision, decision_id)
