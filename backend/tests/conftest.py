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

from app import models  # noqa: F401 — populates Base.metadata
from app.db.base import Base


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
