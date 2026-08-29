"""
§5 / §13 / §24: Normalised (mid-cycle) ratios — "do not value a company
on one year of a cycle."

The system-wide valuation upgrade (`docs/CSE_Alpha_Engine_System_Wide_
Valuation_Upgrade.md` §5, §13, §20, §24) is explicit that a single
confirmed period is not a valuation basis: a cyclical trough, a soft
year at a holding company, or a one-off gain all distort the latest
reported ROE, and every §19-20 justified-multiple anchor is built on
ROE. Before this module, `app.domain.valuation_view._gather_inputs`
computed ROE from exactly one period, so a plantation in a commodity
trough or a conglomerate consolidating a weak subsidiary year produced a
below-`g` ROE and therefore a NEGATIVE justified fair value — an
arithmetic artifact, not a real read.

This module is the pure, deterministic normalisation step: given a
point-in-time-clean series of a ratio's own history, return the
mid-cycle figure (the MEDIAN — robust to a single extreme year in a way
the mean is not), the number of periods it rests on, an explicit
confidence grade, and a cyclicality read (how wide the historical spread
is). It extracts nothing and queries nothing — the caller
(`valuation_view`) assembles the series from confirmed fundamentals and
feeds it in, exactly the split every other `_view.py`/pure-module pair
in this codebase already uses.

CONFIDENCE GRADES, AND WHY MEDIAN NOT MEAN. `>= HIGH_CONFIDENCE_PERIODS`
distinct annual observations → `"high"`; `>= MEDIUM_CONFIDENCE_PERIODS` →
`"medium"`; anything less (including the single-period fallback) →
`"low"`. The median is used rather than the mean because §5's whole
point is robustness to "abnormal years" — one blowout gain or one
impairment year moves a 5-point mean materially but barely moves its
median. A trimmed mean was considered and rejected as a second
provisional constant to defend when the median already does the job.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from decimal import Decimal

HIGH_CONFIDENCE_PERIODS = 5
MEDIUM_CONFIDENCE_PERIODS = 3


@dataclass(frozen=True)
class NormalisedRatio:
    value: Decimal | None
    """The mid-cycle (median) figure — `None` only when no observation at
    all was supplied."""

    basis: str
    """Human-readable, e.g. `"median of 6 annual periods (2020-2025)"` or
    `"single most recent period only"` — shown next to the number per
    this project's "never a bare figure" convention."""

    n_periods: int
    confidence: str
    """`"high"` / `"medium"` / `"low"` / `"none"` — maps directly onto
    the decision engine's own confidence downgrade rules."""

    per_period: tuple[tuple[dt.date, Decimal], ...]
    spread_pct: Decimal | None
    """(max - min) ÷ |median| across the supplied history — a cyclicality
    read. `None` when fewer than 2 periods or the median is zero. A large
    spread should itself reduce downstream confidence (§24: "dispersion
    is a signal")."""

    warnings: tuple[str, ...]


def normalise_ratio(
    history: list[tuple[dt.date, Decimal]],
    *,
    label: str = "ratio",
) -> NormalisedRatio:
    """`history` is `(period_end, value)` pairs — any order; this function
    sorts. Typically one ratio (ROE, operating margin, net margin) across
    a company's confirmed annual periods. Returns the median as the
    mid-cycle estimate with an explicit confidence grade.
    """
    if not history:
        return NormalisedRatio(
            value=None,
            basis="no history supplied",
            n_periods=0,
            confidence="none",
            per_period=(),
            spread_pct=None,
            warnings=(f"No {label} history available to normalise.",),
        )

    ordered = tuple(sorted(history))
    values = [v for _, v in ordered]
    median = Decimal(str(statistics.median(values)))

    n = len(values)
    if n >= HIGH_CONFIDENCE_PERIODS:
        confidence = "high"
    elif n >= MEDIUM_CONFIDENCE_PERIODS:
        confidence = "medium"
    else:
        confidence = "low"

    spread_pct: Decimal | None = None
    warnings: list[str] = []
    if n >= 2 and median != 0:
        spread_pct = (max(values) - min(values)) / abs(median)
    if n == 1:
        basis = "single most recent period only"
        warnings.append(
            f"{label} rests on ONE confirmed period — not a mid-cycle figure. "
            "Treated as low confidence; a cyclical or one-off year cannot be "
            "distinguished from a normal one with a single observation."
        )
    else:
        basis = (
            f"median of {n} annual periods "
            f"({ordered[0][0].year}-{ordered[-1][0].year})"
        )
    if confidence == "medium":
        warnings.append(
            f"{label} normalised over {n} periods — below the {HIGH_CONFIDENCE_PERIODS}-period "
            "bar for high confidence, so a full cycle may not be represented."
        )
    if spread_pct is not None and spread_pct > Decimal("1.0"):
        warnings.append(
            f"{label} spans a wide historical range (spread {spread_pct:.0%} of the "
            "median) — genuinely cyclical; the mid-cycle figure carries real uncertainty."
        )

    return NormalisedRatio(
        value=median,
        basis=basis,
        n_periods=n,
        confidence=confidence,
        per_period=ordered,
        spread_pct=spread_pct,
        warnings=tuple(warnings),
    )


def per_period_roe(
    net_income_history: list[tuple[dt.date, Decimal]],
    total_equity_history: list[tuple[dt.date, Decimal]],
) -> list[tuple[dt.date, Decimal]]:
    """Align a confirmed `net_income` series and a confirmed `total_equity`
    series by `period_end` and return per-period ROE (`net_income ÷
    total_equity`) for every period present in BOTH, oldest first.

    Only periods with a strictly positive equity denominator are kept — a
    zero or negative book value makes ROE meaningless for that year, the
    same guard `app.domain.ratios` applies to the single-period figure.
    Periods where the two series disagree on availability are simply
    dropped (not estimated), so the result is only as deep as the
    company's genuinely paired history.
    """
    equity_by_period = {d: v for d, v in total_equity_history}
    out: list[tuple[dt.date, Decimal]] = []
    for period_end, ni in sorted(net_income_history):
        eq = equity_by_period.get(period_end)
        if eq is None or eq <= 0:
            continue
        out.append((period_end, ni / eq))
    return out
