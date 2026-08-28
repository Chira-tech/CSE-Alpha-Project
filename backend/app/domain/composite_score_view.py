"""
DB-wired glue for `app.domain.composite_score` (pure) — the per-ticker
aggregator behind `GET /composite-score/{ticker}`. Mirrors `app.domain.
valuation_view.valuation_summary_for`'s own shape: one function pulling
together several already-real modules' outputs into one frozen summary,
never computing a valuation/percentile/gate itself.

A REAL, MEASURED COST CONSTRAINT SHAPED THIS MODULE, NOT JUST A DATA GAP.
§38's Valuation pillar (discount to blended fair value) is, in
principle, percentile-rankable the same way Business quality and
Financial strength are below. In practice, ranking it needs every OTHER
ticker's same figure computed too — a full `valuation_summary_for` pass
across the whole universe, which `app.domain.opportunity_ranking_view`
already measured at ~30s even with its own shared-cache optimizations
(verified live against this app's own running `/opportunities` endpoint
while building this module). Redoing that inside a SINGLE-ticker
interactive request would be a real latency regression, not a cost this
endpoint should eat silently. Growth's own rankable input (§34's
national-projects revenue adjustment) has the same principled shape, AND
real register coverage is sparse enough today (fewer than 3 tickers have
any confirmed impact at all) that the same-cost universe pass would
almost certainly come back "too few peers" regardless. Both pillars are
therefore real EVIDENCE here — the figures a caller would actually want
to see — but excluded from `total_score`, with the cost reason named
explicitly on their own `PillarScore.reason`, never silently folded into
a generic "not yet built."
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.composite_score import (
    BUSINESS_QUALITY_RATIO_KEYS,
    FINANCIAL_STRENGTH_INVERT,
    FINANCIAL_STRENGTH_RATIO_KEYS,
    PILLAR_SPECS_BY_KEY,
    mean_of_available,
    renormalize,
)
from app.domain.fundamentals_view import RatioTrend, ratio_trends_for
from app.domain.liquidity_view import liquidity_percentile_for
from app.domain.macro_engine_view import regime_for
from app.domain.macro_sector_fit_view import macro_sector_fit_for
from app.domain.national_projects_view import confirmed_base_case_impacts_for
from app.domain.sector_percentiles_view import sector_percentiles_for
from app.domain.timing_battery import TimingBatteryResult
from app.domain.timing_battery_view import timing_battery_for
from app.domain.valuation_view import CompanyValuationSummary, valuation_summary_for
from app.models.national_projects import NationalProjectTickerImpact
from app.models.prices import PriceDaily
from app.models.securities import Security

#: §37.2's own crash-guard trigger: Risk-Off with a RISING transition
#: probability to Risk-On. No rolling regime-probability accessor exists
#: (see `app.domain.regime_classification.MarkovRegimeRead`'s own
#: docstring — `current_probabilities` is only ever "as of the last
#: observation"), so this compares two independent point-in-time
#: `regime_for` calls, `CRASH_GUARD_LOOKBACK_DAYS` apart — a real,
#: disclosed substitute for a true continuous trend, not a fabricated one.
CRASH_GUARD_LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class PillarScore:
    key: str
    label: str
    weight_pct: Decimal
    """This pillar's §38-specified weight — NOT what it actually
    contributed after renormalization; see `CompositeScoreView.weight_
    used_pct` for that."""
    score: Decimal | None
    """0-100, or `None` when `included` is False."""
    included: bool
    reason: str | None
    """Set whenever `included` is False — either `PillarSpec.always_
    excluded_reason` (a fixed, design-level reason) or a per-ticker
    reason computed here (e.g. "no sector-relative percentile available
    for any business-quality ratio")."""


@dataclass(frozen=True)
class IntegrityView:
    evaluable: bool
    vetoed: bool
    reason: str


@dataclass(frozen=True)
class CompositeScoreView:
    ticker: str
    as_of: dt.date
    pillars: tuple[PillarScore, ...]
    total_score: Decimal | None
    weight_used_pct: dict[str, Decimal]
    """How much of the renormalized 100% each INCLUDED pillar actually
    counted for — `app.domain.composite_score.renormalize`'s own second
    return value, surfaced so a caller never has to reverse-engineer it
    from `pillars` alone."""
    is_partial: bool
    """`True` whenever any of the 7 pillars is excluded — which is
    ALWAYS true today, since Valuation and Growth remain structurally
    excluded by their own real cost constraint (see `PILLAR_SPECS` and
    this module's own docstring); the other 5 pillars are now genuinely
    per-ticker (missing only when THIS ticker's own real data is thin)."""
    integrity: IntegrityView
    valuation_summary: CompanyValuationSummary | None
    """Kept on the view (not flattened) so the API layer can surface
    real Valuation-pillar EVIDENCE (blended fair value, dispersion,
    price-ladder zone, regime) even though the pillar itself is
    excluded from `total_score` — see this module's own docstring for
    why."""
    growth_ratio_trends: dict[str, RatioTrend]
    """Real §13 trend evidence for the Growth pillar — shown, never
    ranked (see module docstring)."""
    growth_project_impacts: tuple[NationalProjectTickerImpact, ...]
    """This ticker's own confirmed §34 register impacts, if any — real
    evidence for the Growth pillar, same reason as above."""
    timing_battery: TimingBatteryResult
    """§37's full signal-by-signal breakdown, contrarian check and
    crash-guard state — kept on the view (not flattened into the pillar
    score alone) so a caller can see exactly which real signals fed
    (or didn't feed) the Timing & momentum pillar."""


def _crash_guard_active(db: Session, as_of: dt.date) -> bool:
    """§37.2's own real trigger, from two independent point-in-time
    regime reads — see module-level constant's own docstring for why
    this is the honest substitute for a true rolling probability."""
    now_view = regime_for(db, as_of)
    earlier_view = regime_for(db, as_of - dt.timedelta(days=CRASH_GUARD_LOOKBACK_DAYS))
    if now_view.result is None or earlier_view.result is None:
        return False
    if now_view.result.label != "risk_off":
        return False
    p_risk_on_now = now_view.result.probabilities.get("risk_on")
    p_risk_on_earlier = earlier_view.result.probabilities.get("risk_on")
    if p_risk_on_now is None or p_risk_on_earlier is None:
        return False
    return p_risk_on_now > p_risk_on_earlier


def _latest_price(db: Session, ticker: str, as_of: dt.date) -> Decimal | None:
    return db.scalar(
        select(PriceDaily.close)
        .where(PriceDaily.ticker == ticker, PriceDaily.date <= as_of, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    )


def _ratio_pillar_score(
    percentiles: dict, ratio_keys: tuple[str, ...], invert: frozenset[str]
) -> tuple[Decimal | None, list[str]]:
    """Mean of whichever `ratio_keys` have a real sector percentile for
    this ticker, inverting the ones named in `invert` first (§38's
    Financial strength pillar: lower leverage is the stronger position —
    see `FINANCIAL_STRENGTH_INVERT`'s own docstring). Returns
    `(score, contributing_ratio_keys)` so the caller can name exactly
    which ratios fed the number, the same "never one opaque figure"
    discipline every other blended value in this codebase already
    follows."""
    values: list[Decimal | None] = []
    contributing: list[str] = []
    for key in ratio_keys:
        result = percentiles.get(key)
        if result is None or result.percentile is None:
            continue
        pct = Decimal(100) - result.percentile if key in invert else result.percentile
        values.append(pct)
        contributing.append(key)
    return mean_of_available(values), contributing


def composite_score_for(
    db: Session, ticker: str, as_of: dt.date | None = None
) -> CompositeScoreView | None:
    """`None` only when the ticker itself doesn't exist — the caller
    (the API route) is expected to have already 404'd on that, matching
    every other per-ticker view in this codebase; this function assumes
    a real `Security` row and returns a `CompositeScoreView` with every
    pillar excluded when the ticker simply has no usable data, never a
    bare `None` for "no data" (that would be indistinguishable from
    "unknown ticker")."""
    security = db.get(Security, ticker)
    if security is None:
        return None

    stamp = as_of or dt.date.today()
    price = _latest_price(db, ticker, stamp)
    valuation_summary = valuation_summary_for(db, ticker, security.archetype, price, stamp)
    percentiles = sector_percentiles_for(db, ticker, stamp)

    pillar_scores: dict[str, Decimal | None] = {}
    pillars: list[PillarScore] = []

    # --- Valuation (25%) — evidence only; see module docstring for the
    # real, measured cost reason a universe-wide rank isn't computed here.
    pillars.append(
        PillarScore(
            "valuation", PILLAR_SPECS_BY_KEY["valuation"].label, PILLAR_SPECS_BY_KEY["valuation"].weight_pct,
            None, False,
            "Ranking this ticker's discount to fair value against the rest of the universe "
            "needs a full valuation pass for every ticker — measured at ~30s even with this "
            "app's own shared-cache optimizations (see GET /opportunities). Redoing that on "
            "every single-ticker request would be a real latency regression, so this pillar "
            "is shown as evidence (blended fair value, dispersion, price-ladder zone, regime) "
            "but not ranked or blended into the score.",
        )
    )

    # --- Business quality (25%)
    bq_score, bq_ratios = _ratio_pillar_score(percentiles, BUSINESS_QUALITY_RATIO_KEYS, frozenset())
    pillar_scores["business_quality"] = bq_score
    pillars.append(
        PillarScore(
            "business_quality", PILLAR_SPECS_BY_KEY["business_quality"].label,
            PILLAR_SPECS_BY_KEY["business_quality"].weight_pct,
            bq_score, bq_score is not None,
            None if bq_score is not None else (
                "No sector-relative percentile available for any business-quality ratio "
                f"({', '.join(BUSINESS_QUALITY_RATIO_KEYS)}) — needs confirmed fundamentals "
                "for this ticker and at least 3 sector peers with the same ratio computable."
            ),
        )
    )

    # --- Growth (15%) — evidence only; see module docstring.
    pillars.append(
        PillarScore(
            "growth", PILLAR_SPECS_BY_KEY["growth"].label, PILLAR_SPECS_BY_KEY["growth"].weight_pct,
            None, False,
            "Ranking §34's national-projects revenue-growth adjustment against the universe "
            "has the same cost shape as Valuation above, AND real register coverage is sparse "
            "enough today (fewer than 3 tickers have any confirmed impact) that the same-cost "
            "pass would almost certainly come back \"too few peers\" regardless — shown as "
            "evidence (real ratio trends, and this ticker's own project impacts if any) but "
            "not ranked or blended into the score.",
        )
    )

    # --- Financial strength (10%)
    fs_score, fs_ratios = _ratio_pillar_score(
        percentiles, FINANCIAL_STRENGTH_RATIO_KEYS, FINANCIAL_STRENGTH_INVERT
    )
    pillar_scores["financial_strength"] = fs_score
    pillars.append(
        PillarScore(
            "financial_strength", PILLAR_SPECS_BY_KEY["financial_strength"].label,
            PILLAR_SPECS_BY_KEY["financial_strength"].weight_pct,
            fs_score, fs_score is not None,
            None if fs_score is not None else (
                "No sector-relative percentile available for any financial-strength ratio "
                f"({', '.join(FINANCIAL_STRENGTH_RATIO_KEYS)})."
            ),
        )
    )

    # --- Macro & sector fit (10%) — real, per-ticker, as of this session.
    macro_fit = macro_sector_fit_for(db, ticker, stamp)
    pillar_scores["macro_sector_fit"] = macro_fit.score
    pillars.append(
        PillarScore(
            "macro_sector_fit", PILLAR_SPECS_BY_KEY["macro_sector_fit"].label,
            PILLAR_SPECS_BY_KEY["macro_sector_fit"].weight_pct,
            macro_fit.score, macro_fit.score is not None, macro_fit.reason,
        )
    )

    # --- Timing & momentum (10%) — real, per-ticker, as of this session.
    # Uses the Business quality score just computed above (bq_score) for
    # §37.1's own condition 2 rather than recomputing it a second time.
    crash_guard_active = _crash_guard_active(db, stamp)
    timing_result = timing_battery_for(
        db, ticker, stamp, business_quality_score=bq_score, crash_guard_active=crash_guard_active,
    )
    pillar_scores["timing_momentum"] = timing_result.composite_score
    pillars.append(
        PillarScore(
            "timing_momentum", PILLAR_SPECS_BY_KEY["timing_momentum"].label,
            PILLAR_SPECS_BY_KEY["timing_momentum"].weight_pct,
            timing_result.composite_score, timing_result.composite_score is not None,
            None if timing_result.composite_score is not None else (
                "None of this battery's 6 signals were computable yet for this ticker — "
                "see timing_battery.signals for exactly why each one is missing."
            ),
        )
    )

    # --- Risk (5%) — Amihud liquidity percentile only; beta is real
    # evidence elsewhere (GET /securities/{ticker}'s cost_of_equity
    # block) but not re-fetched or folded in here — no benchmark-free
    # way to score "is this beta good" without inventing a judgment
    # this pillar doesn't need to make.
    risk_score = liquidity_percentile_for(db, ticker, stamp)
    pillar_scores["risk"] = risk_score
    pillars.append(
        PillarScore(
            "risk", PILLAR_SPECS_BY_KEY["risk"].label, PILLAR_SPECS_BY_KEY["risk"].weight_pct,
            risk_score, risk_score is not None,
            None if risk_score is not None else (
                "Not enough real price/turnover history to compute an Amihud illiquidity "
                "ratio for this ticker yet."
            ),
        )
    )

    total_score, weight_used = renormalize(pillar_scores)

    # Integrity: NEVER computed via `evaluate_gate3_integrity` here — that
    # function's own `Gate3Inputs` requires real booleans (qualified audit
    # opinion, going-concern emphasis, auditor-change-plus-CFO-departure)
    # this system extracts nowhere; supplying `False` as a default would
    # be reporting "no red flag found" when the true state is "never
    # looked," exactly the fabricated-confidence law this whole module
    # exists to avoid. Reported honestly unevaluable instead.
    integrity = IntegrityView(
        evaluable=False,
        vetoed=False,
        reason=(
            "No audit-opinion, going-concern, auditor-change, Beneish M-Score or "
            "related-party data is extracted anywhere in this system yet (see `app.domain."
            "ratios.NOT_YET_COMPUTABLE`) — Gate 3 cannot be evaluated, so it is reported as "
            "unevaluable rather than assumed to pass."
        ),
    )

    return CompositeScoreView(
        ticker=ticker,
        as_of=stamp,
        pillars=tuple(pillars),
        total_score=total_score,
        weight_used_pct=weight_used,
        is_partial=True,  # always true today — see module/class docstrings
        integrity=integrity,
        valuation_summary=valuation_summary,
        growth_ratio_trends=ratio_trends_for(db, ticker, stamp),
        growth_project_impacts=tuple(confirmed_base_case_impacts_for(db, ticker, stamp)),
        timing_battery=timing_result,
    )
