"""
§19: Dividend and residual income models.

19.1 Gordon growth   V0 = D1 ÷ (Ke - g)
19.2 Multi-stage DDM  two/three-stage, dividend capped by sustainable
                      payout = 1 - (g ÷ ROE)
19.3 Residual income  V0 = Book value
                            + Σ [(ROE_t - Ke) × Book_t-1] ÷ (1+Ke)^t
                            + terminal residual income

THE ONE MODEL IN §18-24 THAT IS ALREADY WIREABLE TO LIVE DATA, AND WHY
THAT MATTERS MORE HERE THAN ELSEWHERE. §18's DCF needs D&A, capex and
working-capital deltas this system doesn't extract (see `app.domain.dcf`'s
module docstring). Residual income needs none of that — only book value
(`total_equity`, extracted since Phase 1), ROE (`net_income ÷ total_equity`,
already computed by `app.domain.ratios`), and Ke (`app.domain.cost_of_
equity`, already built). §19.3 itself says why this is disproportionately
valuable on THIS exchange: "Banks are a large share of the S&P SL20...
moving value from the invented part of the model to the observed part is
a direct improvement in reliability." `compute_residual_income` is
therefore the first of §18-22's models that can run against a real filing
the day book value, ROE and Ke are all present for one security — no
further extraction work required.

DDM (19.1, 19.2), BY CONTRAST, STAYS UNWIRED FOR A DIFFERENT REASON.
Dividend history is not extracted anywhere in this system — no ingestion
source pulls per-share dividend declarations (this is a genuine gap, not
the cash-flow-statement gap PARAMETERS.md #9 tracks; dividends are
typically disclosed in a company's dividend announcement, not the
financial statements this project's PDF extractor targets). Both DDM
functions are built and tested against caller-supplied dividend/payout
inputs, ready for that ingestion work, not wired to a live source yet.

`justified_price_to_book` (§19.3 and, identically, §20.2) lives in
`app.domain.relative_valuation` rather than being duplicated here — see
that module's docstring for why the two sections share one formula.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# §19.2: "sustainable payout = 1 - (g ÷ ROE)" — a bank cannot be credited
# with paying dividends it would need to retain to fund its own loan
# growth. Clipped to [0, 1]: a negative implied retention rate (g <= 0
# with positive ROE) would otherwise imply a payout ratio above 100%,
# and a payout ratio below 0% is not a real number a company can pay.
def sustainable_payout_ratio(growth_rate: Decimal, roe: Decimal) -> Decimal | None:
    """None when ROE is zero or negative — the ratio isn't meaningful
    without positive profitability to retain earnings out of, the same
    guard `app.domain.ratios._div_positive_denominator` applies to ROE
    itself."""
    if roe <= 0:
        return None
    raw = Decimal(1) - (growth_rate / roe)
    return max(Decimal(0), min(Decimal(1), raw))


# --- §19.1 Gordon growth -------------------------------------------------

# Provisional default, same discipline as PARAMETERS.md: §19.1 requires
# payout "stable for five years" without stating a numeric tolerance.
# 10 percentage points of range across the trailing five years is the
# threshold used here — generous enough not to flag ordinary year-to-year
# noise in a payout ratio as instability, tight enough to actually
# exclude a company whose payout has genuinely drifted. Treat as
# provisional until reviewed, exactly like PARAMETERS.md's own defaults.
PAYOUT_STABILITY_THRESHOLD_PCT = Decimal("0.10")


@dataclass(frozen=True)
class GordonGrowthEligibility:
    payout_stable: bool | None
    """None if fewer than 5 payout ratios were supplied — not enough
    history to judge stability either way."""

    growth_below_ke: bool
    is_mature: bool
    reasons: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return bool(self.payout_stable) and self.growth_below_ke and self.is_mature


def check_gordon_growth_eligibility(
    trailing_five_year_payout_ratios: tuple[Decimal, ...],
    growth_rate: Decimal,
    cost_of_equity: Decimal,
    is_mature_business: bool,
) -> GordonGrowthEligibility:
    """§19.1: "Applied only where payout has been stable for five years,
    growth is below Ke, and the business is mature. Used mainly as a
    floor check... never as a sole anchor." This function is that gate —
    `gordon_growth_value` below computes the number regardless of
    eligibility (so a rejected case is still inspectable), but the caller
    is expected to check `.eligible` before treating the result as more
    than a floor check.
    """
    reasons: list[str] = []
    payout_stable: bool | None
    if len(trailing_five_year_payout_ratios) < 5:
        payout_stable = None
        reasons.append(
            f"only {len(trailing_five_year_payout_ratios)} of 5 required payout-ratio "
            "years supplied — cannot judge stability"
        )
    else:
        spread = max(trailing_five_year_payout_ratios) - min(trailing_five_year_payout_ratios)
        payout_stable = spread <= PAYOUT_STABILITY_THRESHOLD_PCT
        if not payout_stable:
            reasons.append(
                f"payout ratio range over 5 years ({spread:.1%}) exceeds the "
                f"{PAYOUT_STABILITY_THRESHOLD_PCT:.0%} stability threshold"
            )

    growth_below_ke = growth_rate < cost_of_equity
    if not growth_below_ke:
        reasons.append(f"growth ({growth_rate:.1%}) is not below Ke ({cost_of_equity:.1%})")
    if not is_mature_business:
        reasons.append("business not flagged mature")

    return GordonGrowthEligibility(payout_stable, growth_below_ke, is_mature_business, tuple(reasons))


@dataclass(frozen=True)
class GordonGrowthResult:
    value_per_share: Decimal | None
    note: str


def gordon_growth_value(
    next_year_dividend_per_share: Decimal,
    cost_of_equity: Decimal,
    growth_rate: Decimal,
) -> GordonGrowthResult:
    """V0 = D1 ÷ (Ke - g) (§19.1). Computed regardless of eligibility —
    see `check_gordon_growth_eligibility` for the gate that decides
    whether this number should be trusted as more than a floor check."""
    if cost_of_equity <= growth_rate:
        return GordonGrowthResult(
            value_per_share=None,
            note=f"Ke ({cost_of_equity}) <= growth ({growth_rate}) — undefined "
            "or negative under Gordon growth.",
        )
    value = next_year_dividend_per_share / (cost_of_equity - growth_rate)
    return GordonGrowthResult(value_per_share=value, note="V0 = D1 ÷ (Ke - g).")


# --- §19.2 Multi-stage DDM ------------------------------------------------


@dataclass(frozen=True)
class DDMStage:
    years: int
    eps_growth: Decimal
    target_payout_ratio: Decimal
    """The payout the caller wants to model for this stage — actual
    payout applied is `min(target_payout_ratio, sustainable_payout_ratio)`
    when `roe` is supplied, per §19.2's dividend-capacity cap."""


@dataclass(frozen=True)
class DDMYear:
    year: int
    eps: Decimal
    payout_ratio_used: Decimal
    payout_was_capped: bool
    dividend_per_share: Decimal


@dataclass(frozen=True)
class MultiStageDDMResult:
    years: tuple[DDMYear, ...]
    pv_explicit_dividends: Decimal
    terminal_value: Decimal
    pv_terminal_value: Decimal
    value_per_share: Decimal | None
    warnings: tuple[str, ...]


def compute_multi_stage_ddm(
    base_eps: Decimal,
    roe: Decimal,
    stages: tuple[DDMStage, ...],
    terminal_growth: Decimal,
    terminal_payout_ratio: Decimal,
    cost_of_equity: Decimal,
) -> MultiStageDDMResult:
    """Two- or three-stage DDM (§19.2) — however many `stages` the caller
    passes (a two-stage model is `len(stages) == 1` plus the terminal
    stage; three-stage is `len(stages) == 2` plus terminal, etc.)."""
    warnings: list[str] = []
    years: list[DDMYear] = []
    eps = base_eps
    year_num = 0
    for stage in stages:
        sustainable = sustainable_payout_ratio(stage.eps_growth, roe)
        for _ in range(stage.years):
            year_num += 1
            eps = eps * (Decimal(1) + stage.eps_growth)
            if sustainable is not None and stage.target_payout_ratio > sustainable:
                payout = sustainable
                capped = True
            else:
                payout = stage.target_payout_ratio
                capped = False
            dividend = eps * payout
            years.append(DDMYear(year_num, eps, payout, capped, dividend))

    pv_explicit = Decimal(0)
    for y in years:
        pv_explicit += y.dividend_per_share / ((Decimal(1) + cost_of_equity) ** y.year)

    if cost_of_equity <= terminal_growth:
        warnings.append(
            f"Ke ({cost_of_equity}) <= terminal_growth ({terminal_growth}) — terminal "
            "value undefined; treated as zero."
        )
        terminal_value = Decimal(0)
        pv_terminal = Decimal(0)
    else:
        terminal_sustainable = sustainable_payout_ratio(terminal_growth, roe)
        terminal_payout = (
            min(terminal_payout_ratio, terminal_sustainable)
            if terminal_sustainable is not None
            else terminal_payout_ratio
        )
        last_eps = years[-1].eps if years else base_eps
        terminal_dividend_next = last_eps * (Decimal(1) + terminal_growth) * terminal_payout
        terminal_value = terminal_dividend_next / (cost_of_equity - terminal_growth)
        pv_terminal = terminal_value / ((Decimal(1) + cost_of_equity) ** year_num) if year_num else terminal_value

    value = pv_explicit + pv_terminal if not (cost_of_equity <= terminal_growth) else None
    if value is None:
        value = pv_explicit  # explicit stage is still a real, if incomplete, lower bound

    return MultiStageDDMResult(
        years=tuple(years),
        pv_explicit_dividends=pv_explicit,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal,
        value_per_share=value,
        warnings=tuple(warnings),
    )


# --- §19.3 Residual income -------------------------------------------------


@dataclass(frozen=True)
class ResidualIncomeYear:
    year: int
    beginning_book_value: Decimal
    roe: Decimal
    residual_income: Decimal
    ending_book_value: Decimal


@dataclass(frozen=True)
class ResidualIncomeResult:
    years: tuple[ResidualIncomeYear, ...]
    pv_explicit_residual_income: Decimal
    terminal_residual_income_value: Decimal
    pv_terminal_residual_income: Decimal
    value_per_share: Decimal | None
    warnings: tuple[str, ...]


def compute_residual_income(
    book_value_per_share_t0: Decimal,
    cost_of_equity: Decimal,
    roe_forecast_path: tuple[Decimal, ...],
    book_value_growth_path: tuple[Decimal, ...],
    terminal_roe: Decimal,
    terminal_growth: Decimal,
) -> ResidualIncomeResult:
    """§19.3: "V0 = Book value + Σ[(ROE_t - Ke) × Book_t-1] ÷ (1+Ke)^t +
    terminal residual income." `roe_forecast_path` and
    `book_value_growth_path` must be the same length — one entry per
    explicit forecast year. §19.3 does not itself specify how book value
    should grow year to year (that's a DDM/retention-rate question, not a
    residual-income one); this module takes the growth path as an
    explicit input, the same "never a free parameter left implicit"
    discipline §18.2 states for the DCF. For internal consistency the
    caller should generally set `book_value_growth_path[t] == roe_
    forecast_path[t] × retention_rate_t` (i.e. book grows only by
    retained earnings) — this function does not enforce that, the same
    way `app.domain.dcf` doesn't enforce sector-median growth is "correct."
    """
    if len(roe_forecast_path) != len(book_value_growth_path):
        return ResidualIncomeResult(
            years=(),
            pv_explicit_residual_income=Decimal(0),
            terminal_residual_income_value=Decimal(0),
            pv_terminal_residual_income=Decimal(0),
            value_per_share=None,
            warnings=(
                f"roe_forecast_path ({len(roe_forecast_path)} years) and "
                f"book_value_growth_path ({len(book_value_growth_path)} years) "
                "must be the same length.",
            ),
        )

    warnings: list[str] = []
    years: list[ResidualIncomeYear] = []
    book_prior = book_value_per_share_t0
    for i, (roe_t, growth_t) in enumerate(zip(roe_forecast_path, book_value_growth_path), start=1):
        ri_t = (roe_t - cost_of_equity) * book_prior
        book_t = book_prior * (Decimal(1) + growth_t)
        years.append(ResidualIncomeYear(i, book_prior, roe_t, ri_t, book_t))
        book_prior = book_t

    n = len(years)
    pv_explicit = sum(
        (y.residual_income / ((Decimal(1) + cost_of_equity) ** y.year) for y in years),
        Decimal(0),
    )

    if cost_of_equity <= terminal_growth:
        warnings.append(
            f"Ke ({cost_of_equity}) <= terminal_growth ({terminal_growth}) — terminal "
            "residual income value undefined; treated as zero."
        )
        terminal_value = Decimal(0)
        pv_terminal = Decimal(0)
    else:
        terminal_ri_next = (terminal_roe - cost_of_equity) * book_prior
        terminal_value = terminal_ri_next / (cost_of_equity - terminal_growth)
        pv_terminal = terminal_value / ((Decimal(1) + cost_of_equity) ** n) if n else terminal_value

    value_per_share = book_value_per_share_t0 + pv_explicit + pv_terminal

    return ResidualIncomeResult(
        years=tuple(years),
        pv_explicit_residual_income=pv_explicit,
        terminal_residual_income_value=terminal_value,
        pv_terminal_residual_income=pv_terminal,
        value_per_share=value_per_share,
        warnings=tuple(warnings),
    )
