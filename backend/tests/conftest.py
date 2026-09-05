"""
Test fixtures. DB-touching tests use an in-memory SQLite engine created
directly from `app.db.base.Base.metadata` — independent of
`app.config.settings.database_url` (which points at Postgres for real use).
This is fine for correctness tests of query logic; it does NOT exercise the
TimescaleDB hypertable behaviour created in the alembic migration, which
needs a real Postgres+Timescale instance (see README "Getting started").
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — populates Base.metadata
from app.db.base import Base


@pytest.fixture(autouse=True)
def _no_in_process_job_execution():
    """`POST /jobs/{job}/run` normally executes the job in a daemon
    thread (so "Run Capture" works with just uvicorn) — off in tests, so
    triggering a job asserts the queued row without spawning a real
    ingestion sweep against a URL that isn't reachable here anyway."""
    from app.config import settings

    prev = settings.execute_manual_jobs_in_process
    settings.execute_manual_jobs_in_process = False
    yield
    settings.execute_manual_jobs_in_process = prev


@pytest.fixture(autouse=True)
def _clear_process_level_caches():
    """Several domain views cache a real, expensive, market-wide result in
    a module-level dict shared across the whole process — exactly right for
    one real dev server, exactly wrong left unguarded across a test suite,
    where two tests seeding the same `as_of` date into two different
    in-memory databases would otherwise share a stale cache entry. Caught
    live for `opportunity_ranking_view`; the same hazard applies to every
    cache added since, so they are all reset here, before and after each
    test."""
    from app.domain.composite_ranking_view import clear_cache as clear_composite_ranking
    from app.domain.fundamentals_view import clear_cache as clear_bulk_line_items
    from app.domain.liquidity_view import clear_cache as clear_liquidity
    from app.domain.macro_engine_view import clear_cache as clear_regime
    from app.domain.opportunity_ranking_view import clear_cache as clear_opportunities
    from app.domain.sector_percentiles_view import clear_cache as clear_sector_pct
    from app.domain.sector_sensitivity_view import clear_cache as clear_sector_sens
    from app.domain.valuation_view import clear_peer_multiples_cache

    clears = (
        clear_opportunities, clear_composite_ranking, clear_liquidity, clear_regime,
        clear_sector_pct, clear_sector_sens, clear_bulk_line_items, clear_peer_multiples_cache,
    )
    for clear in clears:
        clear()
    yield
    for clear in clears:
        clear()


@pytest.fixture()
def db_session():
    # StaticPool + check_same_thread=False: SQLAlchemy's default pooling
    # for sqlite ":memory:" keys connections by thread, so a request
    # handled by FastAPI's TestClient (which runs the endpoint in an
    # anyio worker thread, not the test's own thread) would otherwise get
    # a *different*, empty in-memory database than the one this fixture
    # just populated. StaticPool forces a single shared connection
    # regardless of thread.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient wired to the same in-memory sqlite session as
    `db_session`, so a test can set up data via the ORM and assert on it
    via the API in the same test."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
