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

from app.domain.fundamental_validation import (
    VALIDATION_METHOD,
    check_series_trend,
    validate_filing,
)
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


def _trend_failures_by_row(
    rows: list[Fundamental],
) -> dict[tuple[str, str, dt.date], tuple]:
    """Run `check_series_trend` for every (ticker, line) and return its
    failures re-keyed by (ticker, line, period_end). Only the confirmed
    ANNUAL series feeds the check — a quarter-on-quarter jump is ordinary
    seasonality, not a data error."""
    from app.domain.fundamental_validation import FailedCheck  # noqa: F401 (type only)

    series: dict[tuple[str, str], dict[dt.date, Fundamental]] = defaultdict(dict)
    for row in rows:
        if row.period_type != "annual" or not can_enter_valuation(row.provenance_tier):
            continue
        key = (row.ticker, row.statement_line)
        current = series[key].get(row.period_end)
        if current is None or row.version > current.version:
            series[key][row.period_end] = row

    out: dict[tuple[str, str, dt.date], tuple] = {}
    for (ticker, line), by_period in series.items():
        ordered = sorted(by_period.items())  # (period_end, Fundamental)
        history = [(f"FY{p.year}", r.value) for p, r in ordered]
        failures_by_label = check_series_trend(history)
        if not failures_by_label:
            continue
        for (period_end, _row), (label, _v) in zip(ordered, history):
            if label in failures_by_label:
                out[(ticker, line, period_end)] = failures_by_label[label]
    return out


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

    # Spec §5 trend check: the confirmed ANNUAL series for each
    # (ticker, line), highest version per period, oldest first — computed
    # once here and merged into the per-row verdicts below. Keyed by
    # (ticker, line, period_end) so a jump fails the specific year.
    trend_failures = _trend_failures_by_row(rows)

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
            failures = list(verdict.failures)
            failures.extend(trend_failures.get((row.ticker, line, row.period_end), ()))
            passed = not failures
            failures_payload = json.dumps(
                [{"check": f.check, "detail": f.detail} for f in failures]
            )
            record = existing.get(row.id)
            if record is None:
                record = FundamentalValidation(fundamental_id=row.id)
                db.add(record)
                existing[row.id] = record
            record.checked_at = now
            record.passed = passed
            record.method = VALIDATION_METHOD
            record.failures_json = failures_payload

            summary.rows_checked += 1
            if passed:
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
