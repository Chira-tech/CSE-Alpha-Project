"""
Master Spec Part C — coverage tiers and gate definitions (§10, §11, §11.1).

Every listed company gets a full company file (§10 "Resolution"); these
gates decide *capital eligibility*, not analysis coverage, and they are
computed and explained, never silently applied. Gate 3 (integrity) is a
hard veto and must never be folded into a weighted score — §11.1 is
explicit about why: "If integrity is a scored input, a sufficiently
attractive valuation will always outvote it."
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

from app.config import settings
from app.domain.instrument_type import COMMON_EQUITY, InstrumentType
from app.models.enums import CoverageTier


@dataclasses.dataclass(frozen=True)
class Gate1Inputs:
    median_daily_turnover_60d_lkr: Decimal
    days_traded_last_60: int
    amihud_illiquidity_percentile: Decimal  # this stock's percentile within the universe, 0-1
    position_value_lkr: Decimal
    adv_20d_lkr: Decimal


@dataclasses.dataclass(frozen=True)
class Gate1Result:
    passed: bool
    reasons_failed: tuple[str, ...]
    max_position_pct_of_adv_cap: Decimal


def evaluate_gate1_liquidity(inputs: Gate1Inputs) -> Gate1Result:
    reasons: list[str] = []

    if inputs.median_daily_turnover_60d_lkr < settings.gate1_min_median_daily_turnover_lkr:
        reasons.append(
            f"median 60d turnover {inputs.median_daily_turnover_60d_lkr:,.0f} LKR "
            f"< required {settings.gate1_min_median_daily_turnover_lkr:,.0f} LKR"
        )

    if inputs.days_traded_last_60 < settings.gate1_min_days_traded_of_60:
        reasons.append(
            f"traded {inputs.days_traded_last_60}/60 sessions "
            f"< required {settings.gate1_min_days_traded_of_60}"
        )

    if inputs.amihud_illiquidity_percentile > settings.gate1_amihud_max_percentile:
        reasons.append(
            f"Amihud illiquidity at {inputs.amihud_illiquidity_percentile:.0%} percentile "
            f"> universe {settings.gate1_amihud_max_percentile:.0%} cutoff"
        )

    if inputs.adv_20d_lkr > 0:
        position_pct_of_adv = inputs.position_value_lkr / inputs.adv_20d_lkr
        if position_pct_of_adv > settings.gate1_max_position_pct_of_adv:
            reasons.append(
                f"position would be {position_pct_of_adv:.1%} of 20d ADV "
                f"> cap {settings.gate1_max_position_pct_of_adv:.0%}"
            )

    return Gate1Result(
        passed=not reasons,
        reasons_failed=tuple(reasons),
        max_position_pct_of_adv_cap=settings.gate1_max_position_pct_of_adv,
    )


def gate1_liquidity_reason(
    median_daily_turnover_60d_lkr: Decimal, days_traded_60d: int, *, days_of_real_history_available: int
) -> str | None:
    """The two POSITION-INDEPENDENT halves of `evaluate_gate1_liquidity`
    above (median turnover, days traded), for a caller that has no
    specific position to size — TASK "are these opportunities really
    worth buying" found live (30 Aug 2026) that `app.domain.
    opportunity_ranking_view` was ranking real candidates by discount-
    to-book alone, with NO liquidity check at all: the real top-ranked
    "Accumulate" candidates included tickers trading LKR 5,000-200,000/
    day, far below this gate's own LKR 2,000,000 bar — stocks that are
    not practically buyable at any meaningful size regardless of how
    real the valuation discount is.

    `days_of_real_history_available` is REQUIRED, not optional, for a
    real reason found live applying this very fix, in two layers: first,
    treating "60" as 60 CALENDAR days made the days-traded check
    mathematically impossible for any real ticker to pass at all (a
    60-calendar-day span holds at most ~43 weekdays, never 45) — fixed
    in `app.domain.liquidity_view.liquidity_snapshot_for` by windowing
    on real SESSION ROWS instead (see that module's own `GATE1_WINDOW_
    SESSIONS` docstring). Second, even measured correctly by sessions,
    this system's own forward-captured price history (§52's EOD
    snapshot job has been running for a real, but still limited, number
    of weeks) doesn't yet hold 60 real session rows for anyone — so the
    days-traded check is only evaluated once `days_of_real_history_
    available` itself reaches the full 60-session window; before that,
    this real, temporary, disclosed data-depth limit is honestly named
    as "not yet evaluable" (skipped, like every other rule this project
    skips rather than silently passes or fails on absent data) rather
    than used to fail every real candidate.

    Deliberately does NOT evaluate the OTHER two `Gate1Inputs` checks
    (Amihud illiquidity percentile, position-vs-ADV cap) — the first
    needs a real universe-wide computation a ranking pass doesn't
    otherwise require, the second needs a hypothetical position size no
    company-level ranking has. Reuses `evaluate_gate1_liquidity`'s own
    configured thresholds (`settings.gate1_min_median_daily_turnover_
    lkr`/`gate1_min_days_traded_of_60`) directly rather than a second,
    independently-chosen pair of numbers that could silently diverge
    from the real Gate 1 definition.

    `None` when every real, evaluable check passes; otherwise a human-
    readable reason naming which failed and by how much, per this
    project's own "never a black box" rule."""
    reasons: list[str] = []
    if median_daily_turnover_60d_lkr < settings.gate1_min_median_daily_turnover_lkr:
        reasons.append(
            f"median turnover over the last 60 real sessions LKR "
            f"{median_daily_turnover_60d_lkr:,.0f} < required LKR "
            f"{settings.gate1_min_median_daily_turnover_lkr:,.0f}"
        )
    if days_of_real_history_available >= 60 and days_traded_60d < settings.gate1_min_days_traded_of_60:
        reasons.append(
            f"traded {days_traded_60d} of the last 60 real sessions < required "
            f"{settings.gate1_min_days_traded_of_60}"
        )
    return "; ".join(reasons) if reasons else None


@dataclasses.dataclass(frozen=True)
class Gate2Inputs:
    instrument_type: InstrumentType = dataclasses.field(
        default=InstrumentType.ORDINARY, kw_only=True
    )
    """What the ticker actually is. `tradeSummary` returns every line that
    traded, including non-voting shares, closed-end fund units and rights
    — none of which a valuation model may be pointed at unchecked. See
    `app.domain.instrument_type`."""

    free_float_pct: Decimal | None
    """None means "not known yet", not "zero" — the quarterly
    shareholding disclosure that carries it (§5) may not be ingested for
    this company. A hard gate must never pass on absent evidence, so an
    unknown float FAILS the gate with an explicit reason rather than
    being waved through."""

    on_watch_list: bool
    trading_suspended: bool
    months_listed: int
    market_cap_lkr: Decimal | None
    consecutive_quarters_history: int


@dataclasses.dataclass(frozen=True)
class Gate2Result:
    passed: bool
    reasons_failed: tuple[str, ...]


def evaluate_gate2_structural(inputs: Gate2Inputs) -> Gate2Result:
    reasons: list[str] = []

    # Checked first: if the line is not common equity, the remaining
    # tests are not merely failed, they are meaningless. A rights line has
    # no free float and a fund unit has no reporting history, so reporting
    # those as ordinary gate failures would suggest the instrument might
    # qualify once the data improves. It never will.
    if inputs.instrument_type not in COMMON_EQUITY:
        return Gate2Result(
            passed=False,
            reasons_failed=(
                f"not common equity — {inputs.instrument_type.value} lines are outside "
                f"the investable universe",
            ),
        )

    if inputs.free_float_pct is None:
        reasons.append("free float unknown — no shareholding disclosure ingested for this company")
    elif inputs.free_float_pct < settings.gate2_min_free_float_pct:
        reasons.append(f"free float {inputs.free_float_pct:.1%} < required {settings.gate2_min_free_float_pct:.0%}")
    if inputs.on_watch_list:
        reasons.append("on CSE Watch List")
    if inputs.trading_suspended:
        reasons.append("trading suspended")
    if inputs.months_listed < settings.gate2_min_months_listed:
        reasons.append(f"listed {inputs.months_listed}m < required {settings.gate2_min_months_listed}m")
    if inputs.market_cap_lkr is None:
        reasons.append("market cap unknown")
    elif inputs.market_cap_lkr < settings.gate2_min_market_cap_lkr:
        reasons.append(
            f"market cap {inputs.market_cap_lkr:,.0f} LKR < required {settings.gate2_min_market_cap_lkr:,.0f} LKR"
        )
    if inputs.consecutive_quarters_history < settings.gate2_min_quarters_history:
        reasons.append(
            f"only {inputs.consecutive_quarters_history} consecutive quarters of history "
            f"< required {settings.gate2_min_quarters_history}"
        )

    return Gate2Result(passed=not reasons, reasons_failed=tuple(reasons))


@dataclasses.dataclass(frozen=True)
class Gate3Inputs:
    qualified_audit_opinion: bool
    going_concern_emphasis: bool
    auditor_change_and_cfo_departure_same_12m: bool
    beneish_m_score: Decimal | None
    related_party_revenue_or_receivables_pct: Decimal | None


@dataclasses.dataclass(frozen=True)
class Gate3Result:
    passed: bool
    reasons_failed: tuple[str, ...]


def evaluate_gate3_integrity(inputs: Gate3Inputs) -> Gate3Result:
    """Hard veto. §11.1: "Any one of these excludes the name from capital
    regardless of how cheap it looks." Deliberately returns a boolean gate,
    never a score — see the module docstring."""
    reasons: list[str] = []

    if inputs.qualified_audit_opinion:
        reasons.append("qualified audit opinion")
    if inputs.going_concern_emphasis:
        reasons.append("emphasis-of-matter on going concern")
    if inputs.auditor_change_and_cfo_departure_same_12m:
        reasons.append("auditor change and CFO departure within the same 12 months")
    if inputs.beneish_m_score is not None and inputs.beneish_m_score > settings.gate3_beneish_m_score_threshold:
        reasons.append(
            f"Beneish M-Score {inputs.beneish_m_score} > threshold {settings.gate3_beneish_m_score_threshold}"
        )
    if (
        inputs.related_party_revenue_or_receivables_pct is not None
        and inputs.related_party_revenue_or_receivables_pct > settings.gate3_max_related_party_pct
    ):
        reasons.append(
            f"related-party revenue/receivables {inputs.related_party_revenue_or_receivables_pct:.0%} "
            f"> threshold {settings.gate3_max_related_party_pct:.0%}"
        )

    return Gate3Result(passed=not reasons, reasons_failed=tuple(reasons))


@dataclasses.dataclass(frozen=True)
class CoverageClassification:
    tier: CoverageTier
    reasons: tuple[str, ...]


def classify_coverage_tier(
    *,
    data_completeness_pct: Decimal,
    quarters_of_history: int,
    gate1: Gate1Result | None,
    gate2: Gate2Result,
    gate3: Gate3Result,
) -> CoverageClassification:
    """Master Spec §11 tier table, applied in the order the spec lists it:
    Insufficient data overrides everything else (you cannot gate what you
    cannot measure), then the integrity veto, then structural, then
    liquidity determines Core vs Watch.

    `gate1` is Optional because liquidity metrics may not exist yet for a
    thinly-traded or newly-listed name — that alone should not itself
    produce "Insufficient" (data may be complete on fundamentals even if
    trading data is sparse), but it does mean the name can't be Core.
    """
    if (
        data_completeness_pct < settings.insufficient_data_completeness_floor_pct
        or quarters_of_history < settings.insufficient_min_quarters
    ):
        return CoverageClassification(
            tier=CoverageTier.INSUFFICIENT,
            reasons=(
                f"data completeness {data_completeness_pct:.0%} or history "
                f"{quarters_of_history}q below the floor required to publish a fair value",
            ),
        )

    if not gate3.passed:
        return CoverageClassification(tier=CoverageTier.EXCLUDED, reasons=gate3.reasons_failed)

    if not gate2.passed:
        return CoverageClassification(tier=CoverageTier.EXCLUDED, reasons=gate2.reasons_failed)

    if gate1 is None or not gate1.passed:
        reasons = gate1.reasons_failed if gate1 is not None else ("no liquidity data available",)
        return CoverageClassification(tier=CoverageTier.WATCH, reasons=reasons)

    return CoverageClassification(tier=CoverageTier.CORE, reasons=())
