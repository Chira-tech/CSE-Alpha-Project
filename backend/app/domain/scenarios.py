"""
§23: Scenarios and simulation — "a single fair value is false precision.
Every DCF and every SOTP runs three deterministic scenarios plus a
distribution."

Three deterministic scenarios (§23's own table):

    Scenario  Construction
    Bear      Growth at 25th percentile of its own history, margin at 25th
              percentile, WACC +150bp, terminal growth -100bp, plus the
              archetype's specific stress
    Base      Assumptions as derived in §18.2
    Bull      Growth and margin at 75th percentile, WACC -100bp, plus any
              confirmed project in the register reaching completion on
              schedule

Plus a Monte Carlo overlay (10,000 draws, empirical/bootstrap rather than
assumed-normal, per §23's own instruction), a sensitivity tornado (which
single assumption moves the valuation most), and reverse DCF — which
lives in `app.domain.dcf` next to the forward model it inverts, not here.

Built on top of `app.domain.dcf.DCFAssumptions`/`dcf_equity_value` — this
module constructs scenario VARIANTS of an assumption set and re-runs the
same pure DCF engine, it does not duplicate any discounting arithmetic.

WHAT §23 ASKS FOR THAT THIS SYSTEM CANNOT SUPPLY YET, NAMED EXPLICITLY.
The bear scenario's "archetype's specific stress" (an FX shock for
importers, an occupancy shock for hotels, a commodity trough for
plantations, a credit-cost spike for banks) and the bull scenario's
"confirmed project in the register reaching completion on schedule" both
depend on the macro engine and the national-project register (§29-34,
§34) — Phase 5, not built. `build_scenario_set` accepts each as an
optional, caller-supplied delta rather than computing it internally, so
a scenario built today is honestly a partial bear/bull (percentile-shift
and discount-rate-shift only) until that data exists — `note` on the
result says so.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from decimal import Decimal

from app.domain.dcf import DCFAssumptions, dcf_equity_value

# §23's own stated deltas — not policy defaults like PARAMETERS.md's
# provisional numbers, these are literally the spec's construction rule.
BEAR_DISCOUNT_RATE_DELTA = Decimal("0.015")  # WACC +150bp
BEAR_TERMINAL_GROWTH_DELTA = Decimal("-0.010")  # terminal growth -100bp
BULL_DISCOUNT_RATE_DELTA = Decimal("-0.010")  # WACC -100bp


@dataclass(frozen=True)
class HistoricalGrowthMarginDistribution:
    growth_p25: Decimal
    growth_p75: Decimal
    margin_p25: Decimal
    margin_p75: Decimal


@dataclass(frozen=True)
class ScenarioSet:
    bear: DCFAssumptions
    base: DCFAssumptions
    bull: DCFAssumptions
    bear_value_per_share: Decimal
    base_value_per_share: Decimal
    bull_value_per_share: Decimal
    note: str
    inversion_detected: bool = False
    """True when the RAW re-run values were not monotonic (`bear > base`
    or `base > bull`) and had to be reordered for display. §10 of the
    system-wide valuation upgrade doc requires `bear <= base <= bull`
    before any scenario result is shown; a violation also means the
    base-case DCF assumption set is unstable, so a caller should treat
    the whole scenario spread as low confidence when this is set."""


def build_scenario_set(
    base: DCFAssumptions,
    distribution: HistoricalGrowthMarginDistribution,
    archetype_bear_revenue_growth_delta: Decimal = Decimal(0),
    archetype_bear_margin_delta: Decimal = Decimal(0),
    confirmed_project_bull_revenue_growth_delta: Decimal = Decimal(0),
) -> ScenarioSet:
    """§23's three deterministic scenarios. `base` is used exactly as
    supplied — "assumptions as derived in §18.2" means the base case IS
    the §18.2 assumption set, not a fourth thing to construct.

    The three archetype/project-register deltas default to 0 — see the
    module docstring for why (macro engine and project register are
    Phase 5). A caller who does not supply them is running a bear/bull
    that reflects the percentile and discount-rate shifts only.
    """
    bear = dataclasses.replace(
        base,
        revenue_growth_y1=distribution.growth_p25 + archetype_bear_revenue_growth_delta,
        revenue_growth_y2=distribution.growth_p25 + archetype_bear_revenue_growth_delta,
        revenue_growth_stage2_target=distribution.growth_p25 + archetype_bear_revenue_growth_delta,
        operating_margin_current=distribution.margin_p25 + archetype_bear_margin_delta,
        operating_margin_target=distribution.margin_p25 + archetype_bear_margin_delta,
        discount_rate=base.discount_rate + BEAR_DISCOUNT_RATE_DELTA,
        terminal_growth=base.terminal_growth + BEAR_TERMINAL_GROWTH_DELTA,
    )
    bull = dataclasses.replace(
        base,
        revenue_growth_y1=distribution.growth_p75 + confirmed_project_bull_revenue_growth_delta,
        revenue_growth_y2=distribution.growth_p75 + confirmed_project_bull_revenue_growth_delta,
        revenue_growth_stage2_target=distribution.growth_p75 + confirmed_project_bull_revenue_growth_delta,
        operating_margin_current=distribution.margin_p75,
        operating_margin_target=distribution.margin_p75,
        discount_rate=base.discount_rate + BULL_DISCOUNT_RATE_DELTA,
    )

    note = "Base case is `base` as supplied (§18.2's own assumption set)."
    if archetype_bear_revenue_growth_delta == 0 and archetype_bear_margin_delta == 0:
        note += " Bear omits the archetype-specific stress §23 also calls for (macro engine, Phase 5)."
    if confirmed_project_bull_revenue_growth_delta == 0:
        note += " Bull omits the confirmed-project uplift §23 also calls for (project register, Phase 5)."

    raw_bear = dcf_equity_value(bear).value_per_share
    raw_base = dcf_equity_value(base).value_per_share
    raw_bull = dcf_equity_value(bull).value_per_share

    # §10: enforce bear <= base <= bull BEFORE returning. A non-monotonic
    # set is a real, observed failure (DPL.N0000: raw bear -15.06 / base
    # 50.99 / bull 12.52 — the exact inversion §10 names). These ARE
    # scenario values — the SAME pure DCF engine re-run with percentile-
    # and discount-rate-shifted assumptions — not mislabelled model
    # outputs, so §10's "reorder only if genuinely scenario values"
    # condition is met: sort the three by value and keep the base case
    # clamped into [bear, bull] so it stays the central figure it is
    # meant to be. The inversion itself is surfaced (`inversion_detected`
    # + `note`) rather than silently smoothed over, because it signals
    # the base assumption set is pathological.
    inversion = not (raw_bear <= raw_base <= raw_bull)
    if inversion:
        low, mid, high = sorted([raw_bear, raw_base, raw_bull])
        bear_value, bull_value = low, high
        base_value = min(max(raw_base, low), high)
        note += (
            f" WARNING (§10): raw scenario values were non-monotonic "
            f"(bear {raw_bear:.2f} / base {raw_base:.2f} / bull {raw_bull:.2f}) — reordered "
            "by value for display. This signals the base-case DCF assumptions are unstable; "
            "treat the scenario spread as low confidence."
        )
    else:
        bear_value, base_value, bull_value = raw_bear, raw_base, raw_bull

    return ScenarioSet(
        bear=bear,
        base=base,
        bull=bull,
        bear_value_per_share=bear_value,
        base_value_per_share=base_value,
        bull_value_per_share=bull_value,
        note=note,
        inversion_detected=inversion,
    )


# --- Sensitivity tornado --------------------------------------------------


@dataclass(frozen=True)
class TornadoBar:
    assumption_name: str
    low_value_per_share: Decimal
    high_value_per_share: Decimal
    spread: Decimal


def sensitivity_tornado(
    base: DCFAssumptions, deltas: dict[str, Decimal]
) -> tuple[TornadoBar, ...]:
    """§23: "always displayed. Which single assumption moves the
    valuation most?" `deltas` maps a `DCFAssumptions` field name to the
    ± amount to perturb it by (e.g. `{"discount_rate": Decimal("0.01")}`
    tests ±100bp on WACC/Ke). Returned sorted widest spread first — the
    literal tornado-chart ordering.
    """
    bars: list[TornadoBar] = []
    for field_name, delta in deltas.items():
        current = getattr(base, field_name)
        low = dcf_equity_value(dataclasses.replace(base, **{field_name: current - delta})).value_per_share
        high = dcf_equity_value(dataclasses.replace(base, **{field_name: current + delta})).value_per_share
        bars.append(TornadoBar(field_name, low, high, abs(high - low)))
    return tuple(sorted(bars, key=lambda b: b.spread, reverse=True))


# --- Monte Carlo overlay ---------------------------------------------------


@dataclass(frozen=True)
class MonteCarloInput:
    field_name: str
    historical_values: tuple[Decimal, ...]
    """§23: "distributions fitted to each company's own historical
    variability rather than assumed normal." This module draws directly
    (bootstrap-with-replacement) from the company's own historical values
    for this assumption rather than fitting a parametric distribution to
    them — the simplest way to respect "fitted to its own variability"
    without a statistics dependency this project doesn't have (see
    `app.domain.trend_detection`'s own "no scipy/numpy" note)."""


@dataclass(frozen=True)
class MonteCarloResult:
    draws: int
    p10: Decimal
    p25: Decimal
    p50: Decimal
    p75: Decimal
    p90: Decimal
    probability_fair_value_exceeds_price: Decimal | None
    note: str


def run_monte_carlo(
    base: DCFAssumptions,
    inputs: tuple[MonteCarloInput, ...],
    current_price_per_share: Decimal | None = None,
    draws: int = 10_000,
    seed: int | None = None,
) -> MonteCarloResult:
    """§23: "10,000 draws over the four inputs the value is most
    sensitive to... Output: a fair-value distribution with 10th, 25th,
    50th, 75th and 90th percentiles, and — the number that actually
    matters — P(fair value > current price)."

    `seed` makes a run reproducible for testing; production callers
    should leave it `None` (Python's default OS-entropy seeding).
    """
    rng = random.Random(seed)
    values: list[Decimal] = []
    for _ in range(draws):
        overrides = {
            inp.field_name: rng.choice(inp.historical_values)
            for inp in inputs
            if inp.historical_values
        }
        scenario = dataclasses.replace(base, **overrides)
        values.append(dcf_equity_value(scenario).value_per_share)
    values.sort()

    def percentile(p: int) -> Decimal:
        idx = min(len(values) - 1, max(0, (len(values) * p) // 100))
        return values[idx]

    probability = None
    if current_price_per_share is not None and values:
        exceeding = sum(1 for v in values if v > current_price_per_share)
        probability = Decimal(exceeding) / Decimal(len(values))

    return MonteCarloResult(
        draws=len(values),
        p10=percentile(10),
        p25=percentile(25),
        p50=percentile(50),
        p75=percentile(75),
        p90=percentile(90),
        probability_fair_value_exceeds_price=probability,
        note="Empirical bootstrap over caller-supplied historical values per input, "
        "not an assumed-normal distribution (§23).",
    )
