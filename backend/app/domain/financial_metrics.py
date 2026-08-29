"""
STEP 2 of the system-wide valuation upgrade — the canonical financial-data
layer (§24, and `financial_metrics_engine` in §32's module list).

§24 names one set of figures the whole system should read: an income
statement block (revenue through EPS), a balance-sheet block (cash
through tangible equity) and a cash-flow block (CFO, capex, FCF, FCFF,
FCFE and their margins). Before this module those lived nowhere — each
model re-derived what it needed from raw statement lines, so "EBIT" meant
whatever the calling site decided that day, and concepts §24 requires
(net debt, tangible equity, EBITDA, FCF) had no definition at all.

This is the layer everything above it reads. Deliberately PURE — a
mapping of statement lines in, a list of results out; no I/O, no ORM, no
security-specific branching (§32: "No security-specific business
logic") — so every formula is testable directly against a real filing.

It shares `LineItem`, `Unit` and the provenance rules with
`app.domain.ratios` rather than restating them: ratios.py answers "how
profitable, how levered, how cash-generative", this module answers "what
are the figures", and a ratio built on a metric must not disagree with
the metric.

THE GOVERNING CONSTRAINT, unchanged from ratios.py and §23: a metric
whose inputs are missing returns `value=None` and names exactly which
inputs are missing. It never falls back to a plausible-looking number.
Where a missing input IS treated as zero — an absent overdraft line, an
absent amortisation line — that is a real assumption and is recorded on
the result in `assumptions`, so a reader can see it rather than infer it.

Sign conventions follow ratios.py's existing precedent: tax, interest and
depreciation are cost MAGNITUDES and are taken through `abs()`, because
CSE filings are genuinely inconsistent about whether they print them
negative (as a deduction in the income statement) or positive (as an
add-back in the cash-flow statement). Measured on the live data:
`interest_expense` has a median of -0.05x |PBT| across non-financial
annual rows, i.e. both signs occur in the same column. Taking the
magnitude is the only reading that is correct under both conventions.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from decimal import Decimal

from app.domain.provenance import weakest
from app.domain.ratios import PERCENT, TIMES, LineItem, Unit, _safe_div
from app.models.enums import ProvenanceTier

#: Absolute money figures, as opposed to ratios.py's PERCENT/TIMES. The
#: UI needs to know not to render these as a percentage.
CURRENCY = Unit("lkr")


@dataclasses.dataclass(frozen=True)
class MetricResult:
    key: str
    label: str
    formula: str
    unit: Unit
    value: Decimal | None
    provenance: ProvenanceTier | None
    inputs_used: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    #: Stated assumptions that were applied to reach `value` — currently
    #: only ever "an optional input was absent and treated as zero".
    #: Non-empty means the figure is real but rests on something the
    #: filing did not say, and the UI is expected to show it.
    assumptions: tuple[str, ...] = ()
    note: str | None = None

    @property
    def computable(self) -> bool:
        return self.value is not None


@dataclasses.dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    formula: str
    unit: Unit
    #: Absent -> the metric is not computable at all.
    required: tuple[str, ...]
    fn: Callable[[Mapping[str, Decimal]], Decimal | None]
    #: Present -> used; absent -> `fn` sees the key missing and decides.
    #: Every optional key MUST have an entry in `OPTIONAL_ASSUMPTIONS` so
    #: its absence is disclosed rather than silently absorbed.
    optional: tuple[str, ...] = ()
    guard_note: str | None = None


#: What it means when an optional input is absent. Keyed by the input, so
#: the same wording is used everywhere that input is optional.
OPTIONAL_ASSUMPTIONS: dict[str, str] = {
    "bank_overdraft": "no bank overdraft line on this filing; treated as zero. "
                      "If the company has an unextracted overdraft, debt and net debt read low.",
    "amortisation_expense": "no amortisation line on this filing; treated as zero. "
                            "If the company amortises intangibles, D&A and EBITDA read low.",
    "depreciation_expense": "no separate depreciation line on this filing; treated as zero.",
    "intangible_assets": "no intangible assets line on this filing; treated as zero, "
                         "so tangible equity equals total equity.",
    "investment_property": "no investment property line on this filing; treated as zero.",
}


def _get(values: Mapping[str, Decimal], key: str) -> Decimal:
    """An optional input's value, or zero. Only ever called for keys
    listed in a definition's `optional`, so the zero is always disclosed
    through `OPTIONAL_ASSUMPTIONS`."""
    return values.get(key, Decimal(0))


def _d_and_a(values: Mapping[str, Decimal]) -> Decimal:
    """Depreciation and amortisation, from whichever shape the filing
    used. `financial_statement_parsing.DERIVED_SUMS` already combines the
    two separate lines into `depreciation_and_amortisation`, but ONLY
    when both are present — and most CSE filings print depreciation
    without a separate amortisation line, which is why that derived key
    exists for 10 tickers while `depreciation_expense` exists for 132.
    Falling back to the components here is what makes EBITDA computable
    for the other 122."""
    if "depreciation_and_amortisation" in values:
        return abs(values["depreciation_and_amortisation"])
    return abs(_get(values, "depreciation_expense")) + abs(_get(values, "amortisation_expense"))


def _effective_tax_rate(values: Mapping[str, Decimal]) -> Decimal | None:
    """Same definition as `ratios.effective_tax_rate`, including its
    `abs()` on the tax line and its "meaningless in a loss year" guard —
    restated here rather than imported so FCFF's dependency on it is
    visible in this module's own formulas."""
    pbt = values["profit_before_tax"]
    if pbt <= 0:
        return None
    return _safe_div(abs(values["income_tax_expense"]), pbt)


DEFINITIONS: tuple[MetricDefinition, ...] = (
    # ---- Income statement (§24) ---------------------------------------
    MetricDefinition(
        key="revenue", label="Revenue", formula="revenue", unit=CURRENCY,
        required=("revenue",), fn=lambda v: v["revenue"],
    ),
    MetricDefinition(
        key="gross_profit", label="Gross profit", formula="gross profit", unit=CURRENCY,
        required=("gross_profit",), fn=lambda v: v["gross_profit"],
    ),
    MetricDefinition(
        key="ebit", label="EBIT", formula="operating profit", unit=CURRENCY,
        required=("operating_profit",), fn=lambda v: v["operating_profit"],
    ),
    MetricDefinition(
        key="ebitda", label="EBITDA", formula="operating profit + depreciation & amortisation",
        unit=CURRENCY,
        required=("operating_profit",),
        optional=("depreciation_and_amortisation", "depreciation_expense", "amortisation_expense"),
        fn=lambda v: v["operating_profit"] + _d_and_a(v),
    ),
    MetricDefinition(
        key="ebit_margin", label="EBIT margin", formula="EBIT ÷ revenue", unit=PERCENT,
        required=("operating_profit", "revenue"),
        fn=lambda v: _safe_div(v["operating_profit"], v["revenue"]) if v["revenue"] > 0 else None,
        guard_note="Not meaningful without positive revenue.",
    ),
    MetricDefinition(
        key="ebitda_margin", label="EBITDA margin", formula="EBITDA ÷ revenue", unit=PERCENT,
        required=("operating_profit", "revenue"),
        optional=("depreciation_and_amortisation", "depreciation_expense", "amortisation_expense"),
        fn=lambda v: (
            _safe_div(v["operating_profit"] + _d_and_a(v), v["revenue"]) if v["revenue"] > 0 else None
        ),
        guard_note="Not meaningful without positive revenue.",
    ),
    MetricDefinition(
        key="interest_expense", label="Interest expense",
        formula="interest expense (magnitude)", unit=CURRENCY,
        required=("interest_expense",), fn=lambda v: abs(v["interest_expense"]),
    ),
    MetricDefinition(
        key="ebt", label="EBT (profit before tax)", formula="profit before tax", unit=CURRENCY,
        required=("profit_before_tax",), fn=lambda v: v["profit_before_tax"],
    ),
    MetricDefinition(
        key="tax", label="Income tax expense", formula="income tax expense (magnitude)",
        unit=CURRENCY,
        required=("income_tax_expense",), fn=lambda v: abs(v["income_tax_expense"]),
    ),
    MetricDefinition(
        key="net_income", label="Net income", formula="profit for the period", unit=CURRENCY,
        required=("net_income",), fn=lambda v: v["net_income"],
    ),
    # ---- Balance sheet (§24) -------------------------------------------
    MetricDefinition(
        key="cash", label="Cash and cash equivalents", formula="cash and cash equivalents",
        unit=CURRENCY,
        required=("cash_and_cash_equivalents",), fn=lambda v: v["cash_and_cash_equivalents"],
    ),
    MetricDefinition(
        key="receivables", label="Trade receivables", formula="trade and other receivables",
        unit=CURRENCY,
        required=("trade_receivables",), fn=lambda v: v["trade_receivables"],
    ),
    MetricDefinition(
        key="inventory", label="Inventory", formula="inventories", unit=CURRENCY,
        required=("inventories",), fn=lambda v: v["inventories"],
    ),
    MetricDefinition(
        key="ppe", label="Property, plant and equipment", formula="property, plant and equipment",
        unit=CURRENCY,
        required=("property_plant_and_equipment",), fn=lambda v: v["property_plant_and_equipment"],
    ),
    MetricDefinition(
        key="investment_property", label="Investment property", formula="investment property",
        unit=CURRENCY,
        required=("investment_property",), fn=lambda v: v["investment_property"],
    ),
    MetricDefinition(
        key="total_assets", label="Total assets", formula="total assets", unit=CURRENCY,
        required=("total_assets",), fn=lambda v: v["total_assets"],
    ),
    MetricDefinition(
        key="current_liabilities", label="Current liabilities", formula="total current liabilities",
        unit=CURRENCY,
        required=("total_current_liabilities",), fn=lambda v: v["total_current_liabilities"],
    ),
    MetricDefinition(
        key="total_liabilities", label="Total liabilities", formula="total liabilities",
        unit=CURRENCY,
        required=("total_liabilities",), fn=lambda v: v["total_liabilities"],
    ),
    # Interest-bearing borrowings PLUS the overdraft, which sits
    # separately in current liabilities on these filings and is genuinely
    # debt. NOT total liabilities — see ratios.py's own warning that
    # calling that "debt" overstates leverage by sweeping in payables.
    MetricDefinition(
        key="debt", label="Debt", formula="interest-bearing debt + bank overdraft",
        unit=CURRENCY,
        required=("total_interest_bearing_debt",),
        optional=("bank_overdraft",),
        fn=lambda v: v["total_interest_bearing_debt"] + abs(_get(v, "bank_overdraft")),
    ),
    MetricDefinition(
        key="net_debt", label="Net debt", formula="debt − cash", unit=CURRENCY,
        required=("total_interest_bearing_debt", "cash_and_cash_equivalents"),
        optional=("bank_overdraft",),
        fn=lambda v: (
            v["total_interest_bearing_debt"] + abs(_get(v, "bank_overdraft"))
            - v["cash_and_cash_equivalents"]
        ),
    ),
    MetricDefinition(
        key="equity", label="Total equity", formula="total equity", unit=CURRENCY,
        required=("total_equity",), fn=lambda v: v["total_equity"],
    ),
    MetricDefinition(
        key="tangible_equity", label="Tangible equity", formula="total equity − intangible assets",
        unit=CURRENCY,
        required=("total_equity",),
        optional=("intangible_assets",),
        fn=lambda v: v["total_equity"] - _get(v, "intangible_assets"),
    ),
    # ---- Cash flow (§24) ------------------------------------------------
    # CFO is the figure AFTER tax and interest paid — NOT
    # `cash_generated_from_operations`, which is the pre-tax, pre-interest
    # subtotal a few lines above it on the same statement. They are
    # different numbers and this module will not substitute one for the
    # other, even though the pre-tax subtotal is currently extracted for
    # far more companies (159 vs 3). Using it here would silently
    # overstate every cash-flow metric below.
    MetricDefinition(
        key="cfo", label="Cash flow from operations", formula="net cash from operating activities",
        unit=CURRENCY,
        required=("cash_flow_from_operations",), fn=lambda v: v["cash_flow_from_operations"],
    ),
    MetricDefinition(
        key="capex", label="Capital expenditure", formula="purchases of property, plant and equipment",
        unit=CURRENCY,
        required=("capital_expenditure",), fn=lambda v: abs(v["capital_expenditure"]),
    ),
    MetricDefinition(
        key="fcf", label="Free cash flow", formula="CFO − capex", unit=CURRENCY,
        required=("cash_flow_from_operations", "capital_expenditure"),
        fn=lambda v: v["cash_flow_from_operations"] - abs(v["capital_expenditure"]),
    ),
    MetricDefinition(
        key="fcff", label="FCFF",
        formula="EBIT×(1−effective tax rate) + D&A − capex − Δ net working capital",
        unit=CURRENCY,
        required=("operating_profit", "profit_before_tax", "income_tax_expense",
                  "capital_expenditure", "change_in_net_working_capital"),
        optional=("depreciation_and_amortisation", "depreciation_expense", "amortisation_expense"),
        fn=lambda v: (
            None if (rate := _effective_tax_rate(v)) is None
            else v["operating_profit"] * (Decimal(1) - rate)
            + _d_and_a(v) - abs(v["capital_expenditure"]) - v["change_in_net_working_capital"]
        ),
        guard_note="Effective tax rate is not meaningful in a pre-tax loss year.",
    ),
    MetricDefinition(
        key="cfo_to_net_income", label="CFO ÷ net income", formula="CFO ÷ net income", unit=TIMES,
        required=("cash_flow_from_operations", "net_income"),
        fn=lambda v: _safe_div(v["cash_flow_from_operations"], v["net_income"]) if v["net_income"] > 0 else None,
        guard_note="Not meaningful when the company made a net loss.",
    ),
    MetricDefinition(
        key="fcf_margin", label="FCF margin", formula="(CFO − capex) ÷ revenue", unit=PERCENT,
        required=("cash_flow_from_operations", "capital_expenditure", "revenue"),
        fn=lambda v: (
            _safe_div(v["cash_flow_from_operations"] - abs(v["capital_expenditure"]), v["revenue"])
            if v["revenue"] > 0 else None
        ),
        guard_note="Not meaningful without positive revenue.",
    ),
)

DEFINITIONS_BY_KEY = {d.key: d for d in DEFINITIONS}


#: §24 metrics that this layer deliberately does NOT compute, with the
#: exact reason. Declared rather than omitted, so the UI can say what is
#: missing instead of quietly showing a shorter list (§23, and ratios.py's
#: own NOT_YET_COMPUTABLE precedent).
NOT_YET_COMPUTABLE: tuple[tuple[str, str, str], ...] = (
    ("eps", "Earnings per share",
     "needs the share count, which is not a statement line — it comes from "
     "`market_cap_view.latest_shares_issued_all_classes`. Computing it here would "
     "make this module depend on market data and stop being pure."),
    ("fcfe", "FCFE",
     "needs net borrowing (debt drawn − debt repaid) for the period. The cash-flow "
     "statement's financing section is extracted for 9 tickers and its individual "
     "borrowing lines are not extracted at all, so FCFE would rest on an assumed "
     "zero net borrowing — which is exactly the fabricated number §23 forbids."),
)


def compute_metric(definition: MetricDefinition, line_items: Mapping[str, LineItem]) -> MetricResult:
    missing = tuple(k for k in definition.required if k not in line_items)
    if missing:
        return MetricResult(
            key=definition.key, label=definition.label, formula=definition.formula,
            unit=definition.unit, value=None, provenance=None,
            inputs_used=(), missing_inputs=missing,
        )

    present_optional = tuple(k for k in definition.optional if k in line_items)
    used = definition.required + present_optional
    values = {k: line_items[k].value for k in used}
    result = definition.fn(values)

    if result is None:
        return MetricResult(
            key=definition.key, label=definition.label, formula=definition.formula,
            unit=definition.unit, value=None, provenance=None,
            inputs_used=(), missing_inputs=(), note=definition.guard_note,
        )

    # Only disclose an assumption for an optional input that is BOTH
    # absent and actually consequential. `depreciation_expense` and
    # `amortisation_expense` are alternatives to the combined D&A line,
    # so their absence means nothing when the combined line is present.
    absent_optional = [k for k in definition.optional if k not in line_items]
    if "depreciation_and_amortisation" in line_items:
        absent_optional = [
            k for k in absent_optional
            if k not in ("depreciation_expense", "amortisation_expense")
        ]
    assumptions = tuple(
        OPTIONAL_ASSUMPTIONS[k] for k in absent_optional if k in OPTIONAL_ASSUMPTIONS
    )

    return MetricResult(
        key=definition.key, label=definition.label, formula=definition.formula,
        unit=definition.unit, value=result,
        # §8, same rule ratios.py applies: a derived figure inherits the
        # weakest provenance among the inputs that actually fed it.
        provenance=weakest([line_items[k].provenance for k in used]),
        inputs_used=used, missing_inputs=(), assumptions=assumptions,
    )


def compute_all(line_items: Mapping[str, LineItem]) -> list[MetricResult]:
    """Every §24 metric, computable or not. Callers wanting only usable
    figures filter on `.computable` — but the uncomputable entries carry
    their missing inputs, and the UI is expected to show them."""
    return [compute_metric(d, line_items) for d in DEFINITIONS]


#: Metrics §24 asks for as a period-over-period change. Keyed by the
#: metric whose growth is wanted.
GROWTH_METRICS: tuple[tuple[str, str], ...] = (
    ("revenue", "Revenue growth"),
    ("ebit", "EBIT growth"),
    ("net_income", "Net income growth"),
)


def compute_growth(
    current: Mapping[str, LineItem], prior: Mapping[str, LineItem]
) -> list[MetricResult]:
    """Period-over-period growth, which needs two periods and so cannot
    come from `compute_all`'s single-period signature.

    Growth off a non-positive base is not reported. A company going from
    -10 to +5 has no meaningful "percentage growth" — the arithmetic
    yields -150%, which reads as catastrophic deterioration and is the
    exact opposite of what happened. §26's turnaround detection is the
    right home for that transition, not a growth rate.
    """
    results: list[MetricResult] = []
    current_metrics = {m.key: m for m in compute_all(current)}
    prior_metrics = {m.key: m for m in compute_all(prior)}

    for key, label in GROWTH_METRICS:
        now, before = current_metrics.get(key), prior_metrics.get(key)
        definition = DEFINITIONS_BY_KEY[key]
        if now is None or before is None or now.value is None or before.value is None:
            results.append(MetricResult(
                key=f"{key}_growth", label=label, formula=f"{key} ÷ prior {key} − 1",
                unit=PERCENT, value=None, provenance=None, inputs_used=(),
                missing_inputs=tuple(sorted(set(
                    (now.missing_inputs if now else definition.required)
                    + (before.missing_inputs if before else definition.required)
                ))),
            ))
            continue
        if before.value <= 0:
            results.append(MetricResult(
                key=f"{key}_growth", label=label, formula=f"{key} ÷ prior {key} − 1",
                unit=PERCENT, value=None, provenance=None, inputs_used=(), missing_inputs=(),
                note="Not meaningful from a non-positive base period.",
            ))
            continue
        results.append(MetricResult(
            key=f"{key}_growth", label=label, formula=f"{key} ÷ prior {key} − 1",
            unit=PERCENT, value=_safe_div(now.value, before.value) - Decimal(1),
            provenance=weakest([p for p in (now.provenance, before.provenance) if p is not None]),
            inputs_used=(key,), missing_inputs=(),
        ))
    return results
