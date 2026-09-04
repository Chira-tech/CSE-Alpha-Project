"""Every scheduler job that has a tracked `app.jobs.runner` counterpart
must enqueue it as a `JobRun` rather than doing the ingestion inline.

Found live (4 Sep 2026): Data Health's "Macro job last succeeded: never"
turned out to be several scheduler jobs (`_job_cbsl_indicators` and its
siblings) calling their ingestion functions directly, so
`_last_successful_run(db, job)` — which only reads `job_runs` rows — could
never see a real success from the automatic nightly run, only from a
manual "Run Capture" click. These tests pin the fix: each job calls
`enqueue(db, <job_key>, trigger="scheduled")`, nothing else, so a real
`job_runs` row lands for every nightly run.
"""
from __future__ import annotations

import pytest

from app.jobs import scheduler as sched


class _StubSession:
    """Stands in for `SessionLocal()` — just needs `.close()` to exist,
    since `enqueue` itself is monkeypatched out before it would touch it."""

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _stub_session_local(monkeypatch):
    monkeypatch.setattr(sched, "SessionLocal", lambda: _StubSession())


@pytest.mark.parametrize(
    "job_fn, job_key",
    [
        (sched._job_eod_snapshot, "capture_prices"),
        (sched._job_capture_market_internals, "capture_market"),
        (sched._job_cbsl_indicators, "capture_macro"),
        (sched._job_refresh_stale_fundamentals, "refresh_stale_fundamentals"),
        (sched._job_universe_integrity_checks, "universe_integrity_checks"),
        (sched._job_corporate_actions_scan, "capture_corporate_actions"),
        (sched._job_financial_statement_scan, "capture_filings"),
        (sched._job_validate_fundamentals, "validate_fundamentals"),
        (sched._job_enrich_securities_nightly, "enrich_securities"),
        (sched._job_recompute_composite_ranking, "recompute_composite_ranking"),
        (sched._job_auto_confirm_corroborated, "auto_confirm_corroborated_fundamentals"),
    ],
)
def test_nightly_job_enqueues_its_tracked_runner(monkeypatch, job_fn, job_key):
    calls = []
    monkeypatch.setattr(sched, "enqueue", lambda db, key, trigger: calls.append((key, trigger)))

    job_fn()

    assert calls == [(job_key, "scheduled")]


@pytest.mark.parametrize(
    "job_fn, job_key",
    [
        (sched._job_cbsl_indicators, "capture_macro"),
        (sched._job_eod_snapshot, "capture_prices"),
    ],
)
def test_a_conflict_is_swallowed_not_raised(monkeypatch, job_fn, job_key):
    """A cron tick that lands while the same job is already queued or
    running (e.g. a human clicked "Run Capture" moments before midnight)
    must not blow up the scheduler thread — it logs and returns."""
    def _raise(db, key, trigger):
        raise sched.JobConflict(key)

    monkeypatch.setattr(sched, "enqueue", _raise)

    job_fn()  # must not raise
