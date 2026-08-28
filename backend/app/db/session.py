from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# REAL BUG, FOUND LIVE (23 Aug 2026), THE ACTUAL ROOT CAUSE of a much
# worse symptom than the WAL-mode fix below alone explains: opening the
# real app fresh fires ~7 concurrent requests from the Today screen
# alone (jobs/status, market x2, data-health, spread, portfolio, and
# opportunities — the last two genuinely expensive, ~15-20s CPU-bound
# passes each holding their DB session open the whole time), and
# SQLAlchemy's own DEFAULT connection pool for the engine below is only
# 5 base + 10 overflow = 15 connections TOTAL, process-wide. Once every
# slot is checked out by requests that are simply slow (not deadlocked,
# not leaking), any NEW request — including a fast, otherwise-fine one
# like `GET /securities` — queues for a free slot and only fails after
# SQLAlchemy's own default 30s pool-checkout timeout:
# `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10
# reached, connection timed out, timeout 30.00` — caught live in
# `uvicorn.log` while diagnosing why a freshly-loaded Companies screen
# never rendered in a real browser session, no matter how long the page
# was given to settle. SQLite connections are cheap to open (no real
# server-side connection cost the way Postgres has), so there is no
# real reason to cap this low for the sqlite dialect specifically —
# raised well above what this app's own worst observed concurrent-
# request count needs. Postgres keeps SQLAlchemy's own sane default
# (a real server has a real reason to cap pooled connections).
_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    **({"pool_size": 30, "max_overflow": 60} if _is_sqlite else {}),
)

# REAL BUG, FOUND LIVE (23 Aug 2026): dev-mode SQLite (README.md's own
# supported `DATABASE_URL=sqlite+pysqlite:///./devdb.sqlite`) defaults to
# SQLite's rollback-journal mode, which takes a database-wide lock during
# any write's commit and can make even a pure-read request queue behind
# it. Confirmed directly: `GET /securities` (~3.4s calling `list_
# securities()` in-process with nothing else running) measured at
# 35-50s over real HTTP with this app's own background job scheduler and
# a few browser tabs concurrently active — reproducible, not a one-off,
# and traced to `PRAGMA journal_mode` reading `delete` (the SQLite
# default) rather than `wal`. WAL mode lets readers run concurrently
# with a writer instead of queuing behind it, which is exactly this
# workload's shape (many short reads, occasional writes from ingestion
# jobs and user confirmations) — the standard fix for this SQLite usage
# pattern. A no-op for Postgres (this event only fires for the sqlite
# dialect), so it's safe to leave in for every environment.
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
