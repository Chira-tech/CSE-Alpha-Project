"""Spec §17: the company-wide data-quality view — for every security, a
pass / fail per financial year from 2020 to the present, plus the
universe-level counters.

Reads `fundamental_validations` joined to `fundamentals`; a year is
`period_end.year` of a confirmable ANNUAL row. A year cell is:
  - "ok"     — the security has confirmable annual data for that year and
               every row passed the gate;
  - "failed" — at least one row for that year failed a check (it is in
               the fundamentals queue, out of the valuation engine);
  - "none"   — no confirmable annual data for that year.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.provenance import can_enter_valuation
from app.models.fundamental_validation import FundamentalValidation
from app.models.fundamentals import Fundamental
from app.models.securities import Security

_FIRST_YEAR = 2020


@dataclass
class YearCell:
    year: int
    annual_rows: int
    failed_rows: int

    @property
    def status(self) -> str:
        if self.annual_rows == 0:
            return "none"
        return "failed" if self.failed_rows else "ok"


@dataclass
class SecurityRow:
    ticker: str
    name: str
    years: list[YearCell]
    failed_total: int


@dataclass
class ValidationGrid:
    years: list[int]
    securities: list[SecurityRow]
    total_securities: int
    securities_with_fundamentals: int
    securities_fully_validated: int
    securities_with_failures: int
    total_rows_checked: int
    total_rows_failed: int
    pct_rows_validated: Decimal | None
    last_swept_at: dt.datetime | None = None
    unswept_rows: int = 0
    _meta: dict = field(default_factory=dict)


def validation_grid(db: Session) -> ValidationGrid:
    this_year = dt.date.today().year
    years = list(range(_FIRST_YEAR, this_year + 1))

    names = {t: n for t, n in db.execute(select(Security.ticker, Security.name))}
    total_securities = len(names)

    # One pass over the confirmable annual rows + their verdicts.
    verdicts = {
        v.fundamental_id: v for v in db.scalars(select(FundamentalValidation))
    }

    # counts[(ticker, year)] = [annual_rows, failed_rows]
    counts: dict[tuple[str, int], list[int]] = {}
    rows_checked = 0
    rows_failed = 0
    unswept = 0
    last_swept: dt.datetime | None = None

    for row in db.scalars(select(Fundamental).where(Fundamental.period_type == "annual")):
        if not can_enter_valuation(row.provenance_tier):
            continue
        year = row.period_end.year
        if year < _FIRST_YEAR:
            continue
        cell = counts.setdefault((row.ticker, year), [0, 0])
        cell[0] += 1
        verdict = verdicts.get(row.id)
        if verdict is None:
            unswept += 1
            continue
        rows_checked += 1
        if verdict.checked_at is not None and (last_swept is None or verdict.checked_at > last_swept):
            last_swept = verdict.checked_at
        if not verdict.passed:
            cell[1] += 1
            rows_failed += 1

    tickers_with_data = {t for (t, _y) in counts}
    securities: list[SecurityRow] = []
    fully_validated = 0
    with_failures = 0
    for ticker in sorted(tickers_with_data):
        cells = [
            YearCell(y, *counts.get((ticker, y), [0, 0]))
            for y in years
        ]
        failed_total = sum(c.failed_rows for c in cells)
        securities.append(
            SecurityRow(
                ticker=ticker,
                name=names.get(ticker, ticker),
                years=cells,
                failed_total=failed_total,
            )
        )
        if failed_total:
            with_failures += 1
        else:
            fully_validated += 1

    pct = (
        (Decimal(rows_checked - rows_failed) / Decimal(rows_checked) * 100).quantize(Decimal("0.1"))
        if rows_checked
        else None
    )

    return ValidationGrid(
        years=years,
        securities=securities,
        total_securities=total_securities,
        securities_with_fundamentals=len(tickers_with_data),
        securities_fully_validated=fully_validated,
        securities_with_failures=with_failures,
        total_rows_checked=rows_checked,
        total_rows_failed=rows_failed,
        pct_rows_validated=pct,
        last_swept_at=last_swept,
        unswept_rows=unswept,
    )
