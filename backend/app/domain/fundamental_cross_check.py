"""Mathematical cross-check for the fundamentals confirm queue (§8).

The confirm queue holds tens of thousands of AI-assisted rows. A human
reviewing every one is itself an error source — the 19 Aug 2026 bulk
"sample-checked" confirm pass that caused OI-1/OI-4 is the proof. This
module scores each row against several INDEPENDENT signals and only ever
calls a row confirmable when at least two of them agree AND no veto
fires. Anything short of that stays in the queue with a computed
confidence band, so the residual human review is triaged, not blind.

Pure functions over caller-supplied facts — no I/O, no DB, no network,
same discipline as `app.domain.financial_statement_parsing` (whose
`check_accounting_identities`, `_identity_diffs`, `_magnitude_
implausible_keys`, `_COMPONENT_SUBTOTAL_CEILINGS` and rounding tolerance
this module reuses rather than re-deriving). `app.domain.fundamental_
cross_check_view` gathers the facts from the database and drives it.

THE SIGNALS (each independent of the others):
  S1  identity web     — every accounting identity computable for this
                         filing balances within the module's own Rs 1,000
                         rounding tolerance; a line participating in one
                         earns S1.
  S2  re-extraction     — today's parser, re-run against the source PDF,
                         reproduces the stored value exactly. REQUIRED for
                         auto-confirm: it is the direct guard against a
                         value that is stale from before a parser fix
                         (the whole OI-1/OI-4 failure mode).
  S3  cross-source      — an independently-sourced row (different
                         source_url) for the same (ticker, period_end,
                         line) carries the same value: a later filing's
                         comparative column, a re-file, an agreeing
                         restatement.
  S5  annual/quarterly  — (annual filings only) a flow line's annual
                         figure equals the sum of its four quarters within
                         1%.
  S6  dual-listing      — the <T>.N0000 / <T>.X0000 counterpart reports
                         the identical consolidated figure.

THE VETOES (any one blocks auto-confirm regardless of signal count):
  V1  magnitude         — `check_magnitude_plausibility` flags the row.
  V2  ceiling           — the value breaches its component-subtotal
                         ceiling (`_COMPONENT_SUBTOTAL_CEILINGS`).
  V3  discontinuity     — a >20x / <1/20x jump vs the immediately-prior
                         period with no other corroboration — the
                         uniform-offset class (JAT Holdings' real
                         net_income) that every identity passes by
                         construction.
  V4  filing marker     — a row on this filing carries an
                         "EXTRACTION FAILED ARITHMETIC CHECK" snippet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.financial_statement_parsing import (
    _COMPONENT_CEILING_TOLERANCE,
    _COMPONENT_SUBTOTAL_CEILINGS,
    _IDENTITY_ROUNDING_TOLERANCE,
    _identity_diffs,
    _magnitude_implausible_keys,
)

#: Lines measured over a reporting period (income statement + cash flow).
#: An annual figure for one of these should reconcile with the sum of its
#: four quarters; a balance-sheet (stock) line should not.
FLOW_LINES: frozenset[str] = frozenset(
    {
        "revenue",
        "cost_of_sales",
        "gross_profit",
        "operating_profit",
        "operating_profit_before_working_capital_changes",
        "profit_before_tax",
        "income_tax_expense",
        "net_income",
        "total_comprehensive_income",
        "interest_expense",
        "depreciation_expense",
        "amortisation_expense",
        "depreciation_and_amortisation",
        "capital_expenditure",
        "cash_flow_from_operations",
        "cash_generated_from_operations",
        "net_cash_from_financing_activities",
        "net_cash_from_investing_activities",
        "net_increase_in_cash",
    }
)

#: Which canonical lines each `_identity_diffs` relationship ties together.
#: Declared here alongside — `_identity_diffs`' own docstring already asks
#: callers to keep membership in sync by hand rather than parse its names.
_IDENTITY_MEMBERS: dict[str, tuple[str, ...]] = {
    "assets = equity + liabilities": ("total_assets", "total_equity", "total_liabilities"),
    "assets = equity and liabilities": ("total_assets", "total_equity_and_liabilities"),
    "assets = current + non-current": (
        "total_assets",
        "total_current_assets",
        "total_non_current_assets",
    ),
    "liabilities = current + non-current": (
        "total_liabilities",
        "total_current_liabilities",
        "total_non_current_liabilities",
    ),
    "revenue - cost of sales = gross profit": ("revenue", "cost_of_sales", "gross_profit"),
    "pre-tax profit - tax = net income": (
        "profit_before_tax",
        "income_tax_expense",
        "net_income",
    ),
    "CFO + investing + financing = net change in cash": (
        "cash_flow_from_operations",
        "net_cash_from_investing_activities",
        "net_cash_from_financing_activities",
        "net_increase_in_cash",
    ),
}

#: How close an annual flow figure must sit to the sum of its four
#: quarters — real filings round, and a quarter is sometimes a 13-week
#: period against a 52/53-week year.
ANNUAL_QUARTERLY_TOLERANCE_PCT = Decimal("0.01")

#: A period-over-period jump beyond this ratio (either direction), with no
#: other corroborating signal, is a veto. Wide on purpose: a real line can
#: legitimately double or halve; a corrupted read is out by 100x-1000x.
CONTINUITY_MAX_RATIO = Decimal(20)

SIGNAL_IDS: tuple[str, ...] = (
    "S1_identities",
    "S2_reextract",
    "S3_cross_source",
    "S5_annual_quarterly",
    "S6_dual_listing",
)
VETO_IDS: tuple[str, ...] = ("V1_magnitude", "V2_ceiling", "V3_discontinuity", "V4_filing_marker")

MIN_SIGNALS_DEFAULT = 2


#: External (genuinely independent) corroboration — a different filing, a
#: different fiscal aggregation, or the dual listing. S1 (identity web)
#: and S2 (re-extraction) both derive from THE SAME extraction of the
#: SAME filing, so on their own they cannot catch a uniform-offset misread
#: that keeps its one identity balancing (JAT Holdings' real net_income:
#: pbt AND net_income both carried the same +200m offset). At least one of
#: these, OR a line sitting inside two or more independently-passing
#: identities, is required for auto-confirm.
_EXTERNAL_SIGNALS = frozenset({"S3_cross_source", "S5_annual_quarterly", "S6_dual_listing"})


@dataclass(frozen=True)
class RowVerdict:
    ticker: str
    statement_line: str
    period_end: str  # ISO date
    period_type: str
    value: Decimal
    signals: frozenset[str]
    vetoes: frozenset[str]
    identity_count: int = 0  # how many independently-passing identities this line sits in
    min_signals: int = MIN_SIGNALS_DEFAULT

    @property
    def auto_confirm(self) -> bool:
        """Auto-confirm needs, together:
        - S2 (re-extraction) — a value is never machine-confirmed without
          today's parser reproducing it;
        - at least `min_signals` signals total, no veto;
        - a genuinely independent cross-check: either an external signal
          (S3/S5/S6) or membership in >=2 independently-passing identities
          — so a single-identity line (net_income, revenue, ...) can't
          auto-confirm on identity+re-extraction alone, both of which read
          the same extraction of the same filing.
        """
        if "S2_reextract" not in self.signals:
            return False
        if len(self.signals) < self.min_signals or self.vetoes:
            return False
        return self.identity_count >= 2 or bool(_EXTERNAL_SIGNALS & self.signals)

    @property
    def confidence(self) -> str:
        if self.auto_confirm:
            return "auto-confirm"
        if self.vetoes:
            return "needs-review"
        if len(self.signals) >= 2:
            return "high"
        if self.signals:
            return "medium"
        return "needs-review"

    def describe(self) -> str:
        parts = "+".join(sorted(self.signals)) or "none"
        if self.vetoes:
            parts += " / veto:" + ",".join(sorted(self.vetoes))
        return parts


@dataclass
class FilingFacts:
    """Everything `evaluate_filing` needs about one (ticker, period_end,
    period_type), pre-gathered by the view layer."""

    ticker: str
    period_end: str
    period_type: str
    #: best value per canonical line for THIS filing (lowest version)
    values: dict[str, Decimal]
    #: {line: [values from OTHER source_urls for the same (ticker,
    #: period_end)]} — any period_type, any tier
    cross_source_values: dict[str, list[Decimal]] = field(default_factory=dict)
    #: {line: value} from the dual-listing counterpart for the same
    #: (period_end, period_type)
    dual_listing_values: dict[str, Decimal] = field(default_factory=dict)
    #: annual filings only: {line: [quarterly values]} for the four
    #: quarters ending within this period_end's fiscal year
    quarterly_values: dict[str, list[Decimal]] = field(default_factory=dict)
    #: how many distinct quarterly periods were found (need 4 for S5)
    quarterly_period_count: int = 0
    #: {line: value} for the immediately-prior period of the same ticker
    prior_period_values: dict[str, Decimal] = field(default_factory=dict)
    #: today's-parser re-extraction of this filing — None if not run or
    #: the download/parse failed
    reextracted_values: dict[str, Decimal] | None = None
    #: a row on this filing carries an extraction-failure marker in its
    #: stored snippet (from whatever extraction wrote it — possibly stale)
    has_filing_failure_marker: bool = False
    #: whether TODAY's re-extraction of this filing passes
    #: `check_extraction_quality` — None when not re-extracted. A stale
    #: stored failure marker is disregarded once this is True.
    reextracted_quality_ok: bool | None = None


def _close(a: Decimal, b: Decimal, tol: Decimal = _IDENTITY_ROUNDING_TOLERANCE) -> bool:
    return abs(a - b) <= tol


def _within_pct(a: Decimal, b: Decimal, pct: Decimal) -> bool:
    """|a - b| within `pct` of the larger magnitude (or within the flat
    rounding tolerance, for figures near zero)."""
    scale = max(abs(a), abs(b))
    return abs(a - b) <= max(scale * pct, _IDENTITY_ROUNDING_TOLERANCE)


def _passing_identity_counts(values: dict[str, Decimal]) -> dict[str, int]:
    """{statement_line: how many computable-and-passing identities it sits
    in}. 0 means either no identity covers the line, or one does but it
    doesn't balance."""
    counts: dict[str, int] = {}
    for name, diff in _identity_diffs(values).items():
        if diff <= _IDENTITY_ROUNDING_TOLERANCE:
            for member in _IDENTITY_MEMBERS.get(name, ()):
                counts[member] = counts.get(member, 0) + 1
    return counts


def evaluate_filing(facts: FilingFacts, *, min_signals: int = MIN_SIGNALS_DEFAULT) -> list[RowVerdict]:
    """One `RowVerdict` per line in `facts.values`."""
    identity_counts = _passing_identity_counts(facts.values)
    magnitude_flagged = _magnitude_implausible_keys(facts.values)
    verdicts: list[RowVerdict] = []

    for line, value in facts.values.items():
        signals: set[str] = set()
        vetoes: set[str] = set()

        # --- signals ---
        if identity_counts.get(line, 0) >= 1:
            signals.add("S1_identities")

        if facts.reextracted_values is not None and line in facts.reextracted_values:
            if _close(facts.reextracted_values[line], value):
                signals.add("S2_reextract")

        for other in facts.cross_source_values.get(line, ()):
            if _close(other, value):
                signals.add("S3_cross_source")
                break

        if (
            facts.period_type == "annual"
            and line in FLOW_LINES
            and facts.quarterly_period_count >= 4
            and line in facts.quarterly_values
            and len(facts.quarterly_values[line]) >= 4
        ):
            q_sum = sum(facts.quarterly_values[line][:4], Decimal(0))
            if _within_pct(q_sum, value, ANNUAL_QUARTERLY_TOLERANCE_PCT):
                signals.add("S5_annual_quarterly")

        if line in facts.dual_listing_values and _close(facts.dual_listing_values[line], value):
            signals.add("S6_dual_listing")

        # --- vetoes ---
        if line in magnitude_flagged:
            vetoes.add("V1_magnitude")

        ceiling = _component_ceiling(line, facts.values)
        if ceiling is not None and abs(value) > ceiling * _COMPONENT_CEILING_TOLERANCE:
            vetoes.add("V2_ceiling")

        prior = facts.prior_period_values.get(line)
        if (
            prior is not None
            and prior != 0
            and value != 0
            and not {"S3_cross_source", "S5_annual_quarterly", "S6_dual_listing"} & signals
        ):
            ratio = abs(value) / abs(prior)
            if ratio > CONTINUITY_MAX_RATIO or ratio < (Decimal(1) / CONTINUITY_MAX_RATIO):
                vetoes.add("V3_discontinuity")

        # A stored "EXTRACTION FAILED ARITHMETIC CHECK" marker vetoes the
        # filing — UNLESS today's re-extraction of it passes its quality
        # checks, in which case the marker is stale (written by a
        # pre-parser-fix extraction) and disregarded.
        if facts.has_filing_failure_marker and facts.reextracted_quality_ok is not True:
            vetoes.add("V4_filing_marker")

        verdicts.append(
            RowVerdict(
                ticker=facts.ticker,
                statement_line=line,
                period_end=facts.period_end,
                period_type=facts.period_type,
                value=value,
                signals=frozenset(signals),
                vetoes=frozenset(vetoes),
                identity_count=identity_counts.get(line, 0),
                min_signals=min_signals,
            )
        )
    return verdicts


def _component_ceiling(line: str, values: dict[str, Decimal]) -> Decimal | None:
    for sibling in _COMPONENT_SUBTOTAL_CEILINGS.get(line, ()):
        if sibling in values and values[sibling] != 0:
            return abs(values[sibling])
    return None
