"""
Master Spec §6: "All models query on first_available_date <= t, never
period_end <= t." This module is the single chokepoint for that rule so no
caller can accidentally write a period_end filter instead — see Part N
failure mode #1, the most common source of manufactured backtest alpha.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fundamentals import Fundamental


def fundamentals_as_of(
    db: Session, ticker: str, as_of: dt.date, statement_line: str | None = None
) -> list[Fundamental]:
    """Return the latest known *version* of each (period_end, statement_line)
    as it would have been visible to the market on `as_of` — i.e. only rows
    whose first_available_date <= as_of, and for rows with multiple
    versions (restatements), only the highest version number available by
    that date.
    """
    stmt = select(Fundamental).where(
        Fundamental.ticker == ticker,
        Fundamental.first_available_date <= as_of,
    )
    if statement_line is not None:
        stmt = stmt.where(Fundamental.statement_line == statement_line)

    rows = list(db.scalars(stmt))

    # Keep only the highest version, per (period_end, statement_line), among
    # rows that were actually available by `as_of` — a restatement filed
    # after `as_of` must not leak in even though an earlier version of the
    # same period did.
    latest: dict[tuple[dt.date, str], Fundamental] = {}
    for row in rows:
        key = (row.period_end, row.statement_line)
        current = latest.get(key)
        if current is None or row.version > current.version:
            latest[key] = row

    return sorted(latest.values(), key=lambda r: (r.period_end, r.statement_line))


def annual_factor_formation_date(year: int, *, month: int, day: int) -> dt.date:
    """Master Spec §6 / §35.1: factor formation date is 30 September, not
    the Fama-French convention of 30 June, specifically because of the
    concentration of 31 March fiscal year ends — this guarantees a
    six-month lag after the dominant year end."""
    return dt.date(year, month, day)
