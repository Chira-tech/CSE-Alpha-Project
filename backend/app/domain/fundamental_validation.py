"""The data-integrity gate: run one filing's already-extracted values
through a battery of independent checks and return a plain pass / fail
per line.

The product owner's model (3 Sep 2026) is binary. A value that passes
every applicable check is available to the valuation engine; a value that
fails one goes to the fundamentals queue for review and is NOT used until
it is fixed. There is no status ladder and no confidence score.

Phase 1 (this module's first version) reuses the checks
`app.domain.financial_statement_parsing` already has:
  - `check_accounting_identities` — exact arithmetic relationships
    between statement lines (assets = equity + liabilities, and so on).
  - `check_magnitude_plausibility` — a line whose magnitude is a
    millionth or less of the filing's own largest value is a corrupted
    read (a dropped digit, a stray footnote number).

Phase 2 adds the year-over-year trend check, the cross-statement checks
(retained-earnings roll-forward, EPS reconcile, gross->operating) and the
unit / group-vs-standalone checks to the SAME `validate_filing` entry
point — a caller never needs to know which check caught a value.

Pure functions over caller-supplied values — no I/O, no DB, no network.
`app.domain.fundamental_validation_view` gathers the values from the
database and persists the verdicts.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.domain.financial_statement_parsing import (
    _IDENTITY_ROUNDING_TOLERANCE,
    _identity_diffs,
    _magnitude_implausible_keys,
)

#: Bump when the check battery changes so the nightly job re-sweeps every
#: row instead of trusting a verdict a weaker version produced.
VALIDATION_METHOD = "identity+magnitude:v1"

#: Which statement lines each `check_accounting_identities` relationship
#: involves. When an identity fails, the extraction is wrong SOMEWHERE in
#: this set but the check cannot say which line — so every one of these
#: lines the filing actually extracted is failed together, and a reviewer
#: resolves the filing as a whole. Kept in lockstep, by hand, with
#: `check_accounting_identities` (same discipline that module already
#: applies between `check_accounting_identities` and `_identity_diffs`).
_IDENTITY_LINES: dict[str, tuple[str, ...]] = {
    "assets = equity + liabilities": (
        "total_assets", "total_equity", "total_liabilities",
    ),
    "assets = equity and liabilities": (
        "total_assets", "total_equity_and_liabilities",
    ),
    "assets = current + non-current": (
        "total_assets", "total_current_assets", "total_non_current_assets",
        "assets_held_for_sale",
    ),
    "liabilities = current + non-current": (
        "total_liabilities", "total_current_liabilities",
        "total_non_current_liabilities",
        "liabilities_associated_with_assets_held_for_sale",
    ),
    "revenue - cost of sales = gross profit": (
        "revenue", "cost_of_sales", "gross_profit",
    ),
    "pre-tax profit - tax = net income": (
        "profit_before_tax", "income_tax_expense", "net_income",
    ),
    "CFO + investing + financing = net change in cash": (
        "cash_flow_from_operations", "net_cash_from_investing_activities",
        "net_cash_from_financing_activities", "net_increase_in_cash",
    ),
}


@dataclass(frozen=True)
class FailedCheck:
    check: str
    detail: str


@dataclass(frozen=True)
class LineValidation:
    passed: bool
    failures: tuple[FailedCheck, ...]


def validate_filing(values: Mapping[str, Decimal]) -> dict[str, LineValidation]:
    """Per-line pass / fail for one filing's confirmable values.

    A line fails when it participates in an accounting identity that is
    off by more than ordinary publication rounding
    (`_IDENTITY_ROUNDING_TOLERANCE`, Rs 1,000 — every real leading-digit
    or column-shift error found on this exchange is wrong by tens of
    millions at least), or when its magnitude is implausible relative to
    the rest of the filing. Every line no failing check touches passes.
    The returned dict has one entry per input line.
    """
    values = {k: v for k, v in values.items()}
    failures_by_line: dict[str, list[FailedCheck]] = defaultdict(list)

    for name, diff in _identity_diffs(values).items():
        if diff <= _IDENTITY_ROUNDING_TOLERANCE:
            continue
        detail = f"identity '{name}' is off by {diff:,}"
        for line in _IDENTITY_LINES.get(name, ()):
            if line in values:
                failures_by_line[line].append(FailedCheck(name, detail))

    if _magnitude_implausible_keys(values):
        largest_key = max(values, key=lambda k: abs(values[k]))
        largest = abs(values[largest_key])
        for line in _magnitude_implausible_keys(values):
            ratio = abs(values[line]) / largest if largest else Decimal(0)
            failures_by_line[line].append(
                FailedCheck(
                    f"{line} implausibly small vs {largest_key}",
                    f"{line} = {values[line]:,} is only {ratio:.2e}x this filing's own "
                    f"largest value ({largest_key} = {largest:,}) — almost certainly a "
                    "corrupted read, not a genuine figure",
                )
            )

    return {
        line: LineValidation(
            passed=line not in failures_by_line,
            failures=tuple(failures_by_line.get(line, ())),
        )
        for line in values
    }
