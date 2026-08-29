"""
Phase 2 — the fundamental engine's ratio layer (Master Spec §12).

Pure functions over a dict of statement line items. No I/O, no ORM, so
every formula is directly testable against a real filing.

THE GOVERNING CONSTRAINT: this computes only what the available line
items actually support, and says so loudly about the rest. §12 lists far
more than is implemented here — ROIC, Piotroski F-Score, Beneish
M-Score, net debt/EBITDA — and every one of those needs line items the
current PDF extractor doesn't pull (debt broken out from total
liabilities, D&A, working-capital components as a stock rather than a
flow). Rather than approximate them from what's to hand, each
unavailable ratio is declared with the exact inputs it is missing, so the
UI can say "cannot compute, needs X" instead of showing a number that
looks precise and is quietly wrong. That is Design Law 3 (§4): "Missing
is displayed as missing... Silence is a lie in this system." Cash
conversion IS implemented below, once `cash_flow_from_operations` became
extractable. §27's Altman Z"-Score is ALSO now real (see the
`altman_z_double_prime` definition below) — the emerging-market variant
(Altman, Hartzell & Peck, 1995), not the original 1968 model, and
deliberately so: the original's X4 term needs MARKET value of equity
(this system's own `NOT_YET_COMPUTABLE` entry named that as the
blocker), while Z" uses BOOK value of equity instead, built by Altman
specifically for non-manufacturers and emerging markets — exactly this
system's real context, and it removes the live-price dependency
entirely. `retained_earnings` was the one genuinely missing input
(added to `app.domain.financial_statement_parsing.CANONICAL_LABELS`,
measured against 62+18 real filings via `scripts/measure_unmatched_
labels.py` before being added, this project's own standing rule, never
guessed).

A specific trap worth naming: total liabilities is NOT debt. Debt/equity
computed on total liabilities sweeps in trade payables and deferred tax
and overstates leverage, sometimes by a lot. The ratio below is therefore
named `liabilities_to_equity` rather than `debt_to_equity`, because
calling it the latter would invite a reader to compare it against a
conventional D/E screen and reach a wrong conclusion.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal, DivisionByZero, InvalidOperation

from app.domain.provenance import weakest
from app.models.enums import ProvenanceTier


class Unit(str):
    """Display unit, so the UI never has to guess whether 0.11 is 11% or
    0.11x (§5.1 requires ratios to be shown 'with the unit named')."""


PERCENT = Unit("percent")
TIMES = Unit("times")


@dataclasses.dataclass(frozen=True)
class LineItem:
    """One statement figure plus the provenance it carries, so a derived
    ratio can inherit the weakest provenance of its inputs (§8)."""

    value: Decimal
    provenance: ProvenanceTier
    #: Optional note about how this figure was DERIVED, when it isn't the
    #: filing's own raw line — currently set only when a flow line had to
    #: be annualised from a period other than the current one (see
    #: `app.domain.ttm.annualised_flow`). Carried here rather than returned
    #: alongside so `_confirmable_line_items`' six existing call sites keep
    #: their signature; the one caller that reports to a user
    #: (`valuation_view._gather_inputs`) reads it and discloses it.
    basis_note: str | None = None
    #: The real period this figure's own value was reported for — `None`
    #: only for a caller that never populates it (this field predates
    #: `app.domain.ratios`'s own single-period `compute_all` pipeline,
    #: which selects one period up front and has no cross-period mixing
    #: to track). `app.domain.valuation_view._confirmable_line_items`
    #: DOES populate this on every item, including ones pulled from an
    #: earlier period via its own per-line fallback — see that module's
    #: `_same_period` helper for why this exists: a MARGIN built by
    #: dividing two flow figures from two DIFFERENT real periods (a full
    #: year's EBIT against one quarter's revenue, say) is not a real
    #: margin at all, and this is the field that lets a caller refuse to
    #: build one from mismatched dates rather than silently doing the
    #: division anyway.
    period_end: dt.date | None = None


@dataclasses.dataclass(frozen=True)
class RatioResult:
    key: str
    label: str
    formula: str
    unit: Unit
    value: Decimal | None
    provenance: ProvenanceTier | None
    inputs_used: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    note: str | None = None

    @property
    def computable(self) -> bool:
        return self.value is not None


@dataclasses.dataclass(frozen=True)
class RatioDefinition:
    key: str
    label: str
    formula: str
    unit: Unit
    required: tuple[str, ...]
    fn: Callable[[Mapping[str, Decimal]], Decimal | None]
    #: Why the result is None despite all inputs being present — e.g. a
    #: denominator that is zero or economically meaningless.
    guard_note: str | None = None


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    try:
        return numerator / denominator
    except (DivisionByZero, InvalidOperation):  # pragma: no cover - defensive
        return None


def _div_positive_denominator(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """For ratios where a non-positive denominator makes the result
    meaningless rather than merely negative.

    Return on equity with negative equity is the classic case: a company
    with -100 equity and -50 profit yields a cheerful +50% ROE. That
    number is arithmetically correct and economically nonsense, and a
    screen sorting on it would rank the most distressed company top.
    §22 anticipates exactly this territory ("liquidation value as an
    absolute floor for distressed names"), so the honest answer is "not
    meaningful", not a figure.
    """
    if denominator <= 0:
        return None
    return _safe_div(numerator, denominator)


DEFINITIONS: tuple[RatioDefinition, ...] = (
    # --- Profitability (§12) -------------------------------------------
    RatioDefinition(
        key="return_on_equity",
        label="Return on equity",
        formula="net income ÷ total equity",
        unit=PERCENT,
        required=("net_income", "total_equity"),
        fn=lambda v: _div_positive_denominator(v["net_income"], v["total_equity"]),
        guard_note="Not meaningful when total equity is zero or negative.",
    ),
    RatioDefinition(
        key="return_on_assets",
        label="Return on assets",
        formula="net income ÷ total assets",
        unit=PERCENT,
        required=("net_income", "total_assets"),
        fn=lambda v: _div_positive_denominator(v["net_income"], v["total_assets"]),
        guard_note="Not meaningful when total assets is zero or negative.",
    ),
    RatioDefinition(
        key="gross_margin",
        label="Gross margin",
        formula="gross profit ÷ revenue",
        unit=PERCENT,
        required=("gross_profit", "revenue"),
        fn=lambda v: _div_positive_denominator(v["gross_profit"], v["revenue"]),
        guard_note="Not meaningful without positive revenue.",
    ),
    RatioDefinition(
        key="operating_margin",
        label="Operating margin",
        formula="operating profit ÷ revenue",
        unit=PERCENT,
        required=("operating_profit", "revenue"),
        fn=lambda v: _div_positive_denominator(v["operating_profit"], v["revenue"]),
        guard_note="Not meaningful without positive revenue.",
    ),
    RatioDefinition(
        key="net_margin",
        label="Net margin",
        formula="net income ÷ revenue",
        unit=PERCENT,
        required=("net_income", "revenue"),
        fn=lambda v: _div_positive_denominator(v["net_income"], v["revenue"]),
        guard_note="Not meaningful without positive revenue.",
    ),
    RatioDefinition(
        # §12 lists this explicitly: "Gross profitability (gross profit ÷
        # total assets) — Novy-Marx; robust where earnings are noisy".
        key="gross_profitability",
        label="Gross profitability (Novy-Marx)",
        formula="gross profit ÷ total assets",
        unit=PERCENT,
        required=("gross_profit", "total_assets"),
        fn=lambda v: _div_positive_denominator(v["gross_profit"], v["total_assets"]),
        guard_note="Not meaningful without positive total assets.",
    ),
    # --- Financial strength --------------------------------------------
    RatioDefinition(
        key="current_ratio",
        label="Current ratio",
        formula="total current assets ÷ total current liabilities",
        unit=TIMES,
        required=("total_current_assets", "total_current_liabilities"),
        fn=lambda v: _div_positive_denominator(
            v["total_current_assets"], v["total_current_liabilities"]
        ),
        guard_note="Not meaningful without positive current liabilities.",
    ),
    RatioDefinition(
        key="liabilities_to_equity",
        label="Liabilities to equity",
        formula="total liabilities ÷ total equity",
        unit=TIMES,
        required=("total_liabilities", "total_equity"),
        fn=lambda v: _div_positive_denominator(v["total_liabilities"], v["total_equity"]),
        # Deliberately NOT called debt/equity — see the module docstring.
        guard_note=(
            "Total liabilities, not debt — includes payables and deferred tax, so this "
            "reads higher than a conventional debt/equity ratio and is not comparable to one."
        ),
    ),
    RatioDefinition(
        key="equity_ratio",
        label="Equity ratio",
        formula="total equity ÷ total assets",
        unit=PERCENT,
        required=("total_equity", "total_assets"),
        fn=lambda v: _div_positive_denominator(v["total_equity"], v["total_assets"]),
        guard_note="Not meaningful without positive total assets.",
    ),
    # --- Tax -------------------------------------------------------------
    RatioDefinition(
        key="effective_tax_rate",
        label="Effective tax rate",
        formula="income tax expense ÷ profit before tax",
        unit=PERCENT,
        required=("income_tax_expense", "profit_before_tax"),
        # Tax expense is stored negative (it reduces profit); report the
        # rate as a positive percentage, which is how §18.2 uses it.
        fn=lambda v: _div_positive_denominator(
            abs(v["income_tax_expense"]), v["profit_before_tax"]
        ),
        guard_note="Not meaningful when the company made a pre-tax loss.",
    ),
    # --- Cash flow (§12) — the first three ratios wired since
    # `cash_flow_from_operations` became extractable (financial_statement_
    # parsing.py, verified against J.F. Packaging PLC's real FY2025/26
    # statement of cash flow). Capex, D&A's use in §18 FCFF, and the
    # remaining cash-flow-dependent ratios below (net debt/EBITDA,
    # interest coverage, Piotroski, Beneish) are still blocked — see
    # NOT_YET_COMPUTABLE — because they need line items beyond CFO alone
    # (total debt, interest expense, share count) that this extractor
    # still doesn't pull.
    RatioDefinition(
        key="cash_conversion",
        label="Cash conversion (CFO ÷ net income)",
        formula="cash flow from operations ÷ net income",
        unit=TIMES,
        required=("cash_flow_from_operations", "net_income"),
        fn=lambda v: _div_positive_denominator(v["cash_flow_from_operations"], v["net_income"]),
        guard_note="Not meaningful when the company made a net loss.",
    ),
    RatioDefinition(
        key="operating_cash_flow_margin",
        label="Operating cash flow margin",
        formula="cash flow from operations ÷ revenue",
        unit=PERCENT,
        required=("cash_flow_from_operations", "revenue"),
        fn=lambda v: _div_positive_denominator(v["cash_flow_from_operations"], v["revenue"]),
        guard_note="Not meaningful without positive revenue.",
    ),
    RatioDefinition(
        key="sloan_accrual_ratio",
        label="Sloan accrual ratio",
        formula="(net income − cash flow from operations) ÷ total assets",
        unit=PERCENT,
        required=("net_income", "cash_flow_from_operations", "total_assets"),
        # Sloan (1996): a large positive accrual ratio (earnings well
        # above cash generated) is the specific pattern associated with
        # lower earnings quality and weaker forward returns — this is a
        # signal ratio, not a profitability one, so it is NOT run through
        # _div_positive_denominator's "not meaningful if negative" guard;
        # a negative total_assets company has bigger problems this ratio
        # isn't trying to flag, but the arithmetic itself stays defined.
        fn=lambda v: _safe_div(v["net_income"] - v["cash_flow_from_operations"], v["total_assets"]),
        guard_note="Not meaningful when total assets is zero.",
    ),
    # --- Distress detection (§27) ---------------------------------------
    RatioDefinition(
        # Altman's EMERGING-MARKET Z"-Score (Altman, Hartzell & Peck,
        # 1995) — deliberately NOT the original 1968 Z, whose X4 term
        # needs MARKET value of equity (this module's own docstring
        # explains why book value is the right, and now computable,
        # choice for this system). `retained_earnings` was the one
        # genuinely missing input; measured against real filings before
        # being added (`app.domain.financial_statement_parsing.
        # CANONICAL_LABELS`'s own comment).
        #
        # Widely-cited bands, PROVISIONAL (see this project's own
        # "Provisional" marking convention, e.g. `app.domain.valuation_
        # view.MIN_PLAUSIBLE_JUSTIFIED_PB`): distress < 4.35, grey
        # 4.35-5.85, safe > 5.85. Not encoded here as a zone label —
        # `compute_ratio`'s shared `note` field is reserved for the
        # guard reason when a ratio ISN'T computable, not a dynamic
        # interpretation of a value that is — so the raw score is
        # returned and a caller applies the bands itself if it wants to.
        # Keyed "altman_z" (not "altman_z_double_prime") to match the key
        # this system's own frontend (`RatioCardGrid.tsx`'s `GROUP_BY_KEY`)
        # and the removed `NOT_YET_COMPUTABLE` entry both already used —
        # one stable identifier for "this system's Altman-Z implementation,
        # whichever variant," with the label naming the variant.
        key="altman_z",
        label='Altman Z"-Score (emerging market)',
        formula='6.56×WC/TA + 3.26×RE/TA + 6.72×EBIT/TA + 1.05×BVE/TL + 3.25',
        unit=TIMES,
        required=(
            "total_current_assets", "total_current_liabilities", "retained_earnings",
            "operating_profit", "total_assets", "total_equity", "total_liabilities",
        ),
        fn=lambda v: (
            Decimal("6.56") * (v["total_current_assets"] - v["total_current_liabilities"]) / v["total_assets"]
            + Decimal("3.26") * v["retained_earnings"] / v["total_assets"]
            + Decimal("6.72") * v["operating_profit"] / v["total_assets"]
            + Decimal("1.05") * v["total_equity"] / v["total_liabilities"]
            + Decimal("3.25")
        ) if v["total_assets"] > 0 and v["total_liabilities"] > 0 else None,
        guard_note="Not meaningful when total assets or total liabilities is zero or negative.",
    ),
)

DEFINITIONS_BY_KEY = {d.key: d for d in DEFINITIONS}


#: §12 ratios that are specified but NOT computable from the line items
#: the extractor currently pulls. Declared explicitly so the UI states
#: what is missing rather than silently omitting the metric.
NOT_YET_COMPUTABLE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("roic", "Return on invested capital", ("nopat", "total_debt", "cash")),
    ("roic_wacc_spread", "ROIC − WACC spread", ("roic", "wacc")),
    ("net_debt_to_ebitda", "Net debt ÷ EBITDA", ("total_debt", "cash", "ebitda")),
    ("interest_coverage", "Interest coverage", ("ebit", "interest_expense")),
    # cash_flow_from_operations is extractable now (financial_statement_
    # parsing.py) — Piotroski's remaining gap is total_debt and
    # shares_outstanding, not CFO.
    ("piotroski_f_score", "Piotroski F-Score", ("total_debt", "shares_outstanding")),
    # altman_z is REMOVED from this list — see the `altman_z` definition
    # in DEFINITIONS above: the emerging-market Z" variant this system
    # implements needs book value of equity, not market_cap, and is now
    # real and computable.
    ("beneish_m", "Beneish M-Score", ("receivables", "gross_ppe", "depreciation", "sga", "total_accruals")),
)


def compute_ratio(definition: RatioDefinition, line_items: Mapping[str, LineItem]) -> RatioResult:
    missing = tuple(k for k in definition.required if k not in line_items)
    if missing:
        return RatioResult(
            key=definition.key,
            label=definition.label,
            formula=definition.formula,
            unit=definition.unit,
            value=None,
            provenance=None,
            inputs_used=(),
            missing_inputs=missing,
            note=None,
        )

    values = {k: line_items[k].value for k in definition.required}
    result = definition.fn(values)

    return RatioResult(
        key=definition.key,
        label=definition.label,
        formula=definition.formula,
        unit=definition.unit,
        value=result,
        # §8: "A composite score inherits the weakest provenance among its
        # material inputs." A ratio is a Derived value, but it can be no
        # more trustworthy than the softest number feeding it.
        provenance=(
            weakest([line_items[k].provenance for k in definition.required])
            if result is not None
            else None
        ),
        inputs_used=definition.required if result is not None else (),
        missing_inputs=(),
        note=definition.guard_note if result is None else None,
    )


def compute_all(line_items: Mapping[str, LineItem]) -> list[RatioResult]:
    """Every defined ratio, computable or not. Callers that want only the
    usable ones filter on `.computable` — but the uncomputable entries
    carry the reason, and the UI is expected to show it."""
    return [compute_ratio(d, line_items) for d in DEFINITIONS]
