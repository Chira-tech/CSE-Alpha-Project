"""DB-wired driver for `app.domain.fundamental_validation`.

Groups every `fundamentals` row into its filing (ticker, period_end,
period_type), runs the check battery over the values the valuation engine
would actually use (the highest available version of each confirmable
line), and upserts one `fundamental_validations` row per `fundamentals`
row with the pass / fail verdict.

One load of the whole table, then in-Python assembly — the same batching
discipline as `app.domain.fundamental_cross_check_view` and
`app.domain.fundamentals_view.bulk_latest_line_items`.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamental_validation import VALIDATION_METHOD, validate_filing
from app.domain.provenance import can_enter_valuation
from app.models.fundamental_validation import FundamentalValidation
from app.models.fundamentals import Fundamental


@dataclass
class ValidationSweepSummary:
    filings: int
    rows_checked: int
    rows_passed: int
    rows_failed: int

    def as_dict(self) -> dict[str, int]:
        return {
            "filings": self.filings,
            "rows_checked": self.rows_checked,
            "rows_passed": self.rows_passed,
            "rows_failed": self.rows_failed,
        }


def _filing_key(row: Fundamental) -> tuple[str, dt.date, str]:
    return (row.ticker, row.period_end, row.period_type)


def revalidate_all(
    db: Session, *, tickers: set[str] | None = None, on_progress=None
) -> ValidationSweepSummary:
    """Re-run the gate over every filing (or just `tickers`) and rewrite
    its `fundamental_validations` rows. Idempotent: a filing whose values
    have not changed produces the same verdicts.

    `on_progress(done, total, ticker)` is called after each filing when
    supplied; returning `False` stops the sweep (the cooperative-cancel
    contract `app.jobs.runner` already uses).
    """
    stmt = select(Fundamental)
    if tickers is not None:
        stmt = stmt.where(Fundamental.ticker.in_(tickers))
    rows = list(db.scalars(stmt))

    by_filing: dict[tuple[str, dt.date, str], list[Fundamental]] = defaultdict(list)
    for row in rows:
        by_filing[_filing_key(row)].append(row)

    # Load the whole verdict table (it is 1:1 with fundamentals at most,
    # same order of magnitude as `rows`) rather than an `IN (...)` over
    # tens of thousands of ids — SQLite caps bound parameters at 999.
    ids_wanted = {r.id for r in rows}
    existing = {
        v.fundamental_id: v
        for v in db.scalars(select(FundamentalValidation))
        if v.fundamental_id in ids_wanted
    }

    now = dt.datetime.now(dt.timezone.utc)
    summary = ValidationSweepSummary(0, 0, 0, 0)
    total = len(by_filing)

    for i, (key, filing_rows) in enumerate(sorted(by_filing.items()), start=1):
        summary.filings += 1

        # Highest version of each confirmable line — exactly the set the
        # valuation engine reads. A line present only as an unconfirmed
        # AI-assisted draft is already gated out by provenance and is not
        # validated here.
        best: dict[str, Fundamental] = {}
        for row in filing_rows:
            if not can_enter_valuation(row.provenance_tier):
                continue
            current = best.get(row.statement_line)
            if current is None or row.version > current.version:
                best[row.statement_line] = row

        line_verdicts = validate_filing({line: r.value for line, r in best.items()})

        for line, row in best.items():
            verdict = line_verdicts[line]
            failures_payload = json.dumps(
                [{"check": f.check, "detail": f.detail} for f in verdict.failures]
            )
            record = existing.get(row.id)
            if record is None:
                record = FundamentalValidation(fundamental_id=row.id)
                db.add(record)
                existing[row.id] = record
            record.checked_at = now
            record.passed = verdict.passed
            record.method = VALIDATION_METHOD
            record.failures_json = failures_payload

            summary.rows_checked += 1
            if verdict.passed:
                summary.rows_passed += 1
            else:
                summary.rows_failed += 1

        if on_progress is not None and on_progress(i, total, key[0]) is False:
            break

    db.commit()
    return summary


def failed_fundamental_ids(db: Session, candidate_ids: list[int]) -> set[int]:
    """The subset of `candidate_ids` whose last validation FAILED — the
    set `app.domain.point_in_time.fundamentals_as_of` removes before the
    valuation engine ever sees them. A row with no validation record yet
    is not in the result (not-yet-swept is treated as not-yet-failed).

    `candidate_ids` is normally a single ticker's rows (tens, not
    thousands), so an `IN (...)` is fine — but chunk it anyway to stay
    under SQLite's 999-bound-parameter cap for any larger caller.
    """
    if not candidate_ids:
        return set()
    wanted = set(candidate_ids)
    if len(wanted) <= 900:
        return set(
            db.scalars(
                select(FundamentalValidation.fundamental_id).where(
                    FundamentalValidation.fundamental_id.in_(wanted),
                    FundamentalValidation.passed.is_(False),
                )
            )
        )
    return {
        fid
        for (fid,) in db.execute(
            select(FundamentalValidation.fundamental_id).where(
                FundamentalValidation.passed.is_(False)
            )
        )
        if fid in wanted
    }
