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
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fundamental_majority_vote import resolve
from app.domain.fundamental_validation import (
    VALIDATION_METHOD,
    FailedCheck,
    check_series_trend,
    validate_filing,
)
from app.domain.provenance import can_enter_valuation
from app.models.fundamental_validation import FundamentalValidation
from app.models.fundamentals import Fundamental

#: stockanalysis.com cache written by `scripts/external_crosscheck.py`.
#: The one external financial-data provider that reliably covers CSE
#: small-caps — see `revalidate_all`'s own note on why there is no
#: automated SECOND external provider and the later-filing comparative
#: column stands in as the third source.
_EXTERNAL_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "audits" / "external_fundamentals_cache.jsonl"
)

#: The publisher field -> our canonical line, kept in step with
#: `scripts/external_crosscheck.py`'s HARD_MAP (only the unambiguous
#: ones; a soft-mapped disagreement proves nothing).
_EXTERNAL_HARD_MAP: dict[str, str] = {
    "assets": "total_assets",
    "liabilities": "total_liabilities",
    "equity": "total_equity",
    "liabilitiesequity": "total_equity_and_liabilities",
    "assetsc": "total_current_assets",
    "currentLiabilities": "total_current_liabilities",
    "inventory": "inventories",
    "revenue": "revenue",
    "gp": "gross_profit",
    "opinc": "operating_profit",
    "netinccmn": "net_income",
    "ncfo": "cash_flow_from_operations",
    "ncfi": "net_cash_from_investing_activities",
    "ncff": "net_cash_from_financing_activities",
}


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


def _load_external_index() -> dict[tuple[str, str, str, str], Decimal]:
    """`{(ticker, period_end_iso, period_type, canonical_line): value}`
    from the stockanalysis.com cache. Empty when the cache file is
    absent (a fresh checkout, or CI) — the majority vote then simply has
    one fewer source, never an error."""
    index: dict[tuple[str, str, str, str], Decimal] = {}
    if not _EXTERNAL_CACHE_PATH.exists():
        return index
    with _EXTERNAL_CACHE_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for r in payload.get("_rows", []):
                canonical = _EXTERNAL_HARD_MAP.get(r.get("source_field", ""))
                if canonical is None:
                    continue
                try:
                    value = Decimal(str(r["value"]))
                except (InvalidOperation, KeyError, TypeError):
                    continue
                key = (r["ticker"], r["period_end"], r["period_type"], canonical)
                index.setdefault(key, value)  # first write wins, as in the crosscheck script
    return index


def _independent_reading(
    all_rows_for_key: list[Fundamental], chosen: Fundamental
) -> Decimal | None:
    """A reading of the same (ticker, period_end, period_type, line) from
    a DIFFERENT source document than `chosen` — in practice the same
    figure re-typed by the company in a later filing's comparative
    column. Genuinely independent of the primary extraction (different
    PDF, different parse), even though it is the same publisher. `None`
    when the value was only ever filed once."""
    for row in all_rows_for_key:
        if (
            row.id != chosen.id
            and row.source_url
            and row.source_url != chosen.source_url
            and can_enter_valuation(row.provenance_tier)
        ):
            return row.value
    return None


def _trend_failures_by_row(
    rows: list[Fundamental],
) -> dict[tuple[str, str, dt.date], tuple]:
    """Run `check_series_trend` for every (ticker, line) and return its
    failures re-keyed by (ticker, line, period_end). Only the confirmed
    ANNUAL series feeds the check — a quarter-on-quarter jump is ordinary
    seasonality, not a data error."""
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
        failures_by_label = check_series_trend(history, line)
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

    # Spec §3-4 independent-source verification. Two corroborating
    # sources for a stored CSE value: (1) the stockanalysis.com cache
    # (the one external provider that covers CSE small-caps); (2) the
    # same figure re-typed by the company in a later filing's comparative
    # column (a different PDF and a different parse — independent of the
    # primary extraction, though the same publisher). A genuine SECOND
    # external provider is not currently available for this exchange's
    # small-caps; when one is, it slots straight into `resolve`'s
    # corroborator list. A check-failed row whose stored value TWO
    # sources still agree on is rescued to pass — the identity or trend
    # flag was on a sibling line, not this figure.
    external_index = _load_external_index()
    rows_by_value_key: dict[tuple[str, dt.date, str, str], list[Fundamental]] = defaultdict(list)
    for row in rows:
        rows_by_value_key[
            (row.ticker, row.period_end, row.period_type, row.statement_line)
        ].append(row)

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

            if failures:
                corroborators: list[tuple[str, Decimal]] = []
                ext = external_index.get(
                    (row.ticker, row.period_end.isoformat(), row.period_type, line)
                )
                if ext is not None:
                    corroborators.append(("stockanalysis.com", ext))
                indep = _independent_reading(
                    rows_by_value_key[(row.ticker, row.period_end, row.period_type, line)],
                    row,
                )
                if indep is not None:
                    corroborators.append(("CSE later-filing comparative", indep))

                if corroborators:
                    resolution = resolve(row.value, corroborators)
                    if resolution.primary_is_corroborated:
                        failures = [
                            FailedCheck(
                                "rescued by independent sources",
                                "the identity/trend flag was on a sibling line — this "
                                "figure is corroborated by: "
                                + ", ".join(resolution.supporting),
                            )
                        ]
                        # falls through to `passed = not <only the rescue note>`
                    elif not resolution.unresolved:
                        failures.append(
                            FailedCheck(
                                "independent sources agree on a different value",
                                f"stored {row.value:,}; {', '.join(resolution.supporting)} "
                                f"agree on {resolution.agreed_value:,} — provisional "
                                "corrected value, pending a human",
                            )
                        )

            passed = not failures or (
                len(failures) == 1 and failures[0].check == "rescued by independent sources"
            )
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
