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
P/B (§20.2), residual income (§19.3), the full multi-year FCFF DCF
(§18.1/§18.2, `dcf_for`), AND, as of 23 Aug 2026, justified P/E and
justified P/S (§20.2, `relative_valuation_for`) all run as real
"intrinsic"/"relative" triangulation anchors against live data — see
`app.domain.dividend_residual_income`, `app.domain.relative_valuation`
and `app.domain.dcf`'s own module docstrings, and `dcf_for`'s/
`relative_valuation_for`'s own docstrings below for exactly which
assumptions are real extracted figures versus named, disclosed "no view"
defaults (never a silent guess). Justified P/E and P/S both became
live-computable the same day a real bulk-confirm pass (see
`docs/audits/R1_FIX_LOG.md`) gave this system its first confirmed
`CorporateAction` dividend rows anywhere — `relative_valuation_for`
reuses that exact same trailing-dividend machinery `gordon_growth_ddm_
for` already built, deriving `payout_ratio` from it rather than
inventing a second, separate dividend query. Justified EV/EBIT is the
one sub-multiple of §20.2 that stays genuinely uncomputed — see `relative_
valuation_for`'s own docstring for why fabricating a ROIC to unblock it
would be exactly the false-precision problem §15 exists to prevent.
`app.domain.scenarios`' Bear/Base/Bull set, sensitivity tornado and Monte
Carlo overlay (§23) are wired the same day too, in the sibling module
`app.domain.scenarios_view`, built directly on top of this module's own
`dcf_for` rather than re-deriving a second DCF assumption set — see that
module's own docstring. `current_period_fcff_for` stays a separate,
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

WHAT'S LEFT OF §18-26'S NINE, AS OF THIS PASS. SOTP (§21) is the one
model that stays entirely unwired, and it is a genuinely different class
of gap from everything above: every other model went from "real code, no
live caller" to "real code, live caller, honestly disclosed inputs" by
writing plumbing against data this project already extracts somewhere.
SOTP needs a segment-level breakdown (which subsidiaries a holding
company owns, at what ownership %, unlisted or listed, with what
EBITDA/multiple) that no ingestion source in this project produces at
all — not a confirmation-workflow gap like Gordon-growth DDM's dividends
were, an actual missing data source, needing either segment-reporting
extraction from annual-report notes (well beyond the extractor's
verified total/subtotal-level scope, PARAMETERS.md #9) or a maintained
group-structure register this project has never had. See
`app.domain.sotp`'s own module docstring for the full picture; wiring it
for real, rather than hand-entering one company's segment data as a
demo (which would misrepresent a single hand-typed example as live
coverage), is separate follow-on work, tracked in ROADMAP.md.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.asset_based_valuation import HardBookResult, compute_hard_book
from app.domain.cost_of_equity_view import cost_of_equity_for
from app.domain.dcf import DCFAssumptions, DCFResult, compute_fcff, dcf_equity_value
from app.domain.wacc import WACCResult, compute_cost_of_debt, compute_wacc
from app.domain.dividend_residual_income import (
    GordonGrowthResult,
    ResidualIncomeResult,
    compute_residual_income,
    gordon_growth_value,
)
from app.domain.liquidity import percentile_rank
from app.domain.liquidity_view import liquidity_percentile_for, universe_amihud_ratios
from app.domain.macro_engine_view import RegimeView, regime_for
from app.domain.market_cap_view import latest_shares_issued_all_classes
from app.domain.national_projects_view import confirmed_base_case_revenue_growth_adjustment_for
from app.domain.margin_of_safety import MarginOfSafetyResult, compute_margin_of_safety
from app.domain.point_in_time import fundamentals_as_of
from app.domain.price_ladder import PriceLadderResult, compute_price_ladder
from app.domain.provenance import can_enter_valuation
from app.domain.ratios import LineItem, compute_all
from app.domain.relative_valuation import (
    JustifiedMultipleResult,
    JustifiedVsTradingComparison,
    TradingMultiples,
    compare_to_justified,
    justified_price_to_book,
    justified_price_to_earnings,
    justified_price_to_sales,
)
from app.domain.sanity import SanityCheckResult, SanityContext, run_sanity_checks
from app.domain.market_cap_view import published_market_cap_for
from app.domain.triangulation import TriangulationResult, ValuationAnchor, triangulate
from app.domain.ttm import annualised_flow, trailing_twelve_months
from app.domain.valuation_router import RoutingDecision, route_valuation
from app.models.corporate_actions import CorporateAction
from app.models.enums import CorporateActionType


#: How far back `_confirmable_line_items` may reach for a line the anchor
#: period doesn't carry. Three years: long enough to cover a company that
#: reports a given line only in its annual filing (so the newest interim
#: legitimately lacks it) plus a missed year, short enough that a balance
#: sheet old enough to describe a materially different company is never
#: silently paired with today's price. Every fallback is disclosed
#: regardless of age — this bound is the point past which disclosure stops
#: being enough.
_LINE_FALLBACK_MAX_AGE_DAYS = 1095


def _confirmable_line_items(
    db: Session, ticker: str, as_of: dt.date
) -> tuple[dt.date | None, dict[str, LineItem], tuple[str, ...]]:
    """The latest point-in-time-visible line items, restricted to tiers
    `can_enter_valuation` allows (§8). Returns
    `(period_end, items, excluded_lines)` — `excluded_lines` names any
    statement line that exists for the anchor period but was held back
    because it is still AI-assisted/unconfirmed, so a caller can say why a
    figure is missing rather than just that it is.

    PER-LINE, NOT PER-PERIOD (29 Aug 2026). This used to return ONLY the
    lines confirmed for the single latest period, and drop everything else.
    Real filings are not uniform: a company's newest confirmed filing is
    often an interim carrying a balance sheet but no income statement, or
    the reverse. Measured across a 60-ticker sample, 30 tickers had no
    `net_income` and 24 had no `total_equity` in their latest period WHILE
    OLDER CONFIRMED PERIODS HELD BOTH — and since ROE needs both, the whole
    valuation collapsed to "no anchors at all" for 216 of 290 companies.

    So a line missing from the anchor period now falls back to the most
    recent EARLIER period that has it confirmed, within
    `_LINE_FALLBACK_MAX_AGE_DAYS`. Nothing is estimated: every value is a
    real confirmed figure the company itself reported, and §6's
    point-in-time gate still applies to all of them (`fundamentals_as_of`
    has already filtered to what was public on `as_of`). The cost is that
    lines can come from different dates, so each one that does carries a
    `basis_note` naming its own period, which `_gather_inputs` surfaces as
    a warning — a fair value built partly on an older balance sheet must
    say so rather than read as a single coherent snapshot.
    """
    rows = fundamentals_as_of(db, ticker, as_of)
    if not rows:
        return None, {}, ()

    latest_period = max(r.period_end for r in rows)
    items: dict[str, LineItem] = {}
    excluded: set[str] = set()
    net_income_period_type: str | None = None
    for row in rows:
        if row.period_end != latest_period:
            continue
        if not can_enter_valuation(row.provenance_tier):
            excluded.add(row.statement_line)
            continue
        if row.statement_line not in items:
            items[row.statement_line] = LineItem(value=row.value, provenance=row.provenance_tier)
            if row.statement_line == "net_income":
                net_income_period_type = row.period_type

    # Fill anything the anchor period doesn't carry from the most recent
    # earlier confirmed period that does.
    oldest_allowed = latest_period - dt.timedelta(days=_LINE_FALLBACK_MAX_AGE_DAYS)
    earlier = sorted(
        (
            r for r in rows
            if r.period_end < latest_period
            and r.period_end >= oldest_allowed
            and can_enter_valuation(r.provenance_tier)
        ),
        key=lambda r: r.period_end,
        reverse=True,
    )
    for row in earlier:
        if row.statement_line in items:
            continue
        items[row.statement_line] = LineItem(
            value=row.value,
            provenance=row.provenance_tier,
            basis_note=(
                f"{row.statement_line} is from the confirmed period ending "
                f"{row.period_end} — the latest period ({latest_period}) has no confirmed "
                f"value for this line. A real reported figure, but from an earlier date."
            ),
        )
        if row.statement_line == "net_income":
            net_income_period_type = row.period_type
        excluded.discard(row.statement_line)

    # A REAL P0 fix (18 Aug 2026) — see `app.domain.ttm`'s own module
    # docstring for the full finding: `net_income` for a "quarterly"
    # period is CUMULATIVE SINCE THE FISCAL YEAR START in this system's
    # own real CSE filings, not a standalone quarter. Using it directly
    # understated COMB.N0000's real ROE by roughly half (9.73% instead
    # of the correct 17.92%), which alone was the entire reason
    # residual income and justified P/B put a real, liquid, well-run
    # bank in the "Exit" zone. Replaced here with the real trailing-
    # twelve-month figure — or removed entirely (never left as the raw,
    # misleading cumulative value) when TTM annualisation isn't yet
    # possible for this ticker.
    if "net_income" in items and net_income_period_type is not None:
        # `annualised_flow` = TTM when it can be built, otherwise the most
        # recent confirmed ANNUAL row (already twelve months as reported —
        # nothing scaled or estimated). See its own docstring for the
        # measured reason the fallback exists: TTM alone dropped net_income
        # for 200 of 283 tickers, because the archive backfill gave most
        # companies a deep ANNUAL history against a sparse quarterly one,
        # leaving no prior-year quarterly comparator to annualise against.
        annualised = annualised_flow(
            db, ticker, "net_income", as_of,
            current_period_end=latest_period, current_period_type=net_income_period_type,
            current_value=items["net_income"].value,
        )
        if annualised is not None:
            note = None
            if annualised.basis == "latest_annual":
                note = (
                    f"net_income taken from the confirmed ANNUAL period ending "
                    f"{annualised.period_end} — a real twelve-month reported figure, used "
                    f"because no prior-year quarterly comparator exists to build a "
                    f"trailing-twelve-month figure around {latest_period}. Earnings are "
                    f"therefore as of {annualised.period_end} while the balance sheet is "
                    f"as of {latest_period}."
                )
            items["net_income"] = LineItem(
                value=annualised.value,
                provenance=items["net_income"].provenance,
                basis_note=note,
            )
        else:
            # Deliberately NOT added to `excluded` — that set's own
            # downstream warning says "still AI-assisted/unconfirmed",
            # which would be false here (this line IS confirmed; it's
            # the ANNUALISATION that's missing a component). Removing it
            # from `items` is enough: every ROE-dependent ratio/anchor
            # already names "net_income" as a missing required input on
            # its own terms via `app.domain.ratios`' existing
            # missing-input reporting.
            del items["net_income"]

    return latest_period, items, tuple(sorted(excluded))


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
    total_equity: Decimal | None
    """Confirmed `total_equity` for `period_end` — carried alongside
    `book_value_per_share` (rather than making a caller re-derive it via
    `book_value_per_share x shares_issued`, which would silently produce
    a different number when `shares_issued` is `None`) specifically for
    TASK 0.1's `app.domain.sanity.SanityContext.equity`."""

    total_assets: Decimal | None
    """Confirmed `total_assets` for the SAME `period_end` as `total_
    equity` — see `SanityContext.total_assets`'s own docstring for why
    both must come from one single period. `None` whenever `total_assets`
    wasn't extracted for this company yet (real and common — see
    `app.domain.sanity`'s own docstring for `units_consistent` simply
    being skipped, not failed, in that case)."""

    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def _gather_inputs(
    db: Session,
    ticker: str,
    as_of: dt.date,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> LiveValuationInputs:
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

    # Disclose a derived basis (see LineItem.basis_note) — a fair value
    # built on last year's earnings against this quarter's book value must
    # say so, not read as if both came from the same date.
    for item in items.values():
        if item.basis_note:
            warnings.append(item.basis_note)

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

    ke_result = cost_of_equity_for(
        db, ticker, as_of, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if ke_result.ke is None:
        warnings.append(f"Cost of equity not computable: {ke_result.note}")

    growth_rate = _steady_state_growth(ke_result.risk_free_rate)

    book_value_per_share = None
    total_equity_item = items.get("total_equity")
    total_assets_item = items.get("total_assets")
    shares = latest_shares_issued_all_classes(db, ticker, as_of)
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
        total_equity=total_equity_item.value if total_equity_item is not None else None,
        total_assets=total_assets_item.value if total_assets_item is not None else None,
        excluded_unconfirmed_lines=excluded,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class JustifiedPBView:
    inputs: LiveValuationInputs
    result: JustifiedMultipleResult | None
    fair_value_per_share: Decimal | None


def justified_price_to_book_for(
    db: Session,
    ticker: str,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> JustifiedPBView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )

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


def residual_income_for(
    db: Session,
    ticker: str,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> ResidualIncomeView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )

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
    db: Session, ticker: str, current_price: Decimal | None, as_of: dt.date | None = None,
    *, regime: str | None = None, universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
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

    ke_result = cost_of_equity_for(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    shares = latest_shares_issued_all_classes(db, ticker, stamp)

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


def gordon_growth_ddm_for(
    db: Session,
    ticker: str,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> DDMView:
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

    ke_result = cost_of_equity_for(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
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
    assumptions: DCFAssumptions | None = None
    """The exact §18.2 base-case `DCFAssumptions` this view built and fed
    to `dcf_equity_value` — `None` whenever `result` is `None` (nothing
    was built). Carried here, rather than only inside `result`, so
    `app.domain.scenarios_view` can build real Bear/Base/Bull variants of
    THIS SAME assumption set (§23: "Base = assumptions as derived in
    §18.2") without re-deriving every ratio and growth rate a second
    time — a second derivation could drift from this one and produce a
    "base" scenario that silently disagrees with the DCF anchor already
    shown elsewhere on the same company file."""


def dcf_for(
    db: Session, ticker: str, current_price: Decimal | None, as_of: dt.date | None = None,
    *, regime: str | None = None, universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
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

    wacc_view = wacc_for(
        db, ticker, current_price, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if wacc_view.result is None or wacc_view.result.wacc is None:
        missing.append(
            "WACC (" + (wacc_view.result.note if wacc_view.result else "not computable") + ")"
        )

    ke_result = cost_of_equity_for(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    if ke_result.risk_free_rate is None:
        missing.append("risk_free_rate (needed to cap terminal/stage-2 growth)")

    shares = latest_shares_issued_all_classes(db, ticker, stamp)
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
    # abs(), same reasoning as capex above and app.domain.wacc.compute_
    # cost_of_debt's own docstring: a debt BALANCE can never legitimately
    # be negative, but the same company can print this line parenthesised
    # in one filing type and not another (verified live, 27 Aug 2026:
    # LVEF.N0000's real FY2025 annual report prints its debt maturity
    # split parenthesised while its own quarterly filing prints the
    # identical figure unparenthesised). Without this, a negative reading
    # here would INCREASE `equity_value` below (subtracting a negative
    # `total_debt` from enterprise value), the same overstate-the-
    # dangerous-direction consequence the capex sign-flip guard exists for.
    debt = abs(required["total_interest_bearing_debt"].value)

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

    # §18.2's own words: Y1/Y2 revenue growth is "Trailing 3-year CAGR,
    # adjusted by sector macro sensitivity (§33) and any confirmed
    # project in the register (§34)." The §33 half of that sentence
    # isn't applied here — `app.domain.sector_sensitivity`'s real,
    # estimated coefficients aren't yet threaded into this function, a
    # separate, named gap — but the §34 half is real: whichever confirmed,
    # base-case-eligible projects in the register name this ticker's
    # revenue as an affected line, summed into one adjustment.
    project_adjustment, contributing_impacts = confirmed_base_case_revenue_growth_adjustment_for(
        db, ticker, stamp
    )
    if project_adjustment is not None:
        revenue_growth_y1 = revenue_growth_y1 + project_adjustment
        revenue_growth_y2 = revenue_growth_y2 + project_adjustment
        warnings.append(
            f"Y1/Y2 growth further adjusted by {project_adjustment:+.4f} from "
            f"{len(contributing_impacts)} confirmed §34 national-project-register "
            "impact(s) naming this ticker's revenue (§18.2: 'adjusted by... any "
            "confirmed project in the register')."
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
    return DCFView(period_end, result, result.value_per_share, excluded, tuple(warnings), assumptions)


@dataclass(frozen=True)
class HardBookView:
    period_end: dt.date | None
    result: HardBookResult | None
    excluded_unconfirmed_lines: tuple[str, ...]
    warnings: tuple[str, ...]


def hard_book_for(db: Session, ticker: str, as_of: dt.date | None = None) -> HardBookView:
    """§22 rule 1: hard book value = reported book value − revaluation
    reserves — "necessary for plantations, property and hotels, and
    dangerous, because reported book value in these sectors is inflated
    by property revaluation." `total_equity` has been live-extractable
    since Phase 1; `revaluation_reserves` is new (17 Aug), verified
    against real filings deliberately sought out in the sectors §22
    names, not reused from J.F. Packaging/Swadeshi — see `CANONICAL_
    LABELS`' own comment for the full picture: Asian Hotels and
    Properties PLC prints a combined "Other components of equity" line
    (revaluation-dominated per its own Note 23 breakdown, a real, usable
    proxy but not an exact figure — see `CANONICAL_LABELS`' own comment
    for the verified real page/values, re-checked end-to-end 17 Aug
    against its actual currently-public FY2023/24 filing); Kelani Valley
    Plantations PLC genuinely has NO such
    line at all (99-year government leases, not freehold — nothing to
    revalue, a real zero, not a gap); Galadari Hotels (Lanka) PLC prints
    a pure standalone figure but its filing's 2-column layout isn't yet
    extractable through this pipeline for an unrelated, pre-existing
    reason.

    WHY A MISSING `revaluation_reserves` LINE DEFAULTS TO ZERO, AND WHY
    THAT DEFAULT IS FLAGGED EVERY TIME RATHER THAN TRUSTED SILENTLY.
    Zero is the CORRECT figure for a company with genuinely no
    revaluation reserve — Kelani Valley Plantations proves this is a
    real, common case, not just a convenient placeholder. But zero is
    ALSO what a company gets when it has a real reserve this system
    simply hasn't matched yet (a wording variant not yet added, or a
    filing shape — like Galadari's — this pipeline can't parse at all).
    Treating "confirmed zero" and "not yet extracted" identically means
    a missing line can silently OVERSTATE hard book for the second case
    (hard book should be lower once a real reserve is subtracted) — the
    same dangerous-direction problem `app.domain.wacc`'s missing-cost-
    of-debt rule and `dcf_for`'s missing-`minority_interest`/`pension_
    deficit` warnings already name elsewhere in this module. So this
    function always computes a result when `total_equity` exists (never
    silently withholds one over an absent reserve line, since absence is
    usually the true, correct case), but ALWAYS appends a warning
    naming the ambiguity when no `revaluation_reserves` line was found,
    rather than only warning when one WAS found — the asymmetry a
    caller needs to know about is "this could be an unmatched real
    reserve," not "a reserve was matched."

    Deliberately kept informational only, like `wacc`/`current_period_
    fcff`/`gordon_growth_ddm` — NOT one of `valuation_summary_for`'s
    triangulation anchors — even though §24's own weight table gives
    asset-based methods real weight for property/plantation/hotel
    archetypes (`app.domain.triangulation.TRIANGULATION_WEIGHTS`'s
    `"property"` row: 0.55 asset_sotp weight). The reason is coverage,
    not the arithmetic: `revaluation_reserves` has been verified nonzero
    on exactly one real filing so far (AHPL), and even that one is a
    combined proxy figure, not a pure revaluation number — promoting
    this to an anchor on that little real-world coverage would be
    exactly the "confident, precise, entirely fictional number" §15
    warns the whole valuation engine exists to prevent. Ready to become
    a real anchor for property/plantation/hotel archetypes once more of
    the sector has been verified, the same trajectory `current_period_
    fcff`/`wacc` followed before `dcf_for` was ready to consume them.
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
        return HardBookView(period_end, None, excluded, tuple(warnings))

    equity_item = items.get("total_equity")
    if equity_item is None:
        warnings.append("total_equity not available from confirmed fundamentals.")
        return HardBookView(period_end, None, excluded, tuple(warnings))

    reval_item = items.get("revaluation_reserves")
    if reval_item is None:
        warnings.append(
            "No revaluation_reserves line found for this company as of this period — "
            "treated as zero. This is the CORRECT figure for a company with genuinely "
            "no revaluation reserve (verified real for at least one company checked, "
            "Kelani Valley Plantations PLC), but could OVERSTATE hard book if this "
            "company actually carries a reserve under wording this extractor hasn't "
            "matched yet, or on a filing shape it can't parse at all (both real, "
            "separately-documented cases — see this function's own docstring)."
        )

    shares = latest_shares_issued_all_classes(db, ticker, stamp)
    if shares is None:
        warnings.append("shares_issued not available (no FloatData row on or before this date).")

    result = compute_hard_book(
        reported_book_value=equity_item.value,
        revaluation_reserves=reval_item.value if reval_item else Decimal(0),
        diluted_shares_outstanding=Decimal(shares) if shares else None,
    )
    return HardBookView(period_end, result, excluded, tuple(warnings))


@dataclass(frozen=True)
class RelativeValuationView:
    """§20.2's justified P/E and justified P/S — the two sub-multiples of
    relative valuation beyond justified P/B (which already runs, above,
    as its own dedicated view/anchor) that this system can honestly
    compute live. Both reuse `payout_ratio` derived from the SAME
    trailing-twelve-month confirmed dividend sum `gordon_growth_ddm_for`
    already built (`_trailing_dividend_per_share`) — this is real,
    genuinely confirmed `CorporateAction` data as of 23 Aug 2026 (a bulk
    corroborated-confirm pass gave this system its first confirmed
    dividend rows anywhere), not the "real but empty" state that function
    started in.

    JUSTIFIED EV/EBIT IS DELIBERATELY NOT COMPUTED HERE. §20.2's fourth
    multiple needs ROIC, which `app.domain.ratios.NOT_YET_COMPUTABLE`
    already lists as unavailable system-wide (needs NOPAT, total debt,
    cash — none extracted anywhere in this project). `justified_ev_to_
    ebit` itself is real, tested code (`app.domain.relative_valuation`)
    that already returns a correctly-reasoned `None` when handed
    `roic=None` — but calling it with a fabricated ROIC just to produce a
    non-`None` number would be exactly the "confident, precise, entirely
    fictional number" §15 exists to prevent. This is the one honestly
    remaining sub-multiple gap inside relative valuation, narrower than
    "relative valuation has zero live caller" (it does not, as of this
    view) — `trading.ev_to_ebit` is likewise left `None` for the same
    reason (no live EV figure either, since cash isn't extracted).
    """

    inputs: LiveValuationInputs
    period_end: dt.date | None
    eps: Decimal | None
    sales_per_share: Decimal | None
    net_margin: Decimal | None
    payout_ratio: Decimal | None
    trailing_dividend_per_share: Decimal | None
    justified_pe: JustifiedMultipleResult | None
    justified_ps: JustifiedMultipleResult | None
    fair_value_pe: Decimal | None
    fair_value_ps: Decimal | None
    trading: TradingMultiples
    pe_vs_trading: JustifiedVsTradingComparison | None
    ps_vs_trading: JustifiedVsTradingComparison | None
    pb_vs_trading: JustifiedVsTradingComparison | None
    warnings: tuple[str, ...]


def relative_valuation_for(
    db: Session,
    ticker: str,
    current_price: Decimal | None,
    as_of: dt.date | None = None,
    *,
    regime: str | None = None,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
) -> RelativeValuationView:
    stamp = as_of or dt.date.today()
    inputs = _gather_inputs(
        db, ticker, stamp, regime=regime,
        universe_liquidity_ratios=universe_liquidity_ratios,
        universe_liquidity_percentiles=universe_liquidity_percentiles,
    )
    warnings: list[str] = []

    period_end, items, _excluded = _confirmable_line_items(db, ticker, stamp)
    shares = inputs.shares_issued

    net_income_item = items.get("net_income")
    revenue_item = items.get("revenue")

    eps = net_income_item.value / Decimal(shares) if net_income_item is not None and shares else None
    sales_per_share = revenue_item.value / Decimal(shares) if revenue_item is not None and shares else None

    net_margin = None
    if items:
        margin_result = next((r for r in compute_all(items) if r.key == "net_margin"), None)
        if margin_result is not None and margin_result.computable:
            net_margin = margin_result.value
        else:
            warnings.append(
                "net_margin not computable from confirmed fundamentals"
                + (f" ({margin_result.note})" if margin_result and margin_result.note else ".")
            )

    dividends = _confirmed_dividends_as_of(db, ticker, stamp)
    trailing_dps, _dividend_count = _trailing_dividend_per_share(dividends, stamp)

    payout_ratio = None
    if trailing_dps is None:
        warnings.append(
            "payout_ratio not available — no confirmed DIVIDEND_CASH corporate action falls "
            "within the trailing twelve months of this date (same trailing-dividend source "
            "gordon_growth_ddm_for uses for its own D0; see that function's own docstring)."
        )
    elif eps is None:
        warnings.append("payout_ratio not available — EPS not computable (net_income or shares_issued missing).")
    elif eps <= 0:
        warnings.append("payout_ratio undefined — trailing EPS is not positive (loss-making period).")
    else:
        payout_ratio = trailing_dps / eps

    # THE PAYOUT THE MULTIPLE USES IS THE STEADY-STATE ONE, NOT THE
    # TRAILING ACTUAL — a real inconsistency found 29 Aug 2026, the moment
    # justified P/E first ran against live data and disagreed with
    # justified P/B by 3.4x on COMB.N0000 (239.05 vs 70.66).
    #
    # `inputs.growth_rate` is the STEADY-STATE terminal growth (§18.2's
    # policy figure, capped below Rf — see `_steady_state_growth`). A
    # company growing forever at `g` must, by the Gordon identity, be
    # retaining exactly `g / ROE` of its earnings, so its steady-state
    # payout is `1 - g/ROE`. Feeding today's ACTUAL payout into a formula
    # whose `g` is the terminal one describes a company that retains 80%
    # of its earnings and still only grows 5% — value-destroying by
    # construction — which is why COMB's multiple collapsed to 1.79x.
    #
    # This is not a departure from §20.2, it is the same reinvestment
    # consistency §20.2's OWN EV/EBIT formula already spells out:
    # `(1 - tax) x (1 - g / ROIC) / (WACC - g)`. `1 - g/ROIC` there is
    # exactly `1 - g/ROE` here, one line up the capital structure.
    #
    # The trailing actual payout is still computed and still REPORTED
    # (`payout_ratio` below) — it is real information about what the
    # company currently distributes, and `gordon_growth_ddm_for` rightly
    # uses the actual dividend. It just is not the right number to pair
    # with a terminal growth rate.
    # The confirmed-dividend gate above still applies: these multiples are
    # only offered for a company that demonstrably distributes, which is
    # the pre-existing design decision and is not what was broken here.
    # What changes is only WHICH payout the formula uses.
    steady_state_payout = None
    if payout_ratio is not None and inputs.roe is not None and inputs.roe > 0:
        implied = Decimal(1) - (inputs.growth_rate / inputs.roe)
        if implied > 0:
            steady_state_payout = implied
        else:
            warnings.append(
                f"justified P/E and P/S not computed — this company's ROE ({inputs.roe:.2%}) is at "
                f"or below the steady-state growth rate ({inputs.growth_rate:.2%}), so it cannot "
                "sustain that growth from retained earnings at all and the Gordon-family "
                "multiples have no meaningful value."
            )
    elif payout_ratio is not None and inputs.roe is None:
        warnings.append("justified P/E and P/S not computed — ROE unavailable, so the "
                        "steady-state payout consistent with the growth rate cannot be derived.")

    justified_pe = None
    fair_value_pe = None
    if steady_state_payout is not None and inputs.cost_of_equity is not None:
        justified_pe = justified_price_to_earnings(
            steady_state_payout, inputs.growth_rate, inputs.cost_of_equity
        )
        if justified_pe.value is not None and eps is not None:
            fair_value_pe = justified_pe.value * eps

    if fair_value_pe is not None:
        # NOT AN INDEPENDENT ANCHOR — and this must be said, because a
        # small dispersion between it and justified P/B looks exactly like
        # two models corroborating each other when it is one model counted
        # twice.
        #
        # Proven algebraically and confirmed live on every company checked
        # (COMB/HNB/RIL all return a ratio of exactly 1.05000 against a
        # (1+g) of 1.05000): with the steady-state payout `1 - g/ROE`,
        #     JPE_fv = (1 - g/ROE)(1+g)/(Ke-g) x EPS
        # and EPS = ROE x BVPS exactly, so
        #     JPE_fv = (ROE-g)(1+g)/(Ke-g) x BVPS = JPB_fv x (1+g).
        # Justified P/E and justified P/B are the same Gordon model on
        # different denominators, differing only by the trailing-vs-leading
        # factor. Residual income under this system's flat-ROE baseline
        # collapses to the same thing again.
        #
        # Genuine triangulation therefore needs a STRUCTURALLY different
        # model — §18's FCFF DCF (cash flows, not book or earnings),
        # §22's asset/NAV, or §20.1's cross-sectional peer multiples — not
        # another member of the Gordon family.
        warnings.append(
            "justified P/E is NOT independent of justified P/B — with the steady-state payout "
            "they are the same Gordon model on different denominators, and their fair values "
            "differ by exactly (1 + g). A small dispersion between them is arithmetic, not "
            "corroboration."
        )

    justified_ps = None
    fair_value_ps = None
    if steady_state_payout is not None and net_margin is not None and inputs.cost_of_equity is not None:
        justified_ps = justified_price_to_sales(
            net_margin, steady_state_payout, inputs.growth_rate, inputs.cost_of_equity
        )
        if justified_ps.value is not None and sales_per_share is not None:
            fair_value_ps = justified_ps.value * sales_per_share

    warnings.append(
        "justified EV/EBIT not computed — needs ROIC, which app.domain.ratios."
        "NOT_YET_COMPUTABLE already lists as unavailable system-wide (needs NOPAT, total "
        "debt, cash, none of which are extracted anywhere in this project yet)."
    )

    trading_pe = current_price / eps if current_price is not None and eps is not None and eps > 0 else None
    trading_pb = (
        current_price / inputs.book_value_per_share
        if current_price is not None
        and inputs.book_value_per_share is not None
        and inputs.book_value_per_share > 0
        else None
    )
    trading_ps = (
        current_price / sales_per_share
        if current_price is not None and sales_per_share is not None and sales_per_share > 0
        else None
    )
    trading = TradingMultiples(
        price_to_earnings=trading_pe, price_to_book=trading_pb, ev_to_ebit=None, price_to_sales=trading_ps,
    )

    pe_vs_trading = compare_to_justified(justified_pe, trading_pe) if justified_pe is not None else None
    ps_vs_trading = compare_to_justified(justified_ps, trading_ps) if justified_ps is not None else None
    pb_vs_trading = None
    if inputs.roe is not None and inputs.cost_of_equity is not None:
        jpb_result = justified_price_to_book(inputs.roe, inputs.growth_rate, inputs.cost_of_equity)
        pb_vs_trading = compare_to_justified(jpb_result, trading_pb)

    return RelativeValuationView(
        inputs=inputs,
        period_end=period_end,
        eps=eps,
        sales_per_share=sales_per_share,
        net_margin=net_margin,
        payout_ratio=payout_ratio,
        trailing_dividend_per_share=trailing_dps,
        justified_pe=justified_pe,
        justified_ps=justified_ps,
        fair_value_pe=fair_value_pe,
        fair_value_ps=fair_value_ps,
        trading=trading,
        pe_vs_trading=pe_vs_trading,
        ps_vs_trading=ps_vs_trading,
        pb_vs_trading=pb_vs_trading,
        warnings=tuple(warnings),
    )


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

    hard_book: HardBookView
    """Informational only, same status as `wacc`/`current_period_fcff`/
    `gordon_growth_ddm` — see `hard_book_for`'s own docstring for why:
    real, tested, live-wireable code, but `revaluation_reserves` has
    verified real-world coverage on only one filing so far, not enough
    to promote to a §24 triangulation anchor yet even though §22/§24
    would weight it heavily for a property/plantation/hotel archetype
    once it is."""

    relative_valuation: RelativeValuationView
    """§20.2's justified P/E and justified P/S — see `relative_valuation_
    for`'s own docstring. Both are genuine "relative" triangulation
    anchors below when computable (same category as justified P/B, which
    is why all three average into ONE relative-category bucket in
    `triangulation.category_averages` rather than being weighted
    separately — see `app.domain.triangulation.triangulate`'s own
    by-category averaging)."""

    regime: RegimeView
    """§29-33's regime read — market-wide, not company-specific, shown
    here so a caller can see exactly what fed `margin_of_safety.regime_
    pct` above (§31: "the regime output is not advisory... mechanically
    widens every margin of safety"). The Ke/discount-rate-raising and
    gross-exposure-capping consequences §31 also names are NOT wired
    anywhere in this codebase yet — see `app.domain.regime_
    classification`'s own module docstring for the honestly-named
    remainder of §29-33's method chain."""

    triangulation: TriangulationResult
    margin_of_safety: MarginOfSafetyResult
    sanity: SanityCheckResult | None
    """TASK 0.1's plausibility gate (`app.domain.sanity`), run against
    `triangulation.blended_fair_value_per_share` — `None` only when there
    was no blended fair value to even check (the gate has nothing to
    gate on). When `sanity.blocked` is `True`, `price_ladder` below is
    `None` even though a blended fair value exists — see `price_ladder`'s
    own docstring for why that's a THIRD distinct reason a ladder can be
    absent, alongside "no anchors at all" and "fair value not positive"."""

    price_ladder: PriceLadderResult | None
    """`None` for one of three distinct, named reasons: no triangulated
    fair value exists yet (`sanity` is also `None` in that case); a fair
    value exists but isn't positive (`compute_price_ladder`'s own
    guard); or a fair value exists, is positive, but FAILED TASK 0.1's
    plausibility gate (`sanity.blocked is True`) — never silently
    conflated with the other two, since the third case has a specific,
    actionable reason (`sanity.block_reasons`) the first two don't."""

    note: str


def valuation_summary_for(
    db: Session, ticker: str, archetype: str | None, current_price: Decimal | None,
    as_of: dt.date | None = None,
    *,
    universe_liquidity_ratios: dict[str, Decimal] | None = None,
    universe_liquidity_percentiles: dict[str, Decimal] | None = None,
    regime_view: RegimeView | None = None,
) -> CompanyValuationSummary:
    """The full, real, end-to-end Phase 3 pipeline for one company: route
    → the two live-wireable anchors → triangulate → margin of safety →
    price ladder. Every stage is honest about what it could and couldn't
    compute — this function does not paper over a gap by skipping a
    stage silently; `note` on the result, and each sub-result's own
    fields, say what ran and what didn't.

    `universe_liquidity_ratios` and `regime_view` — the caller's job to
    supply when it already has one, not this function's to fetch
    unconditionally. Both left `None` (computed once here, exactly as
    before) for a single-company call; a caller valuing several companies
    against the same `as_of` — `app.domain.portfolio_valuation_view.
    value_portfolio` and `app.domain.opportunity_ranking_view.
    opportunity_ranking_for` are the real ones — computes `app.domain.
    liquidity_view.universe_amihud_ratios` and `app.domain.macro_engine_
    view.regime_for` ONCE EACH and passes both to every call instead,
    since both are market-wide and identical across every one of them.
    See `app.domain.liquidity_view.liquidity_percentile_for`'s own
    docstring for the real, profiled cost skipping this avoids: 89
    seconds for 9 positions on a real portfolio, from the liquidity scan
    alone. `universe_liquidity_percentiles` closes a SECOND, independent
    half of that same cost class, found live later (20 Aug 2026):
    `universe_ratios` being shared stopped the O(n) universe SCAN from
    repeating, but `percentile_rank(universe_ratios)` — an O(n²) full
    universe RE-RANKING — still ran fresh on every one of the ~6 calls
    into `cost_of_equity_for` this function's own anchors make per
    ticker, identical result every time. Left `None` here falls back to
    computing it once per call to THIS function (still far cheaper than
    the ~6x-per-call cost before this fix) — but a caller valuing many
    tickers against the same universe, exactly like `universe_liquidity_
    ratios` above, should compute it ONCE up front and share it the same
    way; `opportunity_ranking_for`/`value_portfolio` both do.

    `regime_view` is the same class of cost for the same reason —
    `fit_markov_regime_read`'s MLE fit is expensive and was, until this
    parameter existed, being recomputed once per ticker in both
    `opportunity_ranking_for` (every confirmed ticker in the whole
    universe — genuinely unusable once that set grew past a couple of
    dozen names) and `value_portfolio` (once per held position) for an
    identical, market-wide, `as_of`-only answer each time."""
    stamp = as_of or dt.date.today()
    universe_ratios = (
        universe_liquidity_ratios
        if universe_liquidity_ratios is not None
        else universe_amihud_ratios(db, stamp)
    )
    # See this function's own docstring on `universe_liquidity_percentiles`
    # for why this is computed here rather than left for each of the ~6
    # calls below to redo independently (the O(n²) half of the liquidity-
    # scan cost the `universe_ratios` sharing above didn't close).
    universe_percentiles = (
        universe_liquidity_percentiles
        if universe_liquidity_percentiles is not None
        else percentile_rank(universe_ratios)
    )
    routing = route_valuation(archetype)

    # Computed ONCE, here, and threaded through every call below that
    # needs Ke — not recomputed per anchor. §29-33's regime read is
    # market-wide, not company-specific, and a real statistical fit
    # (`app.domain.regime_classification.fit_markov_regime_read`)
    # expensive enough that recomputing it independently inside each of
    # justified_price_to_book_for/residual_income_for/wacc_for/dcf_for/
    # gordon_growth_ddm_for (five calls, several of which call `cost_of_
    # equity_for` internally too) would multiply that cost several-fold
    # for an identical answer each time. Computing it once per company-
    # valuation call rather than once per market snapshot across a whole
    # batch is still a real, known inefficiency — a shared-cache layer
    # across companies is genuine separate work, not a correctness
    # issue — but it is no longer N-times-per-call the way it would be
    # without this.
    regime_view = regime_view if regime_view is not None else regime_for(db, stamp)
    regime_label = regime_view.result.label if regime_view.result is not None else None

    jpb = justified_price_to_book_for(
        db, ticker, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )
    ri = residual_income_for(
        db, ticker, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )
    fcff_view = current_period_fcff_for(db, ticker, stamp)
    wacc_view = wacc_for(
        db, ticker, current_price, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )
    dcf_view = dcf_for(
        db, ticker, current_price, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )
    ddm_view = gordon_growth_ddm_for(
        db, ticker, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )
    hard_book_view = hard_book_for(db, ticker, stamp)
    rel_view = relative_valuation_for(
        db, ticker, current_price, stamp, regime=regime_label,
        universe_liquidity_ratios=universe_ratios, universe_liquidity_percentiles=universe_percentiles,
    )

    anchors: list[ValuationAnchor] = []
    if jpb.fair_value_per_share is not None:
        anchors.append(ValuationAnchor("Justified P/B", "relative", jpb.fair_value_per_share))
    if ri.result is not None and ri.result.value_per_share is not None:
        anchors.append(ValuationAnchor("Residual income", "intrinsic", ri.result.value_per_share))
    if dcf_view.fair_value_per_share is not None:
        anchors.append(ValuationAnchor("FCFF DCF", "intrinsic", dcf_view.fair_value_per_share))
    if rel_view.fair_value_pe is not None:
        anchors.append(ValuationAnchor("Justified P/E", "relative", rel_view.fair_value_pe))
    if rel_view.fair_value_ps is not None:
        anchors.append(ValuationAnchor("Justified P/S", "relative", rel_view.fair_value_ps))

    triangulation = triangulate(routing, tuple(anchors))

    mos = compute_margin_of_safety(
        dispersion_pct=triangulation.dispersion_pct,
        liquidity_percentile=liquidity_percentile_for(
            db, ticker, stamp, universe_ratios=universe_ratios, universe_percentiles=universe_percentiles
        ),  # real Amihud percentile, live 18 Aug 2026
        regime=regime_label,  # §29-33's regime read, live — see regime_for's own docstring
        integrity_score=None,  # no continuous integrity score exists anywhere in this system, by design — see margin_of_safety.py
        data_completeness_pct=None,  # not computed at the per-company level anywhere yet
    )

    sanity_result: SanityCheckResult | None = None
    ladder = None
    if triangulation.blended_fair_value_per_share is not None:
        # A non-positive blended fair value is ALREADY fully, honestly
        # handled by `compute_price_ladder`'s own pre-existing guard
        # (zone=None, "fair_value must be positive" warning) — that is a
        # distinct, older mechanism from TASK 0.1's gate below, and the
        # two are not layered: `SANITY_RULES` (`fv_within_5x_price` in
        # particular) is written for "is this POSITIVE number plausible
        # relative to price," and running it against a negative fair
        # value would short-circuit BEFORE `compute_price_ladder` ever
        # ran, silently discarding that older, already-correct warning
        # (a real regression caught by this project's own existing
        # `test_a_negative_blended_fair_value_is_excluded_with_a_named_
        # reason_not_a_fake_zone` when this was first wired one way).
        ladder = compute_price_ladder(
            triangulation.blended_fair_value_per_share, mos.total_pct, current_price
        )

        if triangulation.blended_fair_value_per_share > 0 and current_price is not None:
            # TASK 0.1: the plausibility gate. Only reached once a
            # positive ladder was actually built — this is the case the
            # gate exists for (COMB's real bug was a POSITIVE, "confident
            # wrong answer", not a negative one). jpb/ri share the
            # identical `_gather_inputs` call for this ticker/as_of, so
            # `jpb.inputs` already carries every input the gate needs; no
            # extra fundamentals query is issued here beyond the one new
            # independent lookup (`published_market_cap_for`) the gate
            # specifically requires.
            published_mcap = published_market_cap_for(db, ticker, stamp)
            sanity_ctx = SanityContext(
                price=current_price,
                bvps=jpb.inputs.book_value_per_share,
                roe=jpb.inputs.roe,
                mcap=published_mcap,
                shares=jpb.inputs.shares_issued,
                equity=jpb.inputs.total_equity,
                total_assets=jpb.inputs.total_assets,
            )
            sanity_result = run_sanity_checks(triangulation.blended_fair_value_per_share, sanity_ctx)
            if sanity_result.blocked:
                # Withhold the ladder itself — but `sanity_result` (and
                # therefore `sanity.block_reasons`) is still returned on
                # the summary, which is where callers now get the reason
                # from (see `note` below and every call site's own
                # comment on why `price_ladder is None` no longer means
                # only one thing).
                ladder = None

    note = (
        f"{len(anchors)} of §18-26's real triangulation anchors were live-computable for "
        f"this company ({', '.join(a.method for a in anchors) or 'none'}) — any missing "
        "ones above need data this system doesn't have for THIS company yet (a confirmed "
        "dividend, enough revenue history, etc. — see each anchor's own view for the "
        "specific reason). Justified P/B, Residual income, FCFF DCF, Justified P/E and "
        "Justified P/S are all genuine, live-wireable anchors as of 23 Aug 2026; SOTP is "
        "the one §18-26 model still blocked on a real missing data source rather than a "
        "wiring gap (see this module's own docstring)."
    )
    if sanity_result is not None and sanity_result.blocked:
        note += (
            " TASK 0.1's plausibility gate withheld the fair value and price ladder "
            f"despite a blended figure existing — failed: {', '.join(sanity_result.blocked_by)}."
        )

    return CompanyValuationSummary(
        ticker=ticker, as_of=stamp, current_price=current_price, routing=routing, justified_pb=jpb,
        residual_income=ri, current_period_fcff=fcff_view, wacc=wacc_view, dcf=dcf_view,
        gordon_growth_ddm=ddm_view, hard_book=hard_book_view, relative_valuation=rel_view,
        regime=regime_view, triangulation=triangulation, margin_of_safety=mos, sanity=sanity_result,
        price_ladder=ladder, note=note,
    )
