"""
§31: Regime classification and its consequences — "Report the
probability, not just the label. A 55/45 split is a fundamentally
different instruction from 90/10."

    Regime      Signature                                    Gross exp.  MoS add
    Risk-On     Falling yields, stable LKR, positive credit    85-100%     +0%
    (reflation) growth, wide earnings-yield spread, reserves
                accumulating
    Transition  Mixed signals, rising uncertainty, conflicting  50-70%     +5%
                internals
    Risk-Off    Rising yields, LKR depreciation, reserve        20-40%    +12%
                drain, spread compression, inflation above
                target

"The regime output is not advisory. It mechanically raises the discount
rate (§17.2), widens every margin of safety (§25), caps gross exposure,
and reweights the composite score (§39)." This module builds the READ;
`app.domain.margin_of_safety.regime_component` already consumes the
label (`"risk_on"`/`"transition"`/`"risk_off"`) for the MoS add — see
`app.domain.macro_engine_view.regime_for` for how this gets there live.
The Ke/discount-rate and gross-exposure consequences §31 also names are
NOT wired anywhere in this codebase yet — a real, separate, honestly
named gap, not attempted in this module (see this module's own "WHAT
THIS DOESN'T DO YET" section below).

TWO INDEPENDENT READS, COMBINED, PER §30 STEP 4'S OWN WORDING: "two- or
three-state Markov switching on market returns and volatility, AUGMENTED
WITH a macro composite z-score."

  1. THE STATISTICAL READ (`fit_markov_regime_read`) — a genuine Markov
     regime-switching model (`statsmodels.tsa.regime_switching.
     markov_regression.MarkovRegression`) fit on a real return series
     (ASPI daily log returns, the only series in this system's macro
     layer with plausible year-long real depth — see `app.domain.
     index_history_loader`). Never hand-rolled: an econometrician's
     tested implementation is worth trusting; reimplementing an EM/
     Hamilton filter from scratch here would be exactly the "confident,
     precise, entirely fictional number" §15 warns the whole platform
     exists to avoid. The fitted regimes are unlabelled statistical
     states (statsmodels has no notion of "risk-on") — this module ranks
     them by `mean_return ÷ √variance` (a Sharpe-like measure, chosen
     deliberately over ranking by mean return alone because §30 itself
     says the switch is on "returns AND volatility," and a high-mean,
     high-variance regime is not unambiguously more "risk-on" than a
     moderate-mean, low-variance one) — highest ratio labelled
     `risk_on`, lowest `risk_off`, any middle state(s) `transition`.
     Requires real history — `MIN_OBSERVATIONS_FOR_MARKOV_FIT` below —
     and returns `None` rather than a numerically unstable fit on too
     short a window.

  2. THE COMPOSITE READ (`classify_composite_regime`) — a rule-based
     overlay directly codifying §31's own signature table and §32's own
     worked-example logic (policy rate direction, T-bill yield trend,
     inflation vs target, reserves trend, currency trend, and §29's own
     hero earnings-yield-minus-T-bill spread), each mapped to a regime
     lean exactly as the spec's own prose states it. This is NOT a
     statistical estimate — it's the spec's own qualitative logic made
     computable, exactly the same category of thing §32 itself is (an
     illustration of "how the engine should read the present moment").
     Deliberately weighted by how many of the ~14 named §29 signals are
     actually available (this system has real coverage of only a subset
     — CBSL T-bill/policy/CCPI/USD-LKR via `app.domain.cbsl_parsing`,
     plus the hero spread — not the full external/fiscal/real-economy/
     global blocks), so a caller can see whether a read rests on two
     signals or ten.

Both reads, when both exist, are blended in `classify_regime` — see that
function's own docstring for exactly how, and why a caller should not
treat this as an ensemble whose weights have been "optimised" in any
formal sense; they haven't, and pretending otherwise would be false
precision.

WHAT THIS MODULE DOESN'T DO YET, NAMED PRECISELY RATHER THAN LEFT
IMPLICIT — §30's method chain is six steps; this module is step 4 only:

  - Step 1 (stationarity/break testing — ADF, Phillips-Perron, KPSS,
    Zivot-Andrews) is a real, separate, useful building block for
    cointegration work this module does not need and does not build.
  - Step 2 (Johansen cointegration / VECM / ARDL bounds testing) — the
    actual long-run macro-to-market relationship §30 wants — is not
    built. `statsmodels.tsa.ardl.ARDL`/`UECM.bounds_test` exist and are
    the right tool; this is real, scoped-out future work, not a design
    decision this module makes.
  - Step 3 (impulse response functions, FEVD, Toda-Yamamoto Granger
    causality) needs step 2's fitted model first.
  - Step 5 (event study around CBSL/CCPI/IMF/budget/election dates) and
    step 6 (sector sensitivity matrix, §33) are both separate, real,
    not-yet-built modules — §33 in particular needs sector-level return
    series this system does not currently assemble.
  - §34's national project register is a structured, human-confirmed
    data table, not an econometric method — also not built.

None of the above is faked here by, say, returning a plausible-looking
number from a formula that isn't actually any of the six named methods.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

RegimeLabel = Literal["risk_on", "transition", "risk_off"]
REGIME_LABELS: tuple[RegimeLabel, ...] = ("risk_on", "transition", "risk_off")

#: Below this many observations, a Markov-switching fit is numerically
#: unstable — the EM algorithm can converge to a degenerate solution (one
#: "regime" absorbing a single outlier day) that looks precise and isn't.
#: 60 trading days (~3 months) is a floor for the model to run at all, not
#: a claim that 60 days is enough for a confident read — `MarkovRegimeRead.
#: observation_count` is always returned so a caller can judge that for
#: themselves. §36's "must span at least three distinct macro regimes" is
#: a BACKTESTING validation bar for a regime-series-over-time, a higher
#: and different bar from this single-point-in-time estimate.
MIN_OBSERVATIONS_FOR_MARKOV_FIT = 60


@dataclass(frozen=True)
class MarkovRegimeRead:
    k_regimes: int
    observation_count: int
    regime_means: tuple[Decimal, ...]
    """Fitted mean return per statistical regime, ordered risk_on-first
    (i.e. `regime_means[0]` is the risk_on regime's mean, matching
    `regime_labels[0]`), NOT in the arbitrary index order statsmodels
    fits them in."""

    regime_volatilities: tuple[Decimal, ...]
    """Fitted return standard deviation per regime, same risk_on-first
    ordering as `regime_means`."""

    regime_labels: tuple[RegimeLabel, ...]
    """One label per regime, ordered by `mean ÷ volatility` descending —
    see module docstring for why this ranking, not mean alone."""

    current_probabilities: dict[RegimeLabel, Decimal]
    """The smoothed probability of each regime as of the LAST observation
    in the input series — this is "where are we now," not the whole
    history."""

    current_label: RegimeLabel
    """`argmax(current_probabilities)` — the single most likely regime
    right now."""


def fit_markov_regime_read(
    returns: list[Decimal], *, k_regimes: int = 2
) -> MarkovRegimeRead | None:
    """§30 step 4's statistical half: Markov regime-switching on a real
    return series (ASPI daily log returns — see this module's own
    docstring for why that series specifically). `returns` must be
    ordered oldest-first, matching every other time-series convention in
    this codebase (`app.domain.valuation_view._confirmed_statement_line_
    history`, `app.domain.trend_detection`).

    Returns `None` — never a number computed from too little data — when
    fewer than `MIN_OBSERVATIONS_FOR_MARKOV_FIT` returns are supplied, or
    when the underlying optimiser fails to converge to a valid two- (or
    three-) state solution at all (a real possibility on a short or
    unusually flat series, not just a theoretical one).

    `k_regimes` must be 2 or 3 per §30 step 4's own "two- or three-state"
    wording; anything else raises `ValueError` rather than silently
    coercing to the nearest valid value.
    """
    if k_regimes not in (2, 3):
        raise ValueError(f"k_regimes must be 2 or 3 per §30 step 4, got {k_regimes}")
    if len(returns) < MIN_OBSERVATIONS_FOR_MARKOV_FIT:
        return None

    # Imported lazily: statsmodels/numpy/pandas are a real but sizeable
    # dependency this module is the ONLY current consumer of — deferring
    # the import means a caller who never touches the regime engine
    # doesn't pay the (real, one-time) import cost.
    import numpy as np
    import pandas as pd
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    series = pd.Series([float(r) for r in returns])
    model = MarkovRegression(series, k_regimes=k_regimes, trend="c", switching_variance=True)
    try:
        result = model.fit()
    except Exception:
        # A real, not-hypothetical failure mode on real short/flat series
        # — see module docstring. `None` with no further detail here
        # because statsmodels' own convergence exceptions vary and none
        # of them would be actionable to a caller beyond "no read".
        return None

    # statsmodels can return a best-effort result even when the EM
    # optimiser did NOT converge (it warns, via ConvergenceWarning,
    # rather than raising) — observed directly on a real 3-regime fit
    # while testing this module. Trusting an unconverged fit's params
    # would present a numerically arbitrary result as a real read; §31
    # itself never asks for a confident-looking wrong answer.
    if not bool(result.mle_retvals.get("converged", False)):
        return None

    means: list[float] = []
    variances: list[float] = []
    for i in range(k_regimes):
        try:
            means.append(float(result.params[f"const[{i}]"]))
            variances.append(float(result.params[f"sigma2[{i}]"]))
        except KeyError:
            return None
        if variances[-1] <= 0 or not np.isfinite(variances[-1]) or not np.isfinite(means[-1]):
            return None

    # Rank by mean ÷ √variance, highest first — see module docstring.
    sharpe_like = [m / (v**0.5) for m, v in zip(means, variances)]
    order = sorted(range(k_regimes), key=lambda i: sharpe_like[i], reverse=True)

    if k_regimes == 2:
        ordered_labels: tuple[RegimeLabel, ...] = ("risk_on", "risk_off")
    else:
        ordered_labels = ("risk_on", "transition", "risk_off")

    ordered_means = tuple(Decimal(str(round(means[i], 8))) for i in order)
    ordered_vols = tuple(Decimal(str(round(variances[i] ** 0.5, 8))) for i in order)

    last_row = result.smoothed_marginal_probabilities.iloc[-1]
    current_probabilities: dict[RegimeLabel, Decimal] = {
        ordered_labels[rank]: Decimal(str(round(float(last_row[stat_index]), 6)))
        for rank, stat_index in enumerate(order)
    }
    current_label = max(current_probabilities, key=lambda label: current_probabilities[label])

    return MarkovRegimeRead(
        k_regimes=k_regimes,
        observation_count=len(returns),
        regime_means=ordered_means,
        regime_volatilities=ordered_vols,
        regime_labels=ordered_labels,
        current_probabilities=current_probabilities,
        current_label=current_label,
    )


@dataclass(frozen=True)
class MacroSignal:
    name: str
    """Human-readable — "Policy rate direction", "364-day T-bill yield
    trend" — shown next to its reading, matching this project's "never a
    bare figure" convention."""

    reading: str
    """The observed fact in words — "Tightened 100bp", "6.8% y/y, above
    the 5% target" — §32's own table has one column exactly like this,
    reused here rather than inventing a different shape."""

    lean: RegimeLabel
    """Which regime this ONE signal points toward, per §31's signature
    table, applied literally — this module does not weigh evidence
    within a signal, only combines already-classified signals."""


def hero_spread_signal(spread: Decimal) -> MacroSignal:
    """§29's hero variable, the earnings-yield-minus-364-day-T-bill
    spread, already computed by `app.domain.macro.compute_spread` — read
    as a regime signal per §31's own table ("wide earnings-yield spread"
    → Risk-On) rather than a fresh threshold invented here. A spread
    within 1 percentage point of zero is read as Transition — genuinely
    ambiguous, not confidently either direction; more negative than that
    is Risk-Off (equities no longer compensate for the T-bill
    alternative); more positive is Risk-On."""
    if spread > Decimal("0.01"):
        lean: RegimeLabel = "risk_on"
    elif spread < Decimal("-0.01"):
        lean = "risk_off"
    else:
        lean = "transition"
    return MacroSignal(
        name="Earnings yield − 364d T-bill spread (§29 hero variable)",
        reading=f"{spread:.2%}",
        lean=lean,
    )


def policy_rate_direction_signal(current: Decimal, previous: Decimal) -> MacroSignal:
    """§31: "Falling yields" → Risk-On, "Rising yields" → Risk-Off — read
    directly on the policy rate's own direction, per §32's own worked
    example ("Tightened 100bp in May, held in July" → Risk-Off)."""
    if current > previous:
        lean: RegimeLabel = "risk_off"
        direction = "Rising"
    elif current < previous:
        lean = "risk_on"
        direction = "Falling"
    else:
        lean = "transition"
        direction = "Holding"
    return MacroSignal(
        name="Policy rate direction",
        reading=f"{direction} ({previous:.2%} → {current:.2%})",
        lean=lean,
    )


def tbill_yield_trend_signal(current: Decimal, previous: Decimal) -> MacroSignal:
    """Same "falling = Risk-On, rising = Risk-Off" reading as the policy
    rate, applied to the 364-day T-bill primary yield specifically —
    §32's own worked example treats these as two separate rows ("Policy
    rate direction" and "T-bill yields") even though they usually move
    together, because they can diverge (the curve can steepen or flatten
    independently of a single policy move), so this module keeps them as
    two independent signals rather than collapsing them into one."""
    if current > previous:
        lean: RegimeLabel = "risk_off"
        direction = "Risen"
    elif current < previous:
        lean = "risk_on"
        direction = "Fallen"
    else:
        lean = "transition"
        direction = "Flat"
    return MacroSignal(
        name="364-day T-bill yield trend",
        reading=f"{direction} ({previous:.2%} → {current:.2%})",
        lean=lean,
    )


def inflation_vs_target_signal(ccpi_yoy: Decimal, target: Decimal = Decimal("0.05")) -> MacroSignal:
    """§32's own worked example: "6.8% y/y, above the 5% target,
    energy-driven → Risk-Off". `target` defaults to 5%, §32's own stated
    figure — not independently sourced from a CBSL inflation-target
    publication, and callers with a more current target should pass it
    explicitly rather than trust this default indefinitely."""
    if ccpi_yoy > target:
        lean: RegimeLabel = "risk_off"
        qualifier = "above"
    elif ccpi_yoy < target - Decimal("0.01"):
        lean = "risk_on"
        qualifier = "comfortably below"
    else:
        lean = "transition"
        qualifier = "near"
    return MacroSignal(
        name="CCPI inflation vs target",
        reading=f"{ccpi_yoy:.1%} y/y, {qualifier} the {target:.0%} target",
        lean=lean,
    )


def currency_trend_signal(pct_change: Decimal) -> MacroSignal:
    """§31: "stable LKR" → Risk-On signature component; "LKR
    depreciation" → Risk-Off. `pct_change` is the LKR's move against USD
    over the caller's chosen window (positive = LKR depreciated, i.e.
    more rupees per dollar) — a caller-supplied window, not fixed here,
    because §29's own variable set lists both spot rates and NEER/REER
    without picking one horizon."""
    if pct_change > Decimal("0.02"):
        lean: RegimeLabel = "risk_off"
        qualifier = "Depreciating"
    elif pct_change < Decimal("-0.005"):
        lean = "risk_on"
        qualifier = "Appreciating"
    else:
        lean = "transition"
        qualifier = "Broadly stable"
    return MacroSignal(
        name="LKR/USD trend",
        reading=f"{qualifier} ({pct_change:+.2%} over the window)",
        lean=lean,
    )


def reserves_trend_signal(pct_change: Decimal) -> MacroSignal:
    """§31: "reserves accumulating" → Risk-On; §32's own worked example:
    "drawn down... → Risk-Off". `pct_change` is gross official reserves'
    change over the caller's chosen window."""
    if pct_change < Decimal("-0.02"):
        lean: RegimeLabel = "risk_off"
        qualifier = "Drawn down"
    elif pct_change > Decimal("0.02"):
        lean = "risk_on"
        qualifier = "Accumulating"
    else:
        lean = "transition"
        qualifier = "Broadly stable"
    return MacroSignal(
        name="Gross official reserves trend",
        reading=f"{qualifier} ({pct_change:+.2%} over the window)",
        lean=lean,
    )


@dataclass(frozen=True)
class CompositeRegimeRead:
    signals: tuple[MacroSignal, ...]
    probabilities: dict[RegimeLabel, Decimal]
    """Simple count-weighted share of signals pointing each way — e.g. 5
    of 7 signals Risk-Off gives `risk_off: 0.714`. NOT a formally
    estimated probability (no likelihood function underlies this), which
    is exactly why it is combined with, and clearly distinguished from,
    `MarkovRegimeRead`'s statistically-fitted probabilities in
    `RegimeRead` below — conflating the two would overstate this
    composite's precision."""

    label: RegimeLabel
    coverage_note: str
    """States how many of §29's ~14 named signal types this read actually
    used, so a caller can see a read built on 2 signals is thinner
    evidence than one built on 8, even though both produce a label."""


#: §29 names roughly this many distinct series across all seven blocks
#: (Monetary, Prices, External, Fiscal/sovereign, Real economy, Market
#: internals, Global) — used only to phrase `coverage_note` honestly, not
#: as a precise or load-bearing count.
APPROXIMATE_NAMED_SIGNAL_COUNT = 14


def classify_composite_regime(signals: list[MacroSignal]) -> CompositeRegimeRead | None:
    """§31's signature table and §32's worked-example logic, made
    computable — a rule-based overlay, not a statistical estimate (see
    module docstring). Returns `None` for an empty signal list rather
    than a meaningless "0 of 0" read."""
    if not signals:
        return None

    counts: dict[RegimeLabel, int] = {label: 0 for label in REGIME_LABELS}
    for signal in signals:
        counts[signal.lean] += 1
    total = len(signals)
    probabilities = {label: Decimal(count) / Decimal(total) for label, count in counts.items()}
    label = max(probabilities, key=lambda l: probabilities[l])

    return CompositeRegimeRead(
        signals=tuple(signals),
        probabilities=probabilities,
        label=label,
        coverage_note=(
            f"Composite read from {total} of roughly {APPROXIMATE_NAMED_SIGNAL_COUNT} "
            "signal types §29 names — this system has real ingested coverage of only a "
            "subset (CBSL T-bill/policy rate/CCPI/USD-LKR, plus the §29 hero spread), not "
            "the full external/fiscal/real-economy/global blocks."
        ),
    )


@dataclass(frozen=True)
class RegimeRead:
    label: RegimeLabel
    probabilities: dict[RegimeLabel, Decimal]
    statistical: MarkovRegimeRead | None
    composite: CompositeRegimeRead | None
    note: str


def classify_regime(
    composite: CompositeRegimeRead | None, statistical: MarkovRegimeRead | None
) -> RegimeRead | None:
    """Combines the two independent reads per §30 step 4's "Markov
    switching... augmented with a macro composite z-score" wording — read
    here as: the statistical read is primary when it exists (it is the
    named method), and the composite read either augments it (when both
    exist, simple 50/50 average of the two probability distributions —
    an explicit, disclosed, NOT formally-optimised blend weight, stated
    plainly here rather than dressed up as more rigorous than it is) or
    stands alone (when only the composite exists, which — given `app.
    domain.index_history_loader` only backfills roughly a year of ASPI
    history and `MIN_OBSERVATIONS_FOR_MARKOV_FIT` needs at least a
    quarter of that — is expected to be the common case for a while).

    Returns `None` only when NEITHER read exists — this module never
    fabricates a regime label from zero signals.
    """
    if composite is None and statistical is None:
        return None
    if statistical is None:
        return RegimeRead(
            label=composite.label,
            probabilities=composite.probabilities,
            statistical=None,
            composite=composite,
            note=(
                "Composite (rule-based) read only — no statistical Markov-switching read "
                "available (insufficient real ASPI return history, or not supplied). "
                + composite.coverage_note
            ),
        )
    if composite is None:
        return RegimeRead(
            label=statistical.current_label,
            probabilities=statistical.current_probabilities,
            statistical=statistical,
            composite=None,
            note=(
                f"Statistical (Markov regime-switching) read only, fit on "
                f"{statistical.observation_count} real ASPI return observations — no "
                "composite macro-signal read available."
            ),
        )

    blended: dict[RegimeLabel, Decimal] = {
        label: (
            composite.probabilities.get(label, Decimal(0))
            + statistical.current_probabilities.get(label, Decimal(0))
        )
        / Decimal(2)
        for label in REGIME_LABELS
    }
    label = max(blended, key=lambda l: blended[l])
    return RegimeRead(
        label=label,
        probabilities=blended,
        statistical=statistical,
        composite=composite,
        note=(
            "Blended read: 50/50 average of the statistical Markov-switching "
            f"probabilities ({statistical.observation_count} real ASPI return "
            f"observations) and the composite rule-based read ({composite.coverage_note} "
            "). The 50/50 weight is an explicit, disclosed choice, not a formally "
            "optimised one."
        ),
    )
