"""
P1.1's execution engine — `app.jobs.runner`. Covers the concurrency
guard, the manual cooldown, and the queued -> running -> terminal
lifecycle, none of which had any test coverage before this file (the
WIP commit that introduced these modules said so explicitly).

Every test that calls `execute()`/`poll_and_run_one()` monkeypatches
`app.jobs.runner.SessionLocal` to the SAME in-memory engine `db_session`
uses — those two functions deliberately open their own fresh session
(see the module's own docstring for why: they may run on a scheduler
thread with a lifetime longer than any single request), so without this
they would read/write a completely different, unrelated database from
the one each test seeds.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from freezegun import freeze_time
from sqlalchemy.orm import sessionmaker

from app.jobs import runner
from app.models.job_run import JobRun


@pytest.fixture(autouse=True)
def _runner_uses_test_db(db_session, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", sessionmaker(bind=db_session.get_bind()))


def _seed_run(db, *, job="capture_market", trigger="manual", status="queued", created_at=None, **overrides):
    defaults = dict(
        job=job,
        trigger=trigger,
        status=status,
        progress_pct=Decimal(0),
        rows_written=0,
        cancel_requested=False,
        created_at=created_at or dt.datetime.now(dt.timezone.utc),
    )
    defaults.update(overrides)
    run = JobRun(**defaults)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# --- recover_orphaned_runs ---------------------------------------------
# R1: a worker process that dies mid-job (see `app.worker`'s own
# top-of-file comment for the real crash this closes — a Unicode
# character in a log message on this project's real Windows dev
# environment, whose stdout defaults to cp1252, killed the process
# outright) leaves its `JobRun` stuck `running` forever, since nothing
# was left alive to ever mark it terminal — which then blocks every
# future `enqueue` of that same job via the concurrency guard above,
# permanently, until something notices and fixes the row by hand.


def test_recover_orphaned_runs_marks_stale_running_and_queued_rows_failed(db_session):
    running = _seed_run(db_session, job="recompute", status="running", started_at=dt.datetime.now(dt.timezone.utc))
    queued = _seed_run(db_session, job="capture_market", status="queued")

    recovered = runner.recover_orphaned_runs(db_session)

    assert recovered == 2
    db_session.refresh(running)
    db_session.refresh(queued)
    assert running.status == "failed"
    assert running.finished_at is not None
    assert "Interrupted" in running.error
    assert queued.status == "failed"
    assert queued.finished_at is not None


def test_recover_orphaned_runs_leaves_terminal_rows_untouched(db_session):
    done = _seed_run(db_session, job="capture_market", status="success")

    recovered = runner.recover_orphaned_runs(db_session)

    assert recovered == 0
    db_session.refresh(done)
    assert done.status == "success"


@freeze_time("2026-08-19 10:00:00")
def test_recover_orphaned_runs_unblocks_a_real_re_enqueue(db_session):
    """The actual real-world payoff: after recovery, the same job can be
    triggered again instead of 409ing forever. `created_at` set outside
    the 15-minute manual cooldown so this test isolates the concurrency
    guard specifically, not the unrelated cooldown check."""
    _seed_run(
        db_session, job="recompute", status="running",
        created_at=dt.datetime(2026, 8, 19, 9, 44, 59, tzinfo=dt.timezone.utc),
    )

    runner.recover_orphaned_runs(db_session)
    run = runner.enqueue(db_session, "recompute", trigger="manual")

    assert run.status == "queued"


# --- enqueue ----------------------------------------------------------


def test_enqueue_unknown_job_raises_keyerror(db_session):
    with pytest.raises(KeyError):
        runner.enqueue(db_session, "not_a_real_job")


def test_enqueue_creates_a_queued_row(db_session):
    run = runner.enqueue(db_session, "capture_market", trigger="manual")
    assert run.id is not None
    assert run.job == "capture_market"
    assert run.trigger == "manual"
    assert run.status == "queued"
    assert run.progress_pct == 0
    assert run.cancel_requested is False


@pytest.mark.parametrize("open_status", ["queued", "running"])
def test_enqueue_raises_conflict_when_the_same_job_is_already_open(db_session, open_status):
    _seed_run(db_session, job="capture_market", status=open_status)
    with pytest.raises(runner.JobConflict):
        runner.enqueue(db_session, "capture_market", trigger="manual")


def test_enqueue_does_not_conflict_across_different_jobs(db_session):
    _seed_run(db_session, job="capture_market", status="running")
    # Different job key — must not be blocked by the running capture_market row.
    run = runner.enqueue(db_session, "capture_macro", trigger="manual")
    assert run.status == "queued"


@freeze_time("2026-08-19 10:00:00")
def test_enqueue_raises_cooldown_within_15_minutes_of_the_last_manual_run(db_session):
    _seed_run(
        db_session,
        job="capture_market",
        status="success",
        created_at=dt.datetime(2026, 8, 19, 9, 50, tzinfo=dt.timezone.utc),
    )
    with pytest.raises(runner.JobCooldown) as excinfo:
        runner.enqueue(db_session, "capture_market", trigger="manual")
    # 10 minutes elapsed of the 15-minute window -> 5 minutes remaining.
    assert 290 <= excinfo.value.retry_after_seconds <= 300


@freeze_time("2026-08-19 10:00:00")
def test_enqueue_allowed_once_the_cooldown_has_elapsed(db_session):
    _seed_run(
        db_session,
        job="capture_market",
        status="success",
        created_at=dt.datetime(2026, 8, 19, 9, 44, 59, tzinfo=dt.timezone.utc),
    )
    run = runner.enqueue(db_session, "capture_market", trigger="manual")
    assert run.status == "queued"


@freeze_time("2026-08-19 10:00:00")
def test_scheduled_trigger_bypasses_the_manual_cooldown(db_session):
    """§52's own cron jobs must never be blocked by a human having
    clicked Run Capture a few minutes earlier — the cooldown exists to
    protect the API from a human hammering the button, not to throttle
    the schedule itself."""
    _seed_run(
        db_session,
        job="capture_market",
        status="success",
        created_at=dt.datetime(2026, 8, 19, 9, 59, tzinfo=dt.timezone.utc),
    )
    run = runner.enqueue(db_session, "capture_market", trigger="scheduled")
    assert run.status == "queued"


def test_cooldown_is_scoped_per_job(db_session):
    _seed_run(db_session, job="capture_market", status="success")
    # A different job's own manual run has never happened — no cooldown.
    run = runner.enqueue(db_session, "capture_macro", trigger="manual")
    assert run.status == "queued"


# --- execute (leaf jobs) -----------------------------------------------


def test_execute_runs_a_leaf_job_and_marks_it_successful(db_session, monkeypatch):
    run = _seed_run(db_session, job="capture_market")
    monkeypatch.setitem(runner._RUNNERS, "capture_market", lambda db, r: 7)

    runner.execute(run.id)

    db_session.refresh(run)
    assert run.status == "success"
    assert run.rows_written == 7
    assert run.progress_pct == 100
    assert run.started_at is not None
    assert run.finished_at is not None


def test_execute_marks_failed_on_an_unhandled_exception(db_session, monkeypatch):
    run = _seed_run(db_session, job="capture_market")

    def _boom(db, r):
        raise RuntimeError("upstream feed returned garbage")

    monkeypatch.setitem(runner._RUNNERS, "capture_market", _boom)

    runner.execute(run.id)

    db_session.refresh(run)
    assert run.status == "failed"
    assert "upstream feed returned garbage" in run.error


def test_execute_reports_cancelled_when_the_job_honoured_a_cancel_request(db_session, monkeypatch):
    """Mirrors what `_run_capture_corporate_actions`/`_run_enrich_
    securities` do for real: notice `cancel_requested` mid-sweep, stop
    early, and return whatever partial row count they'd written so far."""

    def _partial_then_cancelled(db, r):
        db.refresh(r)
        r.cancel_requested = True
        db.commit()
        return 3

    run = _seed_run(db_session, job="capture_market")
    monkeypatch.setitem(runner._RUNNERS, "capture_market", _partial_then_cancelled)

    runner.execute(run.id)

    db_session.refresh(run)
    assert run.status == "cancelled"
    assert run.rows_written == 3


def test_execute_on_a_missing_run_id_does_not_raise(db_session):
    runner.execute(999999)  # no row with this id — logs and returns, no crash


# --- execute (capture_all) ---------------------------------------------


def test_execute_capture_all_runs_every_sub_job_in_order(db_session, monkeypatch):
    calls: list[str] = []

    def _make_stub(name, rows):
        def _stub(db, r):
            calls.append(name)
            return rows

        return _stub

    for name in runner.job_definition("capture_all").sub_jobs:
        monkeypatch.setitem(runner._RUNNERS, name, _make_stub(name, 1))

    run = _seed_run(db_session, job="capture_all")
    runner.execute(run.id)

    db_session.refresh(run)
    assert calls == list(runner.job_definition("capture_all").sub_jobs)
    assert run.status == "success"
    assert run.rows_written == len(calls)


def test_execute_capture_all_stops_at_the_first_sub_job_that_raises(db_session, monkeypatch):
    calls: list[str] = []
    sub_jobs = runner.job_definition("capture_all").sub_jobs

    def _ok(db, r):
        calls.append("ok")
        return 1

    def _boom(db, r):
        raise RuntimeError("second sub-job failed")

    monkeypatch.setitem(runner._RUNNERS, sub_jobs[0], _ok)
    monkeypatch.setitem(runner._RUNNERS, sub_jobs[1], _boom)

    run = _seed_run(db_session, job="capture_all")
    runner.execute(run.id)

    db_session.refresh(run)
    assert calls == ["ok"]  # never reached the third sub-job
    assert run.status == "failed"
    assert "second sub-job failed" in run.error


# --- poll_and_run_one ----------------------------------------------------


def test_poll_and_run_one_returns_false_on_an_empty_queue(db_session):
    assert runner.poll_and_run_one() is False


def test_poll_and_run_one_picks_the_oldest_queued_run(db_session, monkeypatch):
    older = _seed_run(
        db_session, job="capture_market",
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    newer = _seed_run(
        db_session, job="capture_macro",
        created_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
    )
    monkeypatch.setitem(runner._RUNNERS, "capture_market", lambda db, r: 1)
    monkeypatch.setitem(runner._RUNNERS, "capture_macro", lambda db, r: 1)

    picked_up = runner.poll_and_run_one()

    assert picked_up is True
    db_session.refresh(older)
    db_session.refresh(newer)
    assert older.status == "success"
    assert newer.status == "queued"  # not picked up yet — one job per poll call


def test_poll_and_run_one_skips_a_job_whose_key_is_already_running(db_session, monkeypatch):
    """The concurrency guard's second backstop (`enqueue` already checked
    once at insert time) — `poll_and_run_one` re-checks immediately
    before executing, per the module's own docstring."""
    _seed_run(db_session, job="capture_market", status="running")
    queued_same_job = _seed_run(
        db_session, job="capture_market",
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    other_job = _seed_run(
        db_session, job="capture_macro",
        created_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
    )
    monkeypatch.setitem(runner._RUNNERS, "capture_macro", lambda db, r: 1)

    picked_up = runner.poll_and_run_one()

    assert picked_up is True
    db_session.refresh(other_job)
    db_session.refresh(queued_same_job)
    assert other_job.status == "success"
    assert queued_same_job.status == "queued"  # left alone — its own job is still running


# --- universe_integrity_checks ---------------------------------------------


def test_universe_integrity_checks_job_is_wired_and_runs(db_session):
    """docs/CSE_Universe_Integrity_Rollout.md Phase 2 — the manual trigger
    for the nightly universe-integrity sweep. Pins the _RUNNERS wiring and
    that a clean universe produces no alerts."""
    from app.models.securities import Security

    db_session.add(Security(ticker="COMB.N0000", name="COMB", instrument_type="ordinary"))
    db_session.commit()

    assert "universe_integrity_checks" in runner._RUNNERS
    run = _seed_run(db_session, job="universe_integrity_checks")
    assert runner._run_universe_integrity_checks(db_session, run) == 0
