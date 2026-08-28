"""
§37's momentum & contrarian timing battery, the pure combinator half —
weighted-signal composite, §37.1's contrarian branch, §37.2's crash-guard
reweighting. See `app.domain.timing_battery_view` for the DB-wired
aggregator that computes each real signal value this module blends.

§37's own literal weights (52wk-high 20%, residual momentum 20%,
MOM_12_2 20%, MOM_6_1 15%, REV_1M 15%, volume confirmation 10%) sum to
100 by construction — `mean_of_available`-style renormalization (the
exact pattern `app.domain.composite_score.mean_of_available`/
`renormalize` already establish: weighted mean of whichever signals ARE
real for this ticker, weights renormalized among them, `None` — never a
fabricated 0 — when nothing is computable) applies when a signal is
missing for this ticker (most commonly Residual momentum, which needs a
real Carhart regression that itself needs `MIN_OBSERVATIONS_FOR_CARHART`
real weeks — see `app.domain.carhart_regression`).

§37.1 CONTRARIAN BRANCH — CONDITION 4 IS ALWAYS THE LITERAL STRING
`"unknown"`, NEVER COERCED TO A BOOLEAN. "No negative earnings revision
or adverse disclosure in the last 60 days" has no data source anywhere
in this system — this codebase tracks confirmed fundamentals and
corporate actions, not earnings-revision or disclosure-sentiment
tracking. Treating an unknown condition as satisfied (silently `True`)
would let a real, unassessed risk pass the "baby thrown out with the
bathwater" gate §37.1 exists to protect; treating it as failed (`False`)
would silently disqualify every real contrarian candidate this system
could ever flag. Neither is honest — `"unknown"` is, and
`all_conditions_met` is `False` whenever ANY condition (including this
one) is not a confirmed `True`.

§37.2 CRASH GUARD REWEIGHTING. Spec: "momentum weight is cut to 25% and
contrarian weight is raised" when Risk-Off with a rising transition
probability to Risk-On. This battery's own momentum-FAMILY signals
(52wk-high, residual momentum, MOM_12_2, MOM_6_1 — 75 combined points)
are cut to `CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT` (25 combined, scaled
proportionally within the family so their own relative weights don't
change, only the family total). The freed 50 points go to REV_1M — the
one signal in this battery that IS the contrarian direction (a negative
prior-month return, the same direction §37.1's own bottom-decile
condition tests) — raising it from 15 to `CRASH_GUARD_REV_1M_WEIGHT`
(65). Volume confirmation (10) is untouched; the guard is about
momentum-vs-contrarian balance, not about confirmation signals. Sums to
100 exactly (25+65+10), a real test asserts this.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

SIGNAL_WEIGHTS: dict[str, Decimal] = {
    "week52_high_proximity": Decimal(20),
    "residual_momentum": Decimal(20),
    "mom_12_2": Decimal(20),
    "mom_6_1": Decimal(15),
    "rev_1m": Decimal(15),
    "volume_confirmation": Decimal(10),
}
assert sum(SIGNAL_WEIGHTS.values()) == 100

MOMENTUM_FAMILY_KEYS = frozenset({"week52_high_proximity", "residual_momentum", "mom_12_2", "mom_6_1"})
_MOMENTUM_FAMILY_TOTAL_WEIGHT = sum(SIGNAL_WEIGHTS[k] for k in MOMENTUM_FAMILY_KEYS)  # 75

CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT = Decimal(25)
CRASH_GUARD_REV_1M_WEIGHT = Decimal(65)
CRASH_GUARD_VOLUME_WEIGHT = SIGNAL_WEIGHTS["volume_confirmation"]
assert CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT + CRASH_GUARD_REV_1M_WEIGHT + CRASH_GUARD_VOLUME_WEIGHT == 100

#: §37.1's own bottom-decile threshold for condition 1.
REV_1M_BOTTOM_DECILE_THRESHOLD = Decimal("0.10")
#: §38's own composite-score pass bar, reused verbatim for condition 2
#: ("Fundamental score >= 70") rather than a fresh number invented here.
CONTRARIAN_FUNDAMENTAL_SCORE_FLOOR = Decimal(70)


@dataclass(frozen=True)
class TimingSignal:
    key: str
    value: Decimal | None
    """0-100, higher = stronger timing signal in this battery's own
    convention — see `app.domain.timing_battery_view` for how each real
    signal is normalized onto this scale."""
    weight_pct: Decimal
    included: bool
    reason: str | None


@dataclass(frozen=True)
class ContrarianCheck:
    rev_1m_bottom_decile: bool | None
    business_quality_ge_70: bool | None
    no_integrity_red_flag: bool | None
    no_adverse_disclosure_60d: Literal["unknown"]
    no_active_sector_macro_shock: bool | None
    all_conditions_met: bool


def build_contrarian_check(
    *,
    rev_1m_bottom_decile: bool | None,
    business_quality_ge_70: bool | None,
    no_integrity_red_flag: bool | None,
    no_active_sector_macro_shock: bool | None,
) -> ContrarianCheck:
    """Condition 4 is never a parameter here — it is ALWAYS `"unknown"`,
    structurally, so no caller can accidentally supply a fabricated
    boolean for it."""
    no_adverse_disclosure_60d: Literal["unknown"] = "unknown"
    # ALL FIVE conditions, condition 4 included — it is structurally never
    # `True`, so `all_conditions_met` is structurally always `False` today.
    # This is the honest conclusion, not a bug: §37.1 requires all five to
    # hold, and this system has no data source for condition 4 at all.
    conditions = (
        rev_1m_bottom_decile, business_quality_ge_70, no_integrity_red_flag,
        no_adverse_disclosure_60d, no_active_sector_macro_shock,
    )
    all_met = all(c is True for c in conditions)
    return ContrarianCheck(
        rev_1m_bottom_decile=rev_1m_bottom_decile,
        business_quality_ge_70=business_quality_ge_70,
        no_integrity_red_flag=no_integrity_red_flag,
        no_adverse_disclosure_60d="unknown",
        no_active_sector_macro_shock=no_active_sector_macro_shock,
        all_conditions_met=all_met,
    )


@dataclass(frozen=True)
class TimingBatteryResult:
    signals: tuple[TimingSignal, ...]
    composite_score: Decimal | None
    crash_guard_active: bool
    contrarian: ContrarianCheck


def _effective_weights(crash_guard_active: bool) -> dict[str, Decimal]:
    if not crash_guard_active:
        return dict(SIGNAL_WEIGHTS)
    weights = dict(SIGNAL_WEIGHTS)
    for key in MOMENTUM_FAMILY_KEYS:
        # Scale each momentum-family signal proportionally within the
        # family so their OWN relative weights (20/20/20/15) are
        # preserved, only the family's combined total changes (75 -> 25).
        weights[key] = SIGNAL_WEIGHTS[key] * CRASH_GUARD_MOMENTUM_FAMILY_WEIGHT / _MOMENTUM_FAMILY_TOTAL_WEIGHT
    weights["rev_1m"] = CRASH_GUARD_REV_1M_WEIGHT
    return weights


def compute_timing_battery(
    signal_values: dict[str, Decimal | None],
    signal_reasons: dict[str, str | None],
    *,
    crash_guard_active: bool,
    contrarian: ContrarianCheck,
) -> TimingBatteryResult:
    """`signal_values`/`signal_reasons` keyed by `SIGNAL_WEIGHTS`'
    own keys. A missing/`None` value is excluded from the weighted
    mean (renormalized among whatever IS real), never treated as 0."""
    weights = _effective_weights(crash_guard_active)
    signals = tuple(
        TimingSignal(
            key=key, value=signal_values.get(key), weight_pct=weights[key],
            included=signal_values.get(key) is not None, reason=signal_reasons.get(key),
        )
        for key in SIGNAL_WEIGHTS
    )

    included = [s for s in signals if s.included]
    if not included:
        composite: Decimal | None = None
    else:
        present_weight_sum = sum(s.weight_pct for s in included)
        composite = sum((s.weight_pct / present_weight_sum) * s.value for s in included) if present_weight_sum > 0 else None

    return TimingBatteryResult(
        signals=signals, composite_score=composite, crash_guard_active=crash_guard_active, contrarian=contrarian,
    )
