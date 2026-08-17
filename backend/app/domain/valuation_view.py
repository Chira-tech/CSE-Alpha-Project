"""
Bridges stored fundamentals, ratios, cost of equity, archetype routing
and live prices to the pure §18-26 valuation modules — the I/O layer
those modules deliberately don't have, the same split
`app.domain.cost_of_equity_view` and `app.domain.fundamentals_view`
already draw for §17 and §12-13.

THE ONE RULE THIS MODULE ENFORCES THAT `app.domain.fundamentals_view`
DELIBERATELY DOESN'T. `fundamentals_view.ratios_for` intentionally shows
AI-assisted ratios (with a provenance chip, on the company file) because
a ratio is displayed there as a fact about the company, chip and all — a
FAIR VALUE is a different kind of claim. §8 is explicit: an AI-assisted
figure "cannot enter a valuation until human-confirmed and promoted to
Reported." This module re-selects line items itself
(`_confirmable_line_items`), filtered through
`app.domain.provenance.can_enter_valuation`, rather than reusing
`fundamentals_view.latest_period_line_items`, specifically so that
boundary can never be silently skipped for a number that ends up on a
price ladder. A period with only AI-assisted figures produces no
valuation here at all — `excluded_unconfirmed_lines` says which lines
were held back and why, rather than the output quietly using them anyway.

WHICH OF §18-26'S NINE MODELS THIS ACTUALLY WIRES UP, AND WHY. Justified
P/B (§20.2), residual income (§19.3) AND, as of this session, the full
multi-year FCFF DCF (§18.1/§18.2, `dcf_for`) all run as real "intrinsic"/
"relative" triangulation anchors against live data — see
`app.domain.dividend_residual_income`, `app.domain.relative_valuation`
and `app.domain.dcf`'s own module docstrings, and `dcf_for`'s own
docstring below for exactly which of the DCF's many assumptions are real
extracted figures versus named, disclosed "no view" defaults (never a
silent guess). `current_period_fcff_for` stays a separate,
informational-only number — §18.1's FCFF formula applied to one real
confirmed period without any discounting — genuinely useful for
inspecting one period's raw cash generation, but never a triangulation
anchor itself: a single undiscounted period's cash flow is not a
per-share fair value, which is exactly what `dcf_for` now IS, once
`dcf_for`'s own multi-year forecast wiring is available for a company.
`gordon_growth_ddm_for` adds one more informational-only number: §19.1's
Gordon-growth DDM, wired to `app.models.corporate_actions.CorporateAction`
rows of type `DIVIDEND_CASH` — a real, working ingestion pipeline
(`app.ingestion.corporate_actions_loader`) already scrapes these from
real CSE dividend announcements, but §8/§9 never lets ingestion
auto-confirm one (`confirmed_by`/`confirmed_at` start `None`; only a
human confirm-queue workflow, not yet built, sets them). That means the
live dev database has, as of this writing, ZERO confirmed dividend rows
for any ticker — this is expected, not a bug, and is exactly why the
result is informational only rather than a triangulation anchor: the
code path is real, correct, and tested against seeded data, ready the
day a human confirms the first real row, but a Gordon-growth DDM with no
confirmed dividend history behind it in production is not ready to move
a price ladder. See `gordon_growth_ddm_for`'s own docstring for the
trailing-twelve-months/D1 mechanics. SOTP stays entirely unwired —
segment data still isn't extracted anywhere in this system.

THE RESIDUAL INCOME FORECAST USED HERE IS DELIBERATELY THE FLAT-
PERSISTENCE CASE, NOT A FORECAST OF IMPROVEMENT. `compute_residual_
income` wants a multi-year ROE path; this system has no analyst forecast
or trend model that could honestly generate one (§13's trend detection
answers "has ROE been rising," not "will it keep rising," and most
companies have too few periods stored for that question to be
answerable at all yet). Projecting the latest confirmed ROE forward
unchanged, for one explicit year, is the standard "no view" baseline in
valuation practice — it says "if nothing changes, this is what the
company is worth today," not "we predict improvement" — and is the only
forecast this module can make without manufacturing false precision from
a single data point, exactly the failure `app.domain.trend_detection`'s
own docstring already warns about for a "trend" read off too little
history.

`settings.long_run_nominal_growth_pct` (PARAMETERS.md #11) supplies `g`
for both models — a policy default, not something computed, same
category as `erp_effective_pct`. It is clamped below the live risk-free
rate before use, per §18.2's own discipline ("never exceeds the
risk-free rate — a company growing faster than the risk-free rate
forever is worth infinity"), rather than trusted as already-safe.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.dcf import DCFAssumptions, DCFResult, compute_fcff, dcf_equity_value
from app.domain.wacc import WACCResult, compute_cost_of_debt, compute_wacc
from app.domain.dividend_residual_income import (
    GordonGrowthResult,
    ResidualIncomeResult,
    compute_residual_income,
    gordon_growth_value,
)
from app.domain.margin_of_safety import MarginOfSafetyResult, compute_margin_of_safety
from app.domain.point_in_time import fundamentals_as_of
from app.domain.price_ladder import PriceLadderResult, compute_price_ladder
from app.domain.provenance import can_enter_valuation
from app.domain.ratios import LineItem, compute_all
from app.domain.relative_valuation import JustifiedMultipleResult, justified_price_to_book
from app.domain.triangulation import TriangulationResult, ValuationAnchor, triangulate
from app.domain.valuation_router import RoutingDecision, route_valuation
from app.models.corporate_actions import CorporateAction
from app.models.enums import CorporateActionType
from app.models.float_data import FloatData


def _confirmable_line_items(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[dt.date | None, dict[str, LineItem], tuple[str, ...]]:
    """The latest point-in-time-visible period's line items, restricted to
    tiers `can_enter_valuation` allows (§8). Returns
    `(period_end, items, excluded_lines)` — `excluded_lines` names any
    statement line that exists for the period but was held back because
    it is still AI-assisted/unconfirmed, so a caller can say why a figure
    is missing rather than just that it is."""
    rows = fundamentals_as_of(db, ticker, as_of)
    if not rows:
        return None, {}, ()

    latest_period = max(r.period_end for r in rows)
    items: dict[str, LineItem] = {}
    excluded: set[str] = set()
    for row in rows:
        if row.period_end != latest_period:
            continue
        if not can_enter_valuation(row.provenance_tier):
            excluded.add(row.statement_line)
            continue
        if row.statement_line not in items:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)

    return latest_period, items, tuple(sorted(excluded))


def _latest_shares_issued(db: Session, ticker: str, as_of: dt.date) -> int | None:
    row = db.scalar(
        select(FloatData)
        .where(FloatData.ticker == ticker, FloatData.as_of <= as_of)
        .order_by(FloatData.as_of.desc())
        .limit(1)
    )
    return row.shares_issued if row else None


def _confirmed_statement_line_history(
    db: Session, ticker: str, statement_line: str, as_of: dt.date
) -> list[tuple[dt.date, Decimal]]:
    """Every point-in-time-visible, §8-confirmable value for ONE canonical
    line across ALL periods — not just the latest, the way
    `_confirmable_line_items` deliberately restricts itself — sorted
    oldest first. This is what a trailing multi-year growth rate needs
    and nothing else in this module has queried for yet. Mirrors
    `_confirmable_line_items`'s point-in-time (`fundamentals_as_of`) and
    §8 provenance (`can_enter_valuation`) filtering exactly, just across
    periods instead of within one."""
    rows = fundamentals_as_of(db, ticker, as_of, statement_line=statement_line)
    by_period: dict[dt.date, Decimal] = {
        row.period_end: row.value for row in rows if can_enter_valuation(row.provenance_tier)
    }
    return sorted(by_period.items())


def _trailing_cagr(history: list[tuple[dt.date, Decimal]]) -> Decimal | None:
    """§18.2's own stated primary source for DCF Years 1-2 growth:
    "Trailing 3-year CAGR". Computed here over however much confirmed
    history actually exists — this system does not yet have 3 full years
    of confirmed fundamentals for any real company (ingestion has so far
    verified one period per company against a live-downloaded PDF, not
    run the multi-year archive loader through to confirmation), so this
    is written to work correctly with as few as 2 periods and to return
    `None`, not a fabricated number, when fewer than that exist —
    `dcf_for` below falls back to a disclosed no-growth-view assumption
    in that case rather than inventing a distinct forecast number.

    Annualised by the ACTUAL elapsed time between the oldest and newest
    period (via `/ 365.25`) rather than assumed to be exactly N whole
    years, because a restated or irregular period should not be silently
    treated as a full year. `None` when the oldest or newest value isn't
    positive (a loss-to-profit swing, or vice versa, has no meaningful
    compound growth rate) or the elapsed time isn't positive.
    """
    if len(history) < 2:
        return None
    (start_date, start_value), (end_date, end_value) = history[0], history[-1]
    if start_value <= 0 or end_value <= 0:
        return None
    years = (end_date - start_date).days / 365.25
    if years <= 0:
        return None
    # Decimal has no fractional-exponent power operator; converting to
    # float for this one non-integer-power step and back via `str()` is
    # this project's own established idiom (see
    # `app.domain.trend_detection`'s `math.sqrt(float(variance))` for the
    # precedent), not a new pattern invented here.
    growth = (float(end_value) / float(start_value)) ** (1.0 / years) - 1.0
    return Decimal(str(growth))


def _steady_state_growth(risk_free_rate: Decimal | None) -> Decimal:
    """§18.2: terminal/steady-state growth "never exceeds the risk-free
    rate." Clamped here rather than trusting the configured default is
    already safe, because `settings.long_run_nominal_growth_pct` is a
    fixed policy constant while `risk_free_rate` moves with real CBSL
    data — the two could fall out of that relationship at any time."""
    g = settings.long_run_nominal_growth_pct
    if risk_free_rate is not None and g >= risk_free_rate:
        return risk_free_rate - Decimal("0.01")
    return g


@dataclass(frozen=True)
class LiveValuationInputs:
    """What was actually available for this company, before any model
    ran — so a `None` fair value downstream is traceable to a specific
    named cause rather than a dead end."""

    period_end: dt.date | None
    roe: Decimal | None
    cost_of_equity: Decimal | None
    growth_rate: Decimal
    book_value_per_share: Decimal | None
    shares_issued: int | None
    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def _gather_inputs(db: Session, ticker: str, as_of: dt.date) -> LiveValuationInputs:
    warnings: list[str] = []

    period_end, items, excluded = _confirmable_line_items(db, ticker, as_of)
    if excluded:
        warnings.append(
            f"{excluded} present for this period but still AI-assisted/unconfirmed — "
            "excluded from valuation per §8 (would show on the company file's ratio "
            "table with a provenance chip, but cannot enter a fair value)."
        )
    if period_end is None:
        warnings.append("No fundamentals visible as of this date at all.")

    roe = None
    if items:
        roe_result = next((r for r in compute_all(items) if r.key == "return_on_equity"), None)
        if roe_result is not None and roe_result.computable:
            roe = roe_result.value
        else:
            warnings.append(
                "ROE not computable from confirmed fundamentals"
                + (f" ({roe_result.note})" if roe_result and roe_result.note else ".")
            )

    ke_result = cost_of_equity_for(db, ticker, as_of)
    if ke_result.ke is None:
        warnings.append(f"Cost of equity not computable: {ke_result.note}")

    growth_rate = _steady_state_growth(ke_result.risk_free_rate)

    book_value_per_share = None
    total_equity_item = items.get("total_equity")
    shares = _latest_shares_issued(db, ticker, as_of)
    if total_equity_item is None:
        warnings.append("total_equity not available from confirmed fundamentals.")
    if shares is None:
        warnings.append("shares_issued not available (no FloatData row on or before this date).")
    if total_equity_item is not None and shares:
        book_value_per_share = total_equity_item.value / Decimal(shares)

    return LiveValuationInputs(
        period_end=period_end,
        roe=roe,
        cost_of_equity=ke_result.ke,
        growth_rate=growth_rate,
        book_value_per_share=book_value_per_share,
        shares_issued=shares,
        excluded_unconfirmed_lines=excluded,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class JustifiedPBView:
    inputs: LiveValuationInputs
    result: JustifiedMultipleResult | None
    fair_value_per_share: Decimal | None


def justified_price_to_book_for(
    db: Session, ticker: str, as_of: dt.date | None = None
) -> JustifiedPBView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(db, ticker, stamp)

    if inputs.roe is None or inputs.cost_of_equity is None:
        return JustifiedPBView(inputs, None, None)

    result = justified_price_to_book(inputs.roe, inputs.growth_rate, inputs.cost_of_equity)
    fair_value = (
        result.value * inputs.book_value_per_share
        if result.value is not None and inputs.book_value_per_share is not None
        else None
    )
    return JustifiedPBView(inputs, result, fair_value)


@dataclass(frozen=True)
class ResidualIncomeView:
    inputs: LiveValuationInputs
    result: ResidualIncomeResult | None


def residual_income_for(db: Session, ticker: str, as_of: dt.date | None = None) -> ResidualIncomeView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(db, ticker, stamp)

    if inputs.roe is None or inputs.cost_of_equity is None or inputs.book_value_per_share is None:
        return ResidualIncomeView(inputs, None)

    result = compute_residual_income(
        book_value_per_share_t0=inputs.book_value_per_share,
        cost_of_equity=inputs.cost_of_equity,
        roe_forecast_path=(inputs.roe,),
        book_value_growth_path=(inputs.growth_rate,),
        terminal_roe=inputs.roe,
        terminal_growth=inputs.growth_rate,
    )
    return ResidualIncomeView(inputs, result)


@dataclass(frozen=True)
class CurrentPeriodFCFFView:
    period_end: dt.date | None
    fcff: Decimal | None
    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def current_period_fcff_for(
    db: Session, ticker: str, as_of: dt.date | None = None
) -> CurrentPeriodFCFFView:
    """§18.1's FCFF formula applied to ONE real, confirmed period — NOT a
    DCF valuation. `dcf_for`, below, is now the real multi-year DCF this
    project has; this function stays as the honestly-scoped smaller
    thing it always was: the trailing-period FCFF number itself, useful
    for inspecting one period's raw cash generation in isolation from any
    discounting or forecast assumption, the first of §18's figures this
    system ever computed from live extracted data rather than only
    hand-worked test inputs. Deliberately NOT fed into `valuation_
    summary_for`'s triangulation anchors — an undiscounted single-period
    cash flow is not a per-share fair value, and treating it as one would
    be exactly the "confident, precise, entirely fictional number" §15
    warns about.

    EBIT IS APPROXIMATED AS `operating_profit`. This extractor has no
    canonical `ebit` line distinct from `operating_profit` to compare
    against — for the CSE income-statement presentations verified so far
    (revenue → cost of sales → gross profit → operating profit → then
    financing items), the two normally coincide, but a company with
    material non-operating income or expense recognised before its
    financing line would make this a genuine approximation, not a
    citation error — stated here rather than silently assumed exact.
    """
    stamp = as_of or dt.date.today()
    period_end, items, excluded = _confirmable_line_items(db, ticker, stamp)
    warnings: list[str] = []
    if excluded:
        warnings.append(
            f"{excluded} present for this period but still AI-assisted/unconfirmed — "
            "excluded from this figure per §8."
        )
    if period_end is None:
        warnings.append("No fundamentals visible as of this date at all.")
        return CurrentPeriodFCFFView(period_end, None, excluded, tuple(warnings))

    tax_result = next((r for r in compute_all(items) if r.key == "effective_tax_rate"), None)
    required = {
        "operating_profit (EBIT proxy)": items.get("operating_profit"),
        "depreciation_and_amortisation": items.get("depreciation_and_amortisation"),
        "capital_expenditure": items.get("capital_expenditure"),
        "change_in_net_working_capital": items.get("change_in_net_working_capital"),
    }
    missing = [name for name, item in required.items() if item is None]
    if tax_result is None or not tax_result.computable:
        missing.append("effective_tax_rate (needs income_tax_expense and profit_before_tax)")

    if missing:
        warnings.append(f"FCFF not computable — missing: {', '.join(missing)}.")
        return CurrentPeriodFCFFView(period_end, None, excluded, tuple(warnings))

    fcff = compute_fcff(
        ebit=required["operating_profit (EBIT proxy)"].value,
        effective_tax_rate=tax_result.value,
        depreciation_amortisation=required["depreciation_and_amortisation"].value,
        # Extracted as a negative cash outflow (the cash-flow statement's
        # own printed convention); compute_fcff wants the positive
        # magnitude it subtracts.
        capital_expenditure=abs(required["capital_expenditure"].value),
        change_in_net_working_capital=required["change_in_net_working_capital"].value,
    )
    return CurrentPeriodFCFFView(period_end, fcff, excluded, tuple(warnings))


@dataclass(frozen=True)
class WACCView:
    period_end: dt.date | None
    result: WACCResult | None
    warnings: tuple[str, ...]


def wacc_for(
    db: Session, ticker: str, current_price: Decimal | None, as_of: dt.date | None = None
) -> WACCView:
    """§18.1's discount rate for an FCFF projection — see
    `app.domain.wacc`'s own module docstring for why this must never be
    approximated as Ke for a levered company (mixing an unlevered cash
    flow with a levered discount rate systematically overstates DCF
    value for any company carrying debt).

    Genuinely live-computable now: `total_interest_bearing_debt` and
    `interest_expense` both extract from a Swadeshi-shaped filing (see
    `app.domain.financial_statement_parsing`'s `SUM_ACROSS_OCCURRENCES`
    for the real current/non-current maturity-split debt line this
    needed), and `effective_tax_rate`/`cost_of_equity`/shares/price were
    all already available. This WACC is now consumed directly as `dcf_
    for`'s discount rate — see that function's own docstring for the full
    multi-year DCF this unlocked, once the working-capital STOCK gap
    (also since closed — `app.domain.financial_statement_parsing`'s
    `net_working_capital` derivation) was closed too.
    """
    stamp = as_of or dt.date.today()
    period_end, items, excluded = _confirmable_line_items(db, ticker, stamp)
    warnings: list[str] = []
    if excluded:
        warnings.append(
            f"{excluded} present for this period but still AI-assisted/unconfirmed — "
            "excluded from this figure per §8."
        )
    if period_end is None:
        warnings.append("No fundamentals visible as of this date at all.")
        return WACCView(period_end, None, tuple(warnings))

    tax_result = next((r for r in compute_all(items) if r.key == "effective_tax_rate"), None)
    debt_item = items.get("total_interest_bearing_debt")
    interest_item = items.get("interest_expense")

    cost_of_debt = compute_cost_of_debt(
        interest_expense=interest_item.value if interest_item else None,
        total_interest_bearing_debt=debt_item.value if debt_item else None,
        effective_tax_rate=tax_result.value if tax_result and tax_result.computable else None,
    )

    ke_result = cost_of_equity_for(db, ticker, stamp)
    shares = _latest_shares_issued(db, ticker, stamp)

    result = compute_wacc(
        shares_outstanding=Decimal(shares) if shares else None,
        current_price=current_price,
        total_interest_bearing_debt=debt_item.value if debt_item else None,
        cost_of_equity=ke_result.ke,
        after_tax_cost_of_debt=cost_of_debt.after_tax_cost_of_debt,
    )
    if result.wacc is None:
        warnings.append(result.note)
    return WACCView(period_end, result, tuple(warnings))


def _confirmed_dividends_as_of(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[CorporateAction, ...]:
    """§8/§9's provenance gate, applied to `CorporateAction` rather than
    `Fundamental` — `_confirmable_line_items` restricts a `Fundamental`
    row by provenance TIER (AI-assisted vs Reported); `CorporateAction`
    has no tier at all, only a binary "drafted by the scraper, still
    unconfirmed" vs "a human set `confirmed_by`/`confirmed_at`" state
    (see `CorporateAction.is_confirmed`), because §5 calls this "the
    highest-consequence data in the system" and the ingestion loader
    (`app.ingestion.corporate_actions_loader`) is explicit that it never
    auto-promotes a draft. The gate here is therefore just
    `confirmed_by is not None` rather than a `can_enter_valuation` tier
    check — same discipline, different shape because the underlying
    table is shaped differently.

    Point-in-time visible as of `as_of` via `ex_date <= as_of`, mirroring
    §6 even though `CorporateAction` has no `first_available_date` column
    of its own to run through `app.domain.point_in_time.fundamentals_
    as_of`. This is, if anything, conservative rather than a gap: CSE
    publishes a dividend declaration before the security actually goes
    ex-dividend, so gating on `ex_date` rather than the (unstored)
    announcement date means a row only becomes visible here at least as
    late as the market itself would have priced it in, never earlier.

    Restricted to `DIVIDEND_CASH` — the only `CorporateActionType` a
    Gordon-growth DDM cares about; bonus issues, splits, rights issues
    etc. affect share count or price, not the dividend stream. Returned
    oldest-to-newest so callers summing a trailing window don't need to
    sort again.
    """
    rows = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.ticker == ticker,
            CorporateAction.type == CorporateActionType.DIVIDEND_CASH,
            CorporateAction.ex_date <= as_of,
            CorporateAction.confirmed_by.is_not(None),
        )
        .order_by(CorporateAction.ex_date.asc())
    ).all()
    return tuple(rows)


def _trailing_dividend_per_share(
    dividends: tuple[CorporateAction, ...], as_of: dt.date
) -> tuple[Decimal | None, int]:
    """Sums `cash_amount` across every confirmed `DIVIDEND_CASH` row whose
    `ex_date` falls in the trailing twelve months ending on `as_of`
    (inclusive) — deliberately a TTM sum, not just the single most recent
    payment. A CSE-listed company routinely declares an interim AND a
    final dividend within the same year; treating whichever single
    payment happens to be most recent as "the" annual rate would
    understate a company that pays twice a year and overstate one that
    just paid its only annual dividend, depending purely on where `as_of`
    happens to fall in the cycle. Summing the trailing-twelve-month
    window is the only one of these that doesn't depend on that
    coincidence.

    Returns `(None, 0)` — not zero — when no confirmed dividend falls in
    that window at all, even if older confirmed rows exist further back.
    A dividend from more than a year ago is stale as an estimate of what
    this company currently pays; reporting a number derived from it
    without any qualification would misrepresent stale history as a
    current rate, the same "confident, precise, entirely fictional
    number" §15 warns the whole valuation engine exists never to produce.
    """
    window_start = as_of - dt.timedelta(days=365)
    in_window = [
        d for d in dividends if window_start < d.ex_date <= as_of and d.cash_amount is not None
    ]
    if not in_window:
        return None, 0
    total = sum((d.cash_amount for d in in_window), Decimal(0))
    return total, len(in_window)


@dataclass(frozen=True)
class DDMView:
    as_of: dt.date
    """Not a `Fundamental` period_end — there is no fundamentals period
    behind this figure at all, only a trailing dividend window ending on
    this date. Named `as_of` rather than `period_end`, unlike `WACCView`/
    `CurrentPeriodFCFFView`, for that reason, while keeping the same
    three-field (marker, result, warnings) shape those views established."""

    result: GordonGrowthResult | None
    warnings: tuple[str, ...]


def gordon_growth_ddm_for(db: Session, ticker: str, as_of: dt.date | None = None) -> DDMView:
    """§19.1's Gordon-growth DDM (`V0 = D1 / (Ke - g)`) wired to real —
    if, for essentially every ticker today, currently EMPTY — confirmed
    dividend history. "Real but empty" is a specific, checkable claim,
    not a euphemism for fabricated: `_confirmed_dividends_as_of` runs a
    genuine query against `CorporateAction` rows a real scraper
    (`app.ingestion.corporate_actions_loader`) populated from real CSE
    announcements; what's missing is only the human confirmation step
    §8/§9 requires before any of those rows may feed a valuation, which
    is a deliberate, not-yet-built workflow gap, not a data gap. The day
    a human confirms the first real dividend row for a ticker, this
    function starts returning a real number for it with no code change.

    D1, THE MODEL'S OWN REQUIRED INPUT, IS DERIVED FROM D0 RATHER THAN A
    SEPARATE INVENTED NUMBER. This system has no dividend-growth forecast
    (no analyst estimates, no trend model — the same absence
    `_steady_state_growth`'s own docstring already explains for `g`
    itself), so there is no honest way to produce a D1 distinct from
    "the trailing actual, carried forward at the same flat steady-state
    rate everything else in this module uses." `_trailing_dividend_per_
    share` supplies D0 (the real trailing-twelve-month sum); D1 = D0 x
    (1 + g), using the SAME `_steady_state_growth(risk_free_rate)` this
    module already computes for justified P/B and residual income — not
    a new policy constant, just Gordon growth's own D1 = D0(1+g)
    identity applied with the one growth rate this system can honestly
    produce.

    `check_gordon_growth_eligibility` (§19.1's "stable payout for five
    years, growth below Ke, mature business" gate) is deliberately NOT
    run here: it needs five years of payout-ratio history and a
    mature-business flag neither of which this system tracks yet. Not
    gating on it is consistent with, not a workaround for, this result
    being informational only — `valuation_summary_for` never treats it
    as a triangulation anchor regardless, so there's no eligibility gate
    left to skip.
    """
    stamp = as_of or dt.date.today()

    dividends = _confirmed_dividends_as_of(db, ticker, stamp)
    if not dividends:
        return DDMView(
            stamp,
            None,
            (
                "No confirmed DIVIDEND_CASH corporate actions exist for this ticker as of "
                "this date. Per §8/§9, a scraped dividend draft is real (see "
                "app.ingestion.corporate_actions_loader) but is never auto-confirmed — a "
                "human confirm-queue workflow, not yet built, must set confirmed_by before a "
                "dividend can feed a valuation. This is the expected state for every ticker "
                "today, not an error.",
            ),
        )

    trailing_dps, count = _trailing_dividend_per_share(dividends, stamp)
    if trailing_dps is None:
        oldest, newest = dividends[0].ex_date, dividends[-1].ex_date
        return DDMView(
            stamp,
            None,
            (
                f"{len(dividends)} confirmed dividend(s) exist for this ticker (ex_date "
                f"{oldest} to {newest}) but none fall within the trailing twelve months of "
                f"{stamp} — no current per-share rate can be estimated from dividend history "
                "this stale without misrepresenting it as current.",
            ),
        )

    warnings: list[str] = []
    if count > 1:
        warnings.append(
            f"Trailing dividend per share is the sum of {count} confirmed payments within "
            "the trailing twelve months (e.g. an interim plus a final dividend), not a "
            "single declaration."
        )

    ke_result = cost_of_equity_for(db, ticker, stamp)
    if ke_result.ke is None:
        warnings.append(f"Cost of equity not computable: {ke_result.note}")
        return DDMView(stamp, None, tuple(warnings))

    g = _steady_state_growth(ke_result.risk_free_rate)
    next_year_dividend = trailing_dps * (Decimal(1) + g)
    result = gordon_growth_value(next_year_dividend, ke_result.ke, g)
    if result.value_per_share is None:
        warnings.append(result.note)
    return DDMView(stamp, result, tuple(warnings))


@dataclass(frozen=True)
class DCFView:
    period_end: dt.date | None
    result: DCFResult | None
    fair_value_per_share: Decimal | None
    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def dcf_for(
    db: Session, ticker: str, current_price: Decimal | None, as_of: dt.date | None = None
) -> DCFView:
    """§18's full three-stage FCFF DCF (`app.domain.dcf.dcf_equity_value`),
    finally wired to live data — the multi-year forecast wiring that
    `current_period_fcff_for` and `wacc_for`'s own docstrings both named
    as the remaining, genuinely separate gap once every raw cash-flow
    input and the discount rate became individually extractable. This
    function is where that gap closes, for whichever company has every
    input below.

    EVERY ASSUMPTION IS EITHER REAL OR A NAMED, DISCLOSED "NO VIEW"
    DEFAULT — NEVER A SILENT GUESS. §18.2's own rule ("never a free
    parameter") is honoured the same way `_gather_inputs` already honours
    it for residual income, just with more moving parts:

      - `base_revenue`, `operating_margin_current` (= EBIT proxy ÷
        revenue), `effective_tax_rate_current`, `depreciation_
        amortisation_pct_revenue`, `capex_pct_revenue` and
        `working_capital_pct_revenue` are all ratios of ONE real
        confirmed period's extracted figures — real, not assumed.
      - `operating_margin_target` = `operating_margin_current` — the
        SAME "no fade, durable advantage, stated explicitly" convention
        `DCFAssumptions.operating_margin_target`'s own docstring already
        names, reused here rather than invented fresh.
      - `statutory_tax_rate` = `settings.statutory_corporate_tax_rate_pct`
        — Sri Lanka's real, current, IRD-published rate (PARAMETERS.md
        #12), not a placeholder.
      - `revenue_growth_y1`/`revenue_growth_y2` use the REAL trailing
        CAGR (`_trailing_cagr`) over however many confirmed revenue
        periods exist for this ticker when there are at least two;
        otherwise they fall back to the same steady-state `g` below,
        clearly flagged in `warnings` either way so a caller can tell a
        real historical growth number from a disclosed no-growth-view
        default apart.
      - `revenue_growth_stage2_target` and `terminal_growth` both use
        `_steady_state_growth` — the SAME sourced, risk-free-rate-capped
        policy figure (`settings.long_run_nominal_growth_pct`,
        PARAMETERS.md #11) residual income already uses for its own
        terminal assumption, not a sector-median figure this system has
        no source for (that source is Phase 5's macro engine, and stays
        genuinely absent).
      - `risk_free_rate` and `discount_rate` (WACC, never Ke — see
        `app.domain.wacc`'s own docstring) both come from this module's
        own already-live `cost_of_equity_for`/`wacc_for`.
      - `total_debt` = the real, extracted `total_interest_bearing_debt`.
      - `cash_and_non_operating_assets`, `minority_interest` and
        `pension_deficit` are NOT extracted anywhere in this system and
        default to zero — for `cash_and_non_operating_assets` this is
        the SAFE direction (omitting real cash can only UNDERSTATE
        equity value, never overstate it, the same reasoning
        `app.domain.cost_of_equity`'s missing premiums already use); for
        `minority_interest`/`pension_deficit` zero is the DANGEROUS
        direction (omitting either can only OVERSTATE equity value for
        any company that actually carries one), so those two are
        flagged explicitly in `warnings` every time this function runs,
        the same discipline `app.domain.wacc`'s missing-cost-of-debt
        rule already established for a directionally-unsafe default —
        disclosed rather than silently zeroed and left unflagged.

    Wired as a genuine "intrinsic" §24 triangulation anchor (`valuation_
    summary_for`), the same category as residual income — both now share
    the identical "flat/no-improvement-assumed, real-data-only" honesty
    this project's residual-income docstring first established, so
    treating one as an anchor and not the other would be the
    inconsistency, not treating both as one.
    """
    stamp = as_of or dt.date.today()
    period_end, items, excluded = _confirmable_line_items(db, ticker, stamp)
    warnings: list[str] = []
    if excluded:
        warnings.append(
            f"{excluded} present for this period but still AI-assisted/unconfirmed — "
            "excluded from this figure per §8."
        )
    if period_end is None:
        warnings.append("No fundamentals visible as of this date at all.")
        return DCFView(period_end, None, None, excluded, tuple(warnings))

    tax_result = next((r for r in compute_all(items) if r.key == "effective_tax_rate"), None)
    required = {
        "revenue": items.get("revenue"),
        "operating_profit (EBIT proxy)": items.get("operating_profit"),
        "depreciation_and_amortisation": items.get("depreciation_and_amortisation"),
        "capital_expenditure": items.get("capital_expenditure"),
        "net_working_capital": items.get("net_working_capital"),
        "total_interest_bearing_debt": items.get("total_interest_bearing_debt"),
    }
    missing = [name for name, item in required.items() if item is None]
    if required["revenue"] is not None and required["revenue"].value <= 0:
        missing.append("revenue (must be positive to project margins/percentages from)")
    if tax_result is None or not tax_result.computable:
        missing.append("effective_tax_rate (needs income_tax_expense and profit_before_tax)")

    wacc_view = wacc_for(db, ticker, current_price, stamp)
    if wacc_view.result is None or wacc_view.result.wacc is None:
        missing.append(
            "WACC (" + (wacc_view.result.note if wacc_view.result else "not computable") + ")"
        )

    ke_result = cost_of_equity_for(db, ticker, stamp)
    if ke_result.risk_free_rate is None:
        missing.append("risk_free_rate (needed to cap terminal/stage-2 growth)")

    shares = _latest_shares_issued(db, ticker, stamp)
    if not shares:
        missing.append("shares_issued (no FloatData row on or before this date)")

    if missing:
        warnings.append(f"DCF not computable — missing: {', '.join(missing)}.")
        return DCFView(period_end, None, None, excluded, tuple(warnings))

    revenue = required["revenue"].value
    ebit = required["operating_profit (EBIT proxy)"].value
    da = required["depreciation_and_amortisation"].value
    # Extracted as a negative cash outflow (the cash-flow statement's own
    # printed convention) — same sign-flip `current_period_fcff_for`
    # already applies.
    capex = abs(required["capital_expenditure"].value)
    nwc = required["net_working_capital"].value
    debt = required["total_interest_bearing_debt"].value

    operating_margin_current = ebit / revenue

    revenue_history = _confirmed_statement_line_history(db, ticker, "revenue", stamp)
    trailing_growth = _trailing_cagr(revenue_history)
    steady_state_g = _steady_state_growth(ke_result.risk_free_rate)
    if trailing_growth is not None:
        revenue_growth_y1 = revenue_growth_y2 = trailing_growth
        warnings.append(
            f"Y1/Y2 growth = {trailing_growth:.4f} real trailing CAGR over "
            f"{len(revenue_history)} confirmed revenue periods "
            f"({revenue_history[0][0]} to {revenue_history[-1][0]})."
        )
    else:
        revenue_growth_y1 = revenue_growth_y2 = steady_state_g
        warnings.append(
            "Y1/Y2 growth: fewer than 2 confirmed revenue periods exist for this "
            "ticker yet, so §18.2's trailing-CAGR source isn't available — fell back "
            f"to the same steady-state g ({steady_state_g:.4f}) used for stage-2/"
            "terminal growth, i.e. a 'no growth view' assumption, not a forecast of "
            "acceleration or decline."
        )
    warnings.append(
        "minority_interest and pension_deficit are not extracted anywhere in this "
        "system and default to zero in the equity-value bridge below — this can "
        "only OVERSTATE equity value for a company that actually carries either, "
        "the dangerous direction (same reasoning app.domain.wacc's missing-cost-"
        "of-debt rule already applies), so this fair value should not be trusted "
        "uncritically for a company known to have material minority interests or "
        "a pension deficit."
    )
    warnings.append(
        "cash_and_non_operating_assets also defaults to zero (not extracted yet) — "
        "this is the safe direction, and can only UNDERSTATE equity value."
    )

    assumptions = DCFAssumptions(
        base_revenue=revenue,
        revenue_growth_y1=revenue_growth_y1,
        revenue_growth_y2=revenue_growth_y2,
        revenue_growth_stage2_target=steady_state_g,
        terminal_growth=steady_state_g,
        operating_margin_current=operating_margin_current,
        operating_margin_target=operating_margin_current,
        effective_tax_rate_current=tax_result.value,
        statutory_tax_rate=settings.statutory_corporate_tax_rate_pct,
        depreciation_amortisation_pct_revenue=da / revenue,
        capex_pct_revenue=capex / revenue,
        working_capital_pct_revenue=nwc / revenue,
        risk_free_rate=ke_result.risk_free_rate,
        discount_rate=wacc_view.result.wacc,
        cash_and_non_operating_assets=Decimal(0),
        total_debt=debt,
        minority_interest=Decimal(0),
        pension_deficit=Decimal(0),
        diluted_shares_outstanding=Decimal(shares),
    )
    result = dcf_equity_value(assumptions)
    return DCFView(period_end, result, result.value_per_share, excluded, tuple(warnings))


@dataclass(frozen=True)
class CompanyValuationSummary:
    ticker: str
    as_of: dt.date
    current_price: Decimal | None
    """The price actually passed in to `valuation_summary_for`, kept
    independent of `price_ladder` — a real current price should still be
    reported even when no fair value exists yet to build a ladder from.
    `price_ladder.current_price` and this field are the same value when
    `price_ladder` is not None; this one is the one that's ALWAYS
    populated whenever a price was found, which is the bug this field
    exists to prevent: a caller reading `price_ladder.current_price` and
    getting None can't tell "no price known" from "no fair value yet."""

    routing: RoutingDecision
    justified_pb: JustifiedPBView
    residual_income: ResidualIncomeView
    current_period_fcff: CurrentPeriodFCFFView
    """Informational only — see `current_period_fcff_for`'s own
    docstring for why this is never one of the triangulation anchors
    below."""

    wacc: WACCView
    """Also informational — a discount rate, not a fair value by itself,
    but no longer only that: it is `dcf`'s own discount rate below, so it
    IS consumed now, just not directly displayed as a price."""

    dcf: DCFView
    """§18's full multi-year FCFF DCF — see `dcf_for`'s own docstring for
    exactly which inputs are real and which are named, disclosed
    defaults. A genuine "intrinsic" triangulation anchor below, the same
    category as residual income, when computable."""

    gordon_growth_ddm: DDMView
    """Informational only, same status as `current_period_fcff` and
    `wacc` above, for a distinct reason from either: the code path and
    math are real (§19.1's actual formula run against real, if currently
    unconfirmed, `CorporateAction` rows — see `gordon_growth_ddm_for`'s
    own docstring for exactly what "real but empty" means here), but a
    Gordon-growth DDM built on zero confirmed dividend history in
    production is not ready to move a price ladder. Never one of
    `triangulation`'s anchors below."""

    triangulation: TriangulationResult
    margin_of_safety: MarginOfSafetyResult
    price_ladder: PriceLadderResult | None
    note: str


def valuation_summary_for(
    db: Session, ticker: str, archetype: str | None, current_price: Decimal | None,
    as_of: dt.date | None = None,
) -> CompanyValuationSummary:
    """The full, real, end-to-end Phase 3 pipeline for one company: route
    → the two live-wireable anchors → triangulate → margin of safety →
    price ladder. Every stage is honest about what it could and couldn't
    compute — this function does not paper over a gap by skipping a
    stage silently; `note` on the result, and each sub-result's own
    fields, say what ran and what didn't.
    """
    stamp = as_of or dt.date.today()
    routing = route_valuation(archetype)
    jpb = justified_price_to_book_for(db, ticker, stamp)
    ri = residual_income_for(db, ticker, stamp)
    fcff_view = current_period_fcff_for(db, ticker, stamp)
    wacc_view = wacc_for(db, ticker, current_price, stamp)
    dcf_view = dcf_for(db, ticker, current_price, stamp)
    ddm_view = gordon_growth_ddm_for(db, ticker, stamp)

    anchors: list[ValuationAnchor] = []
    if jpb.fair_value_per_share is not None:
        anchors.append(ValuationAnchor("Justified P/B", "relative", jpb.fair_value_per_share))
    if ri.result is not None and ri.result.value_per_share is not None:
        anchors.append(ValuationAnchor("Residual income", "intrinsic", ri.result.value_per_share))
    if dcf_view.fair_value_per_share is not None:
        anchors.append(ValuationAnchor("FCFF DCF", "intrinsic", dcf_view.fair_value_per_share))

    triangulation = triangulate(routing, tuple(anchors))

    mos = compute_margin_of_safety(
        dispersion_pct=triangulation.dispersion_pct,
        liquidity_percentile=None,  # Amihud percentile — needs turnover history, still blocked (ROADMAP Gate 1)
        regime=None,  # §29-33 regime classifier — Phase 5, not built
        integrity_score=None,  # no continuous integrity score exists anywhere in this system, by design — see margin_of_safety.py
        data_completeness_pct=None,  # not computed at the per-company level anywhere yet
    )

    ladder = None
    if triangulation.blended_fair_value_per_share is not None:
        ladder = compute_price_ladder(
            triangulation.blended_fair_value_per_share, mos.total_pct, current_price
        )

    note = (
        f"{len(anchors)} of 9 §18-26 valuation anchors were live-computable for this "
        f"company ({', '.join(a.method for a in anchors) or 'none'}) — the rest need "
        "data this system does not extract yet (see ROADMAP.md's Phase 3 section). "
        "This is real math on real stored data, not a placeholder, but it is a partial "
        "triangulation, not the full 3-5-anchor blend §24 describes."
    )

    return CompanyValuationSummary(
        ticker=ticker, as_of=stamp, current_price=current_price, routing=routing, justified_pb=jpb,
        residual_income=ri, current_period_fcff=fcff_view, wacc=wacc_view, dcf=dcf_view,
        gordon_growth_ddm=ddm_view,
        triangulation=triangulation, margin_of_safety=mos, price_ladder=ladder, note=note,
    )
