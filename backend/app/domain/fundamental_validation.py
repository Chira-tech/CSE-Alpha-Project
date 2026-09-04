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
VALIDATION_METHOD = "identity+magnitude+trend+majority:v4"

#: The two balance-sheet composition identities where the extracted
#: `total_equity` line is legitimately the "equity attributable to
#: owners of the parent" figure — it excludes non-controlling interest,
#: so `assets = equity + liabilities` is off by exactly the NCI. A CSE
#: group's NCI is almost always a low-single-digit share of the balance
#: sheet; a real extraction error (a dropped digit, a shifted column) is
#: an order of magnitude larger. So these two identities pass when the
#: gap is within `_NCI_RELATIVE_TOLERANCE` of the balance-sheet size,
#: not just the flat Rs 1,000 rounding tolerance. Every other identity
#: (revenue - cost of sales = gross profit, and so on) keeps the strict
#: tolerance — none of them has a legitimate structural gap.
#: (Product-owner decision, 4 Sep 2026: use owners' equity as book value
#: and allow the NCI gap.)
_NCI_TOLERANT_IDENTITIES = frozenset({
    "assets = equity + liabilities",
    "assets = equity and liabilities",
})
_NCI_RELATIVE_TOLERANCE = Decimal("0.03")

#: A confirmed value that is this many times its own immediately-prior
#: confirmed value (same company, same line, consecutive periods) — or a
#: prior value this many times it — is almost never a real year: it is a
#: dropped digit (10x), a thousands/millions unit confusion (1000x), the
#: wrong statement column, or a consolidated-vs-standalone mixup. Spec
#: §5's own example (10,100M then 101,000M) is a 10x change. Only applied
#: when BOTH values are material relative to the series (see
#: `_TREND_MATERIAL_FRACTION`), so a loss-to-profit swing off a near-zero
#: base is never flagged on ratio alone.
_TREND_JUMP_RATIO = Decimal(10)

#: Below this fraction of the line's own historical peak, a value is too
#: small for a year-on-year ratio to mean anything (a genuinely thin
#: year, a near-break-even result) — the identity and magnitude checks
#: cover a corrupted small value, not this one.
_TREND_MATERIAL_FRACTION = Decimal("0.02")

#: A line needs at least this many confirmed annual periods before the
#: trend check runs at all — two points can't establish what "ordinary"
#: looks like for the company.
_TREND_MIN_PERIODS = 3

#: Lines that a solvent going concern never legitimately reports as
#: negative — a sign flip on one of these between two material years is a
#: column / period / basis error, not a business event. Profit lines are
#: deliberately excluded: a loss year is ordinary and is not something a
#: human needs to "resolve".
_NEVER_NEGATIVE_LINES = frozenset({
    "total_assets", "total_equity", "equity_attributable_to_owners",
    "total_liabilities",
    "total_equity_and_liabilities", "total_current_assets",
    "total_non_current_assets", "total_current_liabilities",
    "total_non_current_liabilities", "revenue", "gross_profit",
    "inventories", "trade_receivables", "trade_payables",
    "cash_and_cash_equivalents", "property_plant_and_equipment",
    "total_interest_bearing_debt",
})

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

    balance_sheet_size = max(
        (abs(values[k]) for k in ("total_assets", "total_equity_and_liabilities") if k in values),
        default=Decimal(0),
    )
    for name, diff in _identity_diffs(values).items():
        tolerance = _IDENTITY_ROUNDING_TOLERANCE
        if name in _NCI_TOLERANT_IDENTITIES and balance_sheet_size > 0:
            # `total_equity` here is owners' equity; the gap up to the
            # NCI band is structural, not a corrupted read.
            tolerance = max(tolerance, balance_sheet_size * _NCI_RELATIVE_TOLERANCE)
        if diff <= tolerance:
            continue
        detail = f"identity '{name}' is off by {diff:,}"
        if name in _NCI_TOLERANT_IDENTITIES and balance_sheet_size > 0:
            detail += (
                f" ({(diff / balance_sheet_size):.1%} of the balance sheet — beyond the "
                f"{_NCI_RELATIVE_TOLERANCE:.0%} non-controlling-interest allowance)"
            )
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


def check_series_trend(
    history: list[tuple[str, Decimal]],
    line: str = "",
) -> dict[str, tuple[FailedCheck, ...]]:
    """Spec §5: test one company-line's confirmed annual series
    2020->present for a year-on-year jump no real business produces.

    `history` is `[(period_label, value), ...]` sorted oldest first (the
    caller supplies a short human label like "FY2024" and the confirmed
    value). `line` is the canonical statement line — used only to decide
    whether a sign flip is meaningful (a loss year is fine; negative
    revenue is not). Returns `{period_label: (failures,)}` for every
    period whose step from the period before it is outside
    `_TREND_JUMP_RATIO` while both values are material, or is a sign flip
    on a line that should never be negative. A period with no entry in
    the result passed the trend check.
    """
    if len(history) < _TREND_MIN_PERIODS:
        return {}
    peak = max((abs(v) for _, v in history), default=Decimal(0))
    if peak == 0:
        return {}
    floor = peak * _TREND_MATERIAL_FRACTION

    out: dict[str, tuple[FailedCheck, ...]] = {}
    for (prev_label, prev), (label, value) in zip(history, history[1:]):
        if abs(prev) < floor or abs(value) < floor:
            continue
        if line in _NEVER_NEGATIVE_LINES and (prev > 0) != (value > 0):
            out[label] = (
                FailedCheck(
                    "year-on-year sign flip",
                    f"{prev_label} = {prev:,} then {label} = {value:,} — {line} flipped "
                    "sign between two material years, which it should never do; check the "
                    "column, the period, or a consolidated-vs-standalone mixup",
                ),
            )
            continue
        hi, lo = max(abs(prev), abs(value)), min(abs(prev), abs(value))
        if lo > 0 and hi / lo >= _TREND_JUMP_RATIO:
            out[label] = (
                FailedCheck(
                    "year-on-year jump outside the ordinary range",
                    f"{prev_label} = {prev:,} then {label} = {value:,} — a "
                    f"{(hi / lo):.0f}x change; check units (thousands vs millions), a "
                    "dropped digit, the wrong column, the wrong period, or consolidated "
                    "vs standalone",
                ),
            )
    return out
