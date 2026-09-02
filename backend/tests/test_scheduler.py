"""
Scheduler wiring — specifically that every job is anchored to the
exchange's clock.

This exists because of a real bug: `CronTrigger` resolves its timezone at
CONSTRUCTION, defaulting to the host's local zone, and passing a timezone
to the *scheduler* does not retro-fit a trigger built without one. On a
machine in Australia/Perth (+08:00) the "15:00 EOD snapshot" was
scheduling for 12:30 Colombo — two hours before the CSE's 14:30 close —
so the end-of-day job would have captured a mid-session price and stored
it as the closing price. Nothing else in the system would have flagged
that; the number would simply have been wrong.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from app.jobs.scheduler import MARKET_TZ, build_scheduler

# The 00:00 Colombo nightly batch — everything that is NOT price capture,
# staggered so a failure in one step is isolated, run every calendar day
# (a weekend-published filing / CBSL edition is picked up that night).
NIGHTLY_JOBS = {
    "eod_snapshot": (0, 0),
    "capture_market_internals": (0, 3),
    "nightly_reconciliation": (0, 6),
    "second_source_check": (0, 9),
    "market_cap_reconciliation": (0, 12),
    "universe_integrity_checks": (0, 15),
    "corporate_actions_scan": (0, 20),
    "financial_statement_scan": (0, 35),
    "cbsl_indicators": (0, 50),
    "enrich_securities": (1, 0),
    "auto_confirm_corroborated_fundamentals": (1, 10),
    "validate_fundamentals": (1, 20),
    "recompute_composite_ranking": (1, 30),
}

# Kept as the name the rest of the file references.
EXPECTED_JOBS = NIGHTLY_JOBS

# Deliberately NOT weekday-scheduled: it repairs gaps in a series that
# stays reconstructable for a year, so it wants a quiet slot rather than
# a trading-day one.
WEEKLY_JOBS = {
    "index_history_backfill": ("sat", 6, 0),
    "issuer_registry_refresh": ("sat", 6, 20),
    "sector_refresh": ("sat", 6, 40),
    "price_gap_repair": ("sat", 7, 0),
    "refresh_stale_fundamentals": ("sat", 7, 30),
}

# P1.1: the manual "Run Capture" queue poller — deliberately NOT weekday/
# hour-gated like every job above (a human can trigger a manual run any
# time), so it gets its own category rather than being forced into
# EXPECTED_JOBS's Colombo-cron shape.
INTERVAL_JOBS = {
    "manual_job_queue_poll": 5,
}

# Intraday price capture: every 20 minutes across the Colombo trading
# window, weekdays only. Its own category — a cron with a minute LIST and
# an hour RANGE, unlike the single-fire nightly jobs.
INTRADAY_PRICE_JOB = "intraday_price_snapshot"


@pytest.fixture()
def scheduler():
    s = build_scheduler()
    yield s
    if s.running:  # pragma: no cover - defensive
        s.shutdown(wait=False)


def test_market_tz_is_colombo_not_the_host_zone():
    assert MARKET_TZ == ZoneInfo("Asia/Colombo")


def test_all_expected_jobs_are_registered(scheduler):
    assert {job.id for job in scheduler.get_jobs()} == (
        set(NIGHTLY_JOBS) | set(WEEKLY_JOBS) | set(INTERVAL_JOBS) | {INTRADAY_PRICE_JOB}
    )


@pytest.mark.parametrize(("job_id", "seconds"), INTERVAL_JOBS.items())
def test_interval_jobs_fire_at_their_named_period(scheduler, job_id, seconds):
    from apscheduler.triggers.interval import IntervalTrigger

    job = scheduler.get_job(job_id)
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == seconds


def test_manual_job_queue_poll_allows_only_one_instance():
    """A manual sweep can take up to ~10 minutes (registry.py's own
    est_seconds); if a second 5s tick started a concurrent poll while one
    was still running, two workers could both call CseClient at once and
    break the >=2s pacing every other job in this system respects."""
    s = build_scheduler()
    try:
        job = s.get_job("manual_job_queue_poll")
        assert job.max_instances == 1
    finally:
        if s.running:  # pragma: no cover - defensive
            s.shutdown(wait=False)


@pytest.mark.parametrize(("job_id", "expected"), EXPECTED_JOBS.items())
def test_every_trigger_uses_colombo_time(scheduler, job_id, expected):
    """The assertion that would have caught the original bug: the
    trigger's own timezone, not just the scheduler's."""
    job = scheduler.get_job(job_id)
    assert job is not None
    assert job.trigger.timezone == ZoneInfo("Asia/Colombo"), (
        f"{job_id} is scheduled in {job.trigger.timezone}, not the exchange's timezone — "
        "on a host outside Sri Lanka this fires at the wrong point in the trading day"
    )


@pytest.mark.parametrize(("job_id", "expected"), EXPECTED_JOBS.items())
def test_trigger_fires_at_the_intended_colombo_hour(scheduler, job_id, expected):
    hour, minute = expected
    fields = {f.name: str(f) for f in scheduler.get_job(job_id).trigger.fields}
    assert fields["hour"] == str(hour)
    assert fields["minute"] == str(minute)


@pytest.mark.parametrize("job_id", list(NIGHTLY_JOBS))
def test_nightly_batch_runs_every_calendar_day(scheduler, job_id):
    """The 00:00 batch runs seven days a week (user directive, 2 Sep
    2026: "every calendar day at 00:00"). Every step it drives is
    idempotent, so a run on a day with no new session is a cheap no-op
    rather than a duplicate write, and a filing / CBSL edition / corporate
    action published over a weekend is picked up that night instead of
    waiting for Monday."""
    fields = {f.name: str(f) for f in scheduler.get_job(job_id).trigger.fields}
    assert fields["day_of_week"] == "*"


def test_intraday_price_job_fires_every_20_min_in_the_trading_window(scheduler):
    """Open 09:30, close 14:30 Colombo, weekdays. The cron is minute
    list 0,20,40 over hours 9-14 — the 09:00/09:20 pre-open ticks and the
    14:40 post-close tick are guarded no-ops in the job itself (it writes
    only when the feed's own timestamps say the session is today)."""
    job = scheduler.get_job(INTRADAY_PRICE_JOB)
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["minute"] == "0,20,40"
    assert fields["hour"] == "9-14"
    assert fields["day_of_week"] == "mon-fri"
    assert job.trigger.timezone == ZoneInfo("Asia/Colombo")
    assert job.max_instances == 1


@pytest.mark.parametrize(("job_id", "expected"), WEEKLY_JOBS.items())
def test_weekly_jobs_run_on_their_named_day_in_colombo_time(scheduler, job_id, expected):
    """Same timezone trap as the weekday jobs: a trigger built without an
    explicit tz would drift onto a different DAY, not just a different
    hour, on a host west of Colombo."""
    day, hour, minute = expected
    job = scheduler.get_job(job_id)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["day_of_week"] == day
    assert fields["hour"] == str(hour)
    assert fields["minute"] == str(minute)
    assert job.trigger.timezone.key == MARKET_TZ.key


def test_eod_snapshot_is_the_midnight_batchs_first_step(scheduler):
    """The definitive settled close is captured at 00:00 Colombo — nine-
    plus hours after the 14:30 close, so it is fully settled — and
    overwrites whatever the last intraday tick left for that date. The
    live in-session price is the `intraday_price_snapshot` job's job."""
    fields = {f.name: str(f) for f in scheduler.get_job("eod_snapshot").trigger.fields}
    assert (int(fields["hour"]), int(fields["minute"])) == (0, 0)


def test_reconciliation_runs_after_the_snapshot(scheduler):
    """§7's reconciliation compares stored adjustment factors against a
    recomputation from that day's prices — running it first would check
    yesterday's data and report a false pass."""
    eod = {f.name: str(f) for f in scheduler.get_job("eod_snapshot").trigger.fields}
    rec = {f.name: str(f) for f in scheduler.get_job("nightly_reconciliation").trigger.fields}
    eod_minutes = int(eod["hour"]) * 60 + int(eod["minute"])
    rec_minutes = int(rec["hour"]) * 60 + int(rec["minute"])
    assert rec_minutes > eod_minutes
