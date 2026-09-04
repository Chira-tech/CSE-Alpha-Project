"""
TASK 1.1: executes a `JobRun` row end to end — the piece that turns a
"Run Capture" click into a real, paced, cancellable, progress-reporting
ingestion sweep.

WHERE THIS RUNS. §5's pacing (`CseClient`'s own `min_seconds_between_
calls`) and the "manual triggers do not bypass rate limits" rule (§1,
standing rule 4) mean a full sweep takes up to ~10 real minutes, so it
must never run inside the request/response cycle — `app.api.routes.jobs.
trigger_job` returns 202 immediately after INSERTing the `queued` row.
Two things then execute that row, and `execute` atomically claims it so
only one wins:

  1. `poll_and_run_one`, called every few seconds by the ALWAYS-ON
     WORKER (`app.worker` → an interval job in `app.jobs.scheduler`) —
     the path for scheduled runs and for setups that keep the worker up.
  2. a daemon thread spawned by `trigger_job` itself — so "Run Capture"
     works for someone running only `uvicorn app.main:app` with no
     separate worker. It is a background thread, not the request thread,
     so the 202 is not held for the job's lifetime.

CONCURRENCY GUARD IS APPLICATION-LEVEL, NOT A DB PARTIAL UNIQUE INDEX.
See `app.models.job_run.JobRun`'s own docstring for why: this project's
real database is SQLite, which has no `WHERE` clause on `CREATE UNIQUE
INDEX`. `enqueue` re-checks for an open (`queued`/`running`) row of the
same job inside one committed transaction before inserting a new one —
a real race is still structurally possible between two near-simultaneous
requests (SQLite's own single-writer semantics make the actual window
for that vanishingly small in practice, and `poll_and_run_one` ALSO
re-checks "is anything of this job already running" immediately before
executing, a second real backstop), but this is the honest limit of
what SQLite can enforce here — not silently pretended away.

EVERY RUNNER FUNCTION BELOW WRAPS AN ALREADY-REAL INGESTION CALL. No new
data-fetching logic is invented in this file — see each `_run_*`
function's own short docstring for which existing module it delegates
to, and `app.jobs.registry`'s own module docstring for why
`capture_orderbook` (in the brief's own pseudocode) has no runner here
at all.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.domain.composite_ranking_snapshot_view import write_snapshot
from app.domain.composite_ranking_view import (
    clear_cache as clear_composite_ranking_cache,
    composite_ranking_for,
)
from app.domain.corroboration_view import (
    all_corroborated_pending_ids,
    all_identity_pinned_pending_ids,
)
from app.domain.factor_series_view import rebuild_factor_series
from app.domain.valuation_quarantine_view import record_sanity_result
from app.domain.valuation_view import valuation_summary_for
from app.ingestion.cbsl_client import CbslClient
from app.ingestion.cbsl_loader import ingest_range as ingest_cbsl_range
from app.ingestion.corporate_actions_loader import (
    ingest_corporate_actions_for_ticker,
    recently_scanned_tickers,
)
from app.ingestion.cse_client import CseClient
from app.ingestion.financial_pdf_extractor import (
    ingest_financial_statements_for_known_tickers,
    sweep_stale_fundamentals,
)
from app.ingestion.market_internals import ingest_market_internals
from app.ingestion.bootstrap import bootstrap_securities
from app.ingestion.price_loader import fetch_eod_prices, infer_session_date, upsert_eod_prices
from app.ingestion.security_enrichment import enrich_securities
from app.jobs.adjustment_factors import rebuild_all_adjustment_factors
from app.jobs.registry import JOBS, job_definition
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.job_run import JobRun
from app.models.prices import PriceDaily
from app.models.securities import Security

logger = logging.getLogger("cse_alpha.jobs.runner")

MANUAL_COOLDOWN_SECONDS = 15 * 60


class JobConflict(Exception):
    """Raised by `enqueue` when this job is already `queued`/`running` —
    the caller (the API route) turns this into a 409, per TASK 1.1's own
    spec ("Returns 409 if already running — never queue a duplicate")."""


class JobCooldown(Exception):
    """Raised by `enqueue` when a MANUAL run of this job started within
    the last `MANUAL_COOLDOWN_SECONDS` — the caller turns this into a
    429 with `retry_after`, per TASK 1.1's own acceptance test."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def _all_tickers(db: Session) -> list[str]:
    return [t for (t,) in db.execute(select(Security.ticker)).all()]


def recover_orphaned_runs(db: Session) -> int:
    """Called once, at worker startup, before the scheduler starts.

    REAL BUG, FOUND LIVE (23 Aug 2026): a `JobRun` stuck in `queued`/
    `running` from a worker process that died mid-job (see `app.worker`'s
    own top-of-file comment for the real crash this closes) blocks
    `enqueue`'s own concurrency guard FOREVER — nothing was left alive to
    ever mark it `failed`, so every future `POST /jobs/{job}/run` for
    that same job 409s indefinitely, and the sidebar's own "Run Capture"
    control looks permanently broken for that one job even though the
    worker itself has since restarted and is healthy. Since this
    function only ever runs at the START of a fresh worker process — the
    one thing in this whole system that is ever allowed to move a row
    out of `queued`/`running` — any row still in either state when this
    runs was left there by a PREVIOUS process that no longer exists, not
    a job this new process is already mid-way through (that can't happen
    yet; the scheduler hasn't started). Marked `failed` with a real,
    honest error rather than silently deleted or left ambiguous."""
    stale = db.scalars(
        select(JobRun).where(JobRun.status.in_(("queued", "running")))
    ).all()
    for run in stale:
        run.status = "failed"
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        run.error = (
            "Interrupted: the worker process running this job exited before it finished "
            "(crash, forced stop, or host restart) — no result was produced. Safe to re-run."
        )
    if stale:
        db.commit()
    return len(stale)


def enqueue(db: Session, job_key: str, *, trigger: str = "manual") -> JobRun:
    """Validates `job_key`, enforces the concurrency guard and (for
    `trigger="manual"`) the 15-minute cooldown, then inserts and commits
    a `queued` row. Never executes the job itself — see this module's
    own docstring for why."""
    if job_definition(job_key) is None:
        raise KeyError(f"unknown job {job_key!r}")

    existing_open = db.scalar(
        select(JobRun).where(JobRun.job == job_key, JobRun.status.in_(("queued", "running"))).limit(1)
    )
    if existing_open is not None:
        raise JobConflict(job_key)

    if trigger == "manual":
        last_manual = db.scalar(
            select(JobRun)
            .where(JobRun.job == job_key, JobRun.trigger == "manual")
            .order_by(JobRun.created_at.desc())
            .limit(1)
        )
        if last_manual is not None:
            # SQLite (this project's real dev database — see JobRun's own
            # docstring) round-trips a `DateTime(timezone=True)` column
            # back as NAIVE; Postgres preserves it. Every `created_at` in
            # this table is always written as UTC-aware, so a naive read
            # is unambiguously UTC, not a guess — subtracting it directly
            # against an aware "now" would otherwise raise `TypeError:
            # can't subtract offset-naive and offset-aware datetimes` the
            # first time this exact path (a real manual re-trigger inside
            # the cooldown window) is actually exercised on SQLite.
            last_manual_at = last_manual.created_at
            if last_manual_at.tzinfo is None:
                last_manual_at = last_manual_at.replace(tzinfo=dt.timezone.utc)
            elapsed = (dt.datetime.now(dt.timezone.utc) - last_manual_at).total_seconds()
            if elapsed < MANUAL_COOLDOWN_SECONDS:
                raise JobCooldown(int(MANUAL_COOLDOWN_SECONDS - elapsed))

    run = JobRun(
        job=job_key, trigger=trigger, status="queued", progress_pct=Decimal(0),
        rows_written=0, cancel_requested=False, created_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _set_progress(db: Session, run: JobRun, pct: float, note: str) -> bool:
    """Writes progress and returns `False` if a cancel was requested in
    the meantime (checked by re-reading the row) — the runner's own loops
    check this return value between tickers, TASK 1.1's own "cooperative
    cancel" requirement."""
    db.refresh(run)
    if run.cancel_requested:
        return False
    run.progress_pct = Decimal(str(round(pct, 2)))
    run.progress_note = note
    db.commit()
    return True


def _finish(db: Session, run: JobRun, *, status: str, rows_written: int = 0, error: str | None = None) -> None:
    run.status = status
    run.finished_at = dt.datetime.now(dt.timezone.utc)
    run.rows_written = rows_written
    run.error = error
    if status == "success":
        run.progress_pct = Decimal(100)
    db.commit()


def _run_capture_prices(db: Session, run: JobRun) -> int:
    """§52's EOD snapshot — a single bulk `tradeSummary` call, not a
    per-ticker loop, so progress is coarse (0 -> 100) rather than a
    ticker count: there genuinely is no intermediate step to report."""
    _set_progress(db, run, 10, "Fetching EOD trade summary...")
    with CseClient() as client:
        rows = fetch_eod_prices(client)
    session_date = infer_session_date(rows)
    if session_date is None:
        raise RuntimeError("could not determine session date from feed; nothing written")
    # Register newly-seen tickers before writing their prices — see the
    # same call in `app.jobs.scheduler`'s EOD job for the real orphaned-row
    # gap this closes. Idempotent, no extra request, never overwrites.
    _set_progress(db, run, 60, "Registering any newly-listed securities...")
    bootstrap_securities(db, rows)
    _set_progress(db, run, 70, f"Writing {len(rows)} rows for session {session_date}...")
    return upsert_eod_prices(db, session_date, rows)


def _run_rebuild_adjustment_factors(db: Session, run: JobRun) -> int:
    """§7's total-return adjustment factors, rebuilt from confirmed
    corporate actions. Safety net behind the synchronous rebuild that
    `POST /corporate-actions/{id}/confirm` already does — see
    `app.jobs.adjustment_factors` for the real gap this closes."""
    def on_progress(i: int, total: int, ticker: str) -> None:
        if i % 25 == 0 or i == total:
            _set_progress(db, run, int(i / max(total, 1) * 100), f"{ticker} ({i}/{total})")

    summary = rebuild_all_adjustment_factors(db, on_progress=on_progress)
    return int(summary["price_rows_changed"])


def _run_capture_market(db: Session, run: JobRun) -> int:
    _set_progress(db, run, 20, "Fetching market internals...")
    with CseClient() as client:
        return ingest_market_internals(client, db)


def _run_capture_macro(db: Session, run: JobRun) -> int:
    _set_progress(db, run, 20, "Fetching CBSL indicators...")
    end = dt.date.today()
    start = end - dt.timedelta(days=6)
    with CbslClient() as client:
        result = ingest_cbsl_range(client, db, start, end)
    return int(result["observations"])


def _run_capture_filings(db: Session, run: JobRun) -> int:
    """§5's financial-statement scan. `ingest_financial_statements_for_
    known_tickers` fetches and matches client-side in one pass (see its
    own module docstring for why — no per-company filter on the feed) —
    coarse progress, same reasoning as `_run_capture_prices`."""
    tickers = _all_tickers(db)
    _set_progress(db, run, 15, f"Scanning recent filings against {len(tickers)} known tickers...")
    with CseClient() as client:
        return ingest_financial_statements_for_known_tickers(client, db, tickers)


def _run_capture_corporate_actions(db: Session, run: JobRun) -> int:
    """Mirrors `app.jobs.scheduler._job_corporate_actions_scan` exactly,
    plus the SAME resumability this session already built for the CLI
    (`app.ingestion.corporate_actions_loader.recently_scanned_tickers`)
    — a manual trigger killed partway through (this environment's own
    real, previously-documented constraint) makes permanent progress
    the same way the CLI sweep does, rather than restarting at ticker
    #1 every time. This is also the one job whose per-ticker progress
    genuinely matches TASK 1.1's own "148 / 286 tickers" example."""
    all_tickers = _all_tickers(db)
    already_scanned = recently_scanned_tickers(db, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20))
    tickers = [t for t in all_tickers if t not in already_scanned]
    total = len(tickers)
    if total == 0:
        _set_progress(db, run, 100, "Every ticker already scanned within the last 20 hours.")
        return 0

    total_drafted = 0
    with CseClient() as client:
        for i, ticker in enumerate(tickers, start=1):
            if not _set_progress(db, run, 100 * (i - 1) / total, f"Corporate actions · {i} / {total} tickers ({ticker})"):
                logger.info("corporate actions run %s: cancelled at ticker %d/%d", run.id, i, total)
                return total_drafted
            try:
                total_drafted += ingest_corporate_actions_for_ticker(client, db, ticker)
            except Exception:
                logger.exception("corporate-actions ingest failed for %s", ticker)
    return total_drafted


#: A ticker whose latest `float_data` row (shares / market cap / price)
#: is newer than this is not re-fetched by a manual enrich or by
#: `capture_all` — the same "only pick up what's new" discipline
#: `_run_capture_corporate_actions` already applies with its 20-hour
#: skip. `companyInfoSummery` changes at most a few times a year for a
#: given line (a rights issue, a bonus), so a week is comfortably safe.
ENRICH_SKIP_IF_FRESH_DAYS = 7


def _run_enrich_securities(db: Session, run: JobRun) -> int:
    from app.models.float_data import FloatData

    cutoff = dt.date.today() - dt.timedelta(days=ENRICH_SKIP_IF_FRESH_DAYS)
    fresh = {
        t
        for (t,) in db.execute(
            select(FloatData.ticker)
            .where(FloatData.published_price.is_not(None))
            .group_by(FloatData.ticker)
            .having(func.max(FloatData.as_of) >= cutoff)
        )
    }
    tickers = [t for t in _all_tickers(db) if t not in fresh]
    if not tickers:
        _set_progress(
            db, run, 100,
            f"Every line enriched within the last {ENRICH_SKIP_IF_FRESH_DAYS} days — nothing new to fetch.",
        )
        return 0

    def on_ticker(i: int, n: int, ticker: str) -> bool:
        # `enrich_securities` itself breaks its own loop on a `False`
        # return (see that function's own docstring for why this must be
        # an honoured signal, not just a locally-remembered flag) — so
        # `_set_progress`'s own bool ("did the caller ask to cancel?")
        # passes straight through with nothing extra to track here.
        return _set_progress(db, run, 100 * i / n, f"Security enrichment · {i} / {n} tickers ({ticker})")

    with CseClient() as client:
        summary = enrich_securities(client, db, tickers, on_ticker=on_ticker)
    return summary.get("enriched", 0) if isinstance(summary, dict) else int(summary or 0)


def _run_universe_integrity_checks(db: Session, run: JobRun) -> int:
    """docs/CSE_Universe_Integrity_Rollout.md Phase 2 — run the
    universe-wide detectors that had no nightly job (rights-price
    coherence, nil-paid fingerprint, price discontinuity, rights-line
    reaping) across every line, raising/auto-resolving `DataAlert`s. Same
    real work as `app.jobs.scheduler._job_universe_integrity_checks`, just
    triggerable on demand. Returns the number of tickers with at least one
    open alert after the sweep."""
    from app.jobs.universe_integrity_checks import run_nightly_universe_integrity

    tickers = _all_tickers(db)
    stamp = dt.date.today()

    def on_progress(i: int, total: int, ticker: str) -> bool:
        return _set_progress(db, run, 100 * i / max(total, 1), f"Universe integrity · {i} / {total} ({ticker})")

    results = run_nightly_universe_integrity(db, tickers, stamp, on_progress=on_progress)
    return sum(1 for alerts in results.values() if alerts)


def _run_recompute(db: Session, run: JobRun) -> int:
    """"Rebuild valuations" — this system computes fair value LIVE on
    every read rather than from a persisted cache (see `app.domain.
    valuation_view.valuation_summary_for`'s own docstring), so there is
    no stored table for this job to overwrite. What it DOES do, and the
    real reason it is worth a manual trigger: re-run TASK 0.1's
    plausibility gate for every ticker with confirmed fundamentals right
    now, so a `DataAlert` quarantine record left over from a since-fixed
    data issue gets auto-resolved (`app.domain.valuation_quarantine_
    view.record_sanity_result`'s own self-healing behaviour) without
    waiting for a human to happen to reopen that one company's page.
    """
    stamp = dt.date.today()
    tickers = sorted(
        {
            t
            for (t,) in db.execute(select(Fundamental.ticker).distinct()).all()
        }
    )
    total = len(tickers)
    checked = 0
    for i, ticker in enumerate(tickers, start=1):
        if not _set_progress(db, run, 100 * (i - 1) / max(total, 1), f"Rechecking valuations · {i} / {total} ({ticker})"):
            break
        security = db.get(Security, ticker)
        archetype = security.archetype if security is not None else None
        price = db.scalar(
            select(PriceDaily.close)
            .where(PriceDaily.ticker == ticker, PriceDaily.close.is_not(None))
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )
        try:
            summary = valuation_summary_for(db, ticker, archetype, price, stamp)
            if summary.sanity is not None:
                record_sanity_result(db, ticker, summary.sanity)
            checked += 1
        except Exception:
            logger.exception("recompute: valuation re-check failed for %s", ticker)
    return checked


def _run_rebuild_factor_series(db: Session, run: JobRun) -> int:
    """§35's weekly factor return series — `app.domain.factor_series_
    view.rebuild_factor_series`'s own bulk-loaded builder, run here
    rather than inline anywhere because even the bulk-loaded path is a
    real, multi-minute pass over this system's full price history (see
    that module's own docstring for the ~142,000-call naive alternative
    this bulk approach avoids) — exactly the "never inline in a request
    handler" rule this file's own module docstring states."""
    def on_progress(done: int, total: int, message: str) -> bool:
        pct = 100 * done / max(total, 1)
        return _set_progress(db, run, pct, message)

    summary = rebuild_factor_series(db, on_progress=on_progress)
    for warning in summary.warnings[:20]:
        logger.warning("rebuild_factor_series: %s", warning)
    return sum(summary.rows_written.values())


def _run_refresh_stale_fundamentals(db: Session, run: JobRun) -> int:
    """The manual "Run Capture" trigger for `app.ingestion.financial_pdf_
    extractor.sweep_stale_fundamentals` — re-checks every ticker's
    already-stored fundamentals against `check_extraction_quality` and
    re-extracts any filing still failing. Also runs on its own weekly
    Saturday cron (`app.jobs.scheduler._job_refresh_stale_fundamentals`);
    this is the same real sweep, just triggerable on demand rather than
    waiting for Saturday — e.g. right after a `check_extraction_quality`
    check gets a new rule added, or after fixing a real extractor bug,
    when a human wants the backlog swept NOW rather than at the next
    scheduled run.

    Progress is reported per FILING CHECKED (`sweep_stale_fundamentals`'s
    own `on_filing` — mirrors `_run_enrich_securities`'s per-ticker
    convention), not per ticker: the count that actually matters here is
    how many filings still need a real download, which is usually far
    fewer than the ticker count and only known once every ticker's stored
    rows have been grouped and checked.
    """
    tickers = _all_tickers(db)

    def on_filing(i: int, total: int, label: str) -> bool:
        return _set_progress(db, run, 100 * i / max(total, 1), f"Stale fundamentals · {i} / {total} ({label})")

    outcomes = sweep_stale_fundamentals(db, tickers, on_filing=on_filing)
    repaired = sum(1 for o in outcomes if o.status == "repaired")
    still_failing = sum(1 for o in outcomes if o.status == "still_failing")
    if outcomes:
        logger.info(
            "refresh_stale_fundamentals: %d filing(s) checked, %d repaired, %d still fail",
            len(outcomes), repaired, still_failing,
        )
    return repaired


def _run_recompute_composite_ranking(db: Session, run: JobRun) -> int:
    """Runs §38's real ~70s universe pass (`app.domain.composite_ranking_
    view`) ONCE and freezes the result in a `composite_ranking_snapshots`
    row, so `GET /composite-ranking` reads a finished result instead of
    triggering the pass on a page load — the redesign doc's §2 fix. The
    module cache is cleared first so a run always reflects the very latest
    confirmed data, not whatever a `/opportunities` hit warmed 30s ago.

    Coarse progress (0 → 100): the pass has no per-ticker callback hook to
    report against, same as `_run_capture_prices`. Returns the number of
    ranked rows written, for the `rows_written` column.
    """
    _set_progress(db, run, 5, "Clearing the composite-ranking cache…")
    clear_composite_ranking_cache()
    _set_progress(db, run, 10, "Running the §38 universe pass (~70s)…")
    started = time.monotonic()
    view = composite_ranking_for(db)
    duration = Decimal(str(round(time.monotonic() - started, 2)))
    _set_progress(db, run, 90, f"Freezing snapshot ({len(view.ranked)} ranked)…")
    write_snapshot(db, view, computed_at=dt.datetime.now(dt.timezone.utc), duration_seconds=duration)
    logger.info(
        "recompute_composite_ranking: %d ranked, %d excluded, pass took %ss",
        len(view.ranked), len(view.excluded), duration,
    )
    return len(view.ranked)


def _run_auto_confirm_corroborated(db: Session, run: JobRun) -> int:
    """Promotes every pending AI-assisted fundamental the SERVER can
    independently verify as corroborated (`app.domain.corroboration_view`)
    — an independently-sourced REPORTED row already carrying the exact
    same value from a different `source_url`. This is the one case R1 T2.5
    already declared safe to confirm without a human looking at each
    value; this job applies it on a schedule instead of waiting for
    someone to click "Confirm N corroborated".

    `confirmed_by` is stamped `"auto (corroborated)"` — a distinct,
    searchable marker, mirroring the existing `"{actor} (corroborated
    bulk confirm)"` convention — so an audit never mistakes an unattended
    promotion for a genuine per-row human review.

    A second, independent signal runs in the same job: a row whose value
    is arithmetically pinned by an accounting identity that already
    balances against a human-confirmed line on the same filing
    (`all_identity_pinned_pending_ids`). Those are stamped
    `"auto (identity-pinned)"`.
    """
    _set_progress(db, run, 5, "Scanning the pending queue for corroborated figures…")
    corroborated = list(all_corroborated_pending_ids(db))
    _set_progress(db, run, 15, "Scanning the pending queue for identity-pinned figures…")
    pinned = [i for i in all_identity_pinned_pending_ids(db) if i not in set(corroborated)]

    plan: list[tuple[int, str]] = (
        [(i, "auto (corroborated)") for i in corroborated]
        + [(i, "auto (identity-pinned)") for i in pinned]
    )
    if not plan:
        _set_progress(db, run, 100, "Nothing corroborated or identity-pinned in the pending queue.")
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    confirmed = 0
    for i, (fundamental_id, marker) in enumerate(plan, start=1):
        row = db.get(Fundamental, fundamental_id)
        # Re-check under the row we're about to write — a human may have
        # confirmed it between the scan above and here.
        if row is None or row.confirmed_by is not None or row.provenance_tier != ProvenanceTier.AI_ASSISTED:
            continue
        row.provenance_tier = ProvenanceTier.REPORTED
        row.confirmed_by = marker
        row.confirmed_at = now
        confirmed += 1
        if i % 100 == 0:
            db.commit()
            if not _set_progress(db, run, 100 * i / len(plan), f"Auto-confirmed {confirmed} / {len(plan)}…"):
                break
    db.commit()
    logger.info(
        "auto_confirm_corroborated_fundamentals: promoted %d figure(s) "
        "(%d corroborated, %d identity-pinned)",
        confirmed, len(corroborated), len(pinned),
    )
    return confirmed


def _run_validate_fundamentals(db: Session, run: JobRun) -> int:
    """Re-run the data-integrity gate (`app.domain.fundamental_validation`)
    over every filing and rewrite its `fundamental_validations` rows. A
    value that fails a check drops out of the valuation engine (via
    `app.domain.point_in_time.fundamentals_as_of`) and shows in the
    fundamentals queue instead — the framework spec's binary model
    (3 Sep 2026). Idempotent; returns the number of rows that failed.
    """
    from app.domain.fundamental_validation_view import revalidate_all

    def on_progress(done: int, total: int, ticker: str) -> bool:
        # `_set_progress` commits, and `revalidate_all` calls this once
        # per filing (~11,700) — reporting every time would turn one
        # bulk write into thousands of tiny transactions. Report every
        # 250 filings; a cancel is still honoured within a few seconds.
        if done % 250 and done != total:
            return not run.cancel_requested
        return _set_progress(
            db, run, 100 * done / max(total, 1),
            f"Validating fundamentals · {done} / {total} filings ({ticker})",
        )

    summary = revalidate_all(db, on_progress=on_progress)
    logger.info(
        "validate_fundamentals: %d filings, %d rows checked, %d failed",
        summary.filings, summary.rows_checked, summary.rows_failed,
    )
    return summary.rows_failed


_RUNNERS = {
    "capture_prices": _run_capture_prices,
    "capture_market": _run_capture_market,
    "capture_macro": _run_capture_macro,
    "capture_filings": _run_capture_filings,
    "capture_corporate_actions": _run_capture_corporate_actions,
    "enrich_securities": _run_enrich_securities,
    "recompute": _run_recompute,
    "rebuild_adjustment_factors": _run_rebuild_adjustment_factors,
    "rebuild_factor_series": _run_rebuild_factor_series,
    "refresh_stale_fundamentals": _run_refresh_stale_fundamentals,
    "validate_fundamentals": _run_validate_fundamentals,
    "universe_integrity_checks": _run_universe_integrity_checks,
    "recompute_composite_ranking": _run_recompute_composite_ranking,
    "auto_confirm_corroborated_fundamentals": _run_auto_confirm_corroborated,
}


def _execute_leaf_job(db: Session, run: JobRun) -> None:
    fn = _RUNNERS[run.job]
    run.status = "running"
    run.started_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    try:
        rows = fn(db, run)
        db.refresh(run)
        if run.cancel_requested:
            _finish(db, run, status="cancelled", rows_written=rows or 0)
        else:
            _finish(db, run, status="success", rows_written=rows or 0)
    except Exception as exc:  # noqa: BLE001 — must always leave a terminal status
        logger.exception("job run %s (%s) failed", run.id, run.job)
        _finish(db, run, status="failed", error=str(exc))


def _execute_capture_all(db: Session, run: JobRun) -> None:
    """TASK 1.1: "capture_all runs sub-jobs sequentially and reports
    which one it is on." Runs each sub-job's own runner function
    directly (not through the queue — this IS the queue's one active
    slot) so a single `capture_all` JobRun row carries the whole
    sequence's combined progress rather than fanning out into further
    `JobRun` rows a caller would have to correlate."""
    sub_jobs = job_definition("capture_all").sub_jobs
    run.status = "running"
    run.started_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    total_rows = 0
    try:
        for i, sub_key in enumerate(sub_jobs):
            db.refresh(run)
            if run.cancel_requested:
                _finish(db, run, status="cancelled", rows_written=total_rows)
                return
            label = JOBS[sub_key].label
            if not _set_progress(db, run, 100 * i / len(sub_jobs), f"{label} ({i + 1} / {len(sub_jobs)})"):
                _finish(db, run, status="cancelled", rows_written=total_rows)
                return
            total_rows += _RUNNERS[sub_key](db, run) or 0
        _finish(db, run, status="success", rows_written=total_rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("capture_all run %s failed", run.id)
        _finish(db, run, status="failed", rows_written=total_rows, error=str(exc))


def execute(run_id: int) -> None:
    """Runs one `JobRun` to completion in the CALLING process — always
    leaves a terminal `status`, even on an unhandled exception, per
    TASK 1.1's own "Every run writes a job_runs row whether it succeeds
    or fails." Opens its own session: the caller may be running on a
    scheduler thread, or the API's own request thread (see
    `app.api.routes.jobs.trigger_job` — a manual trigger now runs the
    job in-process so "Run Capture" works with just `uvicorn app.main`
    and no separate `python -m app.worker`).

    ATOMICALLY CLAIMS the run first — flips `queued` -> `running` in a
    single conditional UPDATE and only proceeds if that affected a row.
    Two things can call this for the same run now (the API thread and,
    if one is also up, the worker's `poll_and_run_one`); the claim makes
    the loser a no-op instead of a double execution."""
    db = SessionLocal()
    try:
        claimed = db.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == "queued")
            .values(status="running", started_at=dt.datetime.now(dt.timezone.utc))
        )
        db.commit()
        if claimed.rowcount == 0:
            logger.info("execute: job_run %s was not claimable (already taken or gone)", run_id)
            return
        run = db.get(JobRun, run_id)
        if run is None:
            logger.error("execute: job_run %s not found", run_id)
            return
        if run.job == "capture_all":
            _execute_capture_all(db, run)
        else:
            _execute_leaf_job(db, run)
    finally:
        db.close()


def poll_and_run_one() -> bool:
    """Called every few seconds by `app.jobs.scheduler`'s own interval
    job. Picks the SINGLE oldest `queued` run whose job is not already
    `running`, and executes it synchronously (blocking this call until
    that job finishes) — see this module's own docstring for why one
    slot at a time is the honest choice for what SQLite can actually
    guarantee here. Returns `True` if a job was picked up (so the
    scheduler can immediately poll again rather than waiting a full
    interval), `False` if the queue was empty."""
    db = SessionLocal()
    try:
        running_jobs = {
            j for (j,) in db.execute(select(JobRun.job).where(JobRun.status == "running")).all()
        }
        candidates = db.scalars(
            select(JobRun).where(JobRun.status == "queued").order_by(JobRun.created_at.asc())
        ).all()
        next_run = next((r for r in candidates if r.job not in running_jobs), None)
        if next_run is None:
            return False
        run_id = next_run.id
    finally:
        db.close()

    execute(run_id)
    return True
