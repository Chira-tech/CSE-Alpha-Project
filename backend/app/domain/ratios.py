"""
Phase 2 — the fundamental engine's ratio layer (Master Spec §12).

Pure functions over a dict of statement line items. No I/O, no ORM, so
every formula is directly testable against a real filing.

THE GOVERNING CONSTRAINT: this computes only what the available line
items actually support, and says so loudly about the rest. §12 lists far
more than is implemented here — ROIC, cash conversion, Piotroski F-Score,
Altman Z", Beneish M-Score, net debt/EBITDA — and every one of those needs
line items the current PDF extractor doesn't pull (cash flow from
operations, debt broken out from total liabilities, D&A, working-capital
components). Rather than approximate them from what's to hand, each
unavailable ratio is declared with the exact inputs it is missing, so the
UI can say "cannot compute, needs X" instead of showing a number that
looks precise and is quietly wrong. That is Design Law 3 (§4): "Missing
is displayed as missing... Silence is a lie in this system."

A specific trap worth naming: total liabilities is NOT debt. Debt/equity
computed on total liabilities sweeps in trade payables and deferred tax
and overstates leverage, sometimes by a lot. The ratio below is therefore
named `liabilities_to_equity` rather than `debt_to_equity`, because
calling it the latter would invite a reader to compare it against a
conventional D/E screen and reach a wrong conclusion.
"""
from __future__ import annotations

import dataclasses
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
)

DEFINITIONS_BY_KEY = {d.key: d for d in DEFINITIONS}


#: §12 ratios that are specified but NOT computable from the line items
#: the extractor currently pulls. Declared explicitly so the UI states
#: what is missing rather than silently omitting the metric.
NOT_YET_COMPUTABLE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("roic", "Return on invested capital", ("nopat", "total_debt", "cash")),
    ("roic_wacc_spread", "ROIC − WACC spread", ("roic", "wacc")),
    ("cash_conversion", "Cash conversion (CFO ÷ net income)", ("cash_flow_from_operations",)),
    ("operating_cash_flow_margin", "Operating cash flow margin", ("cash_flow_from_operations",)),
    ("net_debt_to_ebitda", "Net debt ÷ EBITDA", ("total_debt", "cash", "ebitda")),
    ("interest_coverage", "Interest coverage", ("ebit", "interest_expense")),
    ("piotroski_f_score", "Piotroski F-Score", ("cash_flow_from_operations", "total_debt", "shares_outstanding")),
    ("altman_z", 'Altman Z"-Score', ("working_capital", "retained_earnings", "ebit", "market_cap")),
    ("beneish_m", "Beneish M-Score", ("receivables", "gross_ppe", "depreciation", "sga", "total_accruals")),
    ("sloan_accrual_ratio", "Sloan accrual ratio", ("cash_flow_from_operations",)),
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
