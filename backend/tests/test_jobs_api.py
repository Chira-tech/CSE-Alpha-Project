"""
P1.1 (`docs/CLAUDE_CODE_BRIEF.md`, TASK 1.1) — the "Run Capture" API:
`POST /jobs/{job}/run`, `GET /jobs/status`, `POST /jobs/{run_id}/cancel`,
`GET /jobs/{run_id}/stream`. Named acceptance tests from the brief itself
are called out below where they apply directly.

The stream endpoint's own generator opens a fresh `SessionLocal()` per
poll rather than reusing the request's injected session (see that
route's own docstring for why) — every test touching it monkeypatches
`app.api.routes.jobs.SessionLocal` to the same in-memory engine
`db_session` uses, or its reads would silently miss everything the test
just seeded.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest
from freezegun import freeze_time
from sqlalchemy.orm import sessionmaker

import app.api.routes.jobs as jobs_route
from app.models.job_run import JobRun


@pytest.fixture(autouse=True)
def _stream_uses_test_db(db_session, monkeypatch):
    monkeypatch.setattr(jobs_route, "SessionLocal", sessionmaker(bind=db_session.get_bind()))


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


# --- POST /jobs/{job}/run -------------------------------------------------


def test_manual_run_returns_202_and_run_id(client):
    """test_manual_run_returns_202_and_run_id"""
    response = client.post("/jobs/capture_market/run")
    assert response.status_code == 202
    body = response.json()
    assert body["id"] > 0
    assert body["job"] == "capture_market"
    assert body["status"] == "queued"
    assert body["trigger"] == "manual"


def test_unknown_job_returns_404(client):
    response = client.post("/jobs/not_a_real_job/run")
    assert response.status_code == 404


def test_concurrent_run_returns_409(client, db_session):
    """test_concurrent_run_returns_409 — second POST while running is rejected."""
    _seed_run(db_session, job="capture_market", status="running")
    response = client.post("/jobs/capture_market/run")
    assert response.status_code == 409


@freeze_time("2026-08-19 10:00:00")
def test_cooldown_enforced(client, db_session):
    """test_cooldown_enforced — second manual run within 15 min returns
    429 with retry_after."""
    _seed_run(
        db_session,
        job="capture_market",
        status="success",
        created_at=dt.datetime(2026, 8, 19, 9, 55, tzinfo=dt.timezone.utc),
    )
    response = client.post("/jobs/capture_market/run")
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["retry_after"] == pytest.approx(600, abs=1)


def test_capture_all_is_a_triggerable_job(client):
    response = client.post("/jobs/capture_all/run")
    assert response.status_code == 202
    assert response.json()["job"] == "capture_all"


# --- GET /jobs/status ------------------------------------------------------


def test_status_lists_every_registered_job_even_with_no_history(client):
    from app.jobs.registry import JOBS

    body = client.get("/jobs/status").json()
    reported = {entry["job"] for entry in body["jobs"]}
    assert reported == set(JOBS)
    for entry in body["jobs"]:
        assert entry["last_run"] is None


def test_status_reports_the_most_recent_run_per_job(client, db_session):
    _seed_run(
        db_session, job="capture_market", status="success", rows_written=42,
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    newer = _seed_run(
        db_session, job="capture_market", status="failed", error="boom",
        created_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
    )
    body = client.get("/jobs/status").json()
    entry = next(e for e in body["jobs"] if e["job"] == "capture_market")
    assert entry["last_run"]["id"] == newer.id
    assert entry["last_run"]["status"] == "failed"
    assert entry["last_run"]["error"] == "boom"


def test_timestamps_are_serialized_as_utc_even_when_sqlite_stripped_tzinfo(client, db_session):
    """Real bug, caught live in the browser: SQLite round-trips a
    `DateTime(timezone=True)` column back as NAIVE. Serialised as-is,
    the frontend's `new Date(...)` parses the offset-less string as
    LOCAL time — on a host 8 hours ahead of UTC, a job that had just
    finished showed as "8h ago" instead of "just now". Every timestamp
    in this table is always written as UTC, so this asserts the API
    response always carries an explicit UTC offset regardless of what
    the DB layer handed back."""
    run = _seed_run(db_session, status="success")
    db_session.refresh(run)
    assert run.created_at.tzinfo is None  # confirms this test exercises the real sqlite behaviour

    body = client.get("/jobs/status").json()
    entry = next(e for e in body["jobs"] if e["job"] == run.job)
    created_at = entry["last_run"]["created_at"]
    assert created_at.endswith("Z") or created_at[-6] in "+-"


def test_status_reports_a_real_next_scheduled_time_for_a_cron_backed_job(client):
    """capture_prices mirrors app.jobs.scheduler's real eod_snapshot cron
    (15:00 Colombo, Mon-Fri) — this is not a fabricated estimate."""
    body = client.get("/jobs/status").json()
    entry = next(e for e in body["jobs"] if e["job"] == "capture_prices")
    assert entry["next_scheduled_at"] is not None


@pytest.mark.parametrize("job", ["enrich_securities", "recompute", "capture_all"])
def test_status_reports_no_next_scheduled_time_for_jobs_with_no_cron_equivalent(client, job):
    body = client.get("/jobs/status").json()
    entry = next(e for e in body["jobs"] if e["job"] == job)
    assert entry["next_scheduled_at"] is None


# --- POST /jobs/{run_id}/cancel --------------------------------------------


def test_cancel_unknown_run_returns_404(client):
    assert client.post("/jobs/999999/cancel").status_code == 404


def test_cancel_a_queued_run_cancels_it_immediately(client, db_session):
    run = _seed_run(db_session, status="queued")
    response = client.post(f"/jobs/{run.id}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancel_requested"] is True


def test_cancel_a_running_run_only_sets_the_flag(client, db_session):
    """Cooperative cancel — the runner's own loop is what actually stops;
    the API can't interrupt a job mid-flight."""
    run = _seed_run(db_session, status="running")
    response = client.post(f"/jobs/{run.id}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["cancel_requested"] is True


@pytest.mark.parametrize("status", ["success", "failed", "cancelled"])
def test_cancel_an_already_finished_run_returns_409(client, db_session, status):
    run = _seed_run(db_session, status=status)
    response = client.post(f"/jobs/{run.id}/cancel")
    assert response.status_code == 409


# --- GET /jobs/{run_id}/stream ----------------------------------------------


def test_stream_returns_404_for_an_unknown_run(client):
    assert client.get("/jobs/999999/stream").status_code == 404


def test_stream_reports_the_current_state_of_a_finished_run(client, db_session):
    run = _seed_run(db_session, status="success", rows_written=286, progress_pct=Decimal(100))
    response = client.get(f"/jobs/{run.id}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    # A terminal-status run's stream ends after exactly one event — no
    # `asyncio.sleep`, so this never blocks the test suite.
    lines = [l for l in response.text.strip().splitlines() if l.startswith("data: ")]
    assert len(lines) == 1
    payload = json.loads(lines[0].removeprefix("data: "))
    assert payload["status"] == "success"
    assert payload["rows_written"] == 286
