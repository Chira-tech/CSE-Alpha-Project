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
def _clear_opportunity_ranking_cache():
    """R1: `app.domain.opportunity_ranking_view.opportunity_ranking_for`
    caches its own real, expensive result in a module-level dict shared
    across the whole process — exactly right for one real dev server,
    exactly wrong left unguarded across a test suite, where two tests
    seeding the same `as_of` date into two different in-memory databases
    would otherwise share a stale cache entry. Caught live: this fixture
    exists because tests genuinely failed without it, not on suspicion."""
    from app.domain.opportunity_ranking_view import clear_cache

    clear_cache()
    yield
    clear_cache()


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
