"""
The M5 database engine. NEVER imports `app.db`, `app.models`, or any
other application write path — this is what `tests/isolation/test_m5_
isolation.py::test_m5_never_imports_app_write_paths` enforces by static
analysis on every module under this package, this one included.

WHY A SEPARATE SQLITE FILE, NOT THE BRIEF'S POSTGRES SCHEMA/ROLE SETUP
(§1.1): that SQL — `CREATE SCHEMA m5`, `CREATE ROLE m5_reader/m5_writer/
m5_service` with scoped `GRANT`/`REVOKE` — is real and correct for this
project's PRODUCTION target, but this project's actual dev database is
SQLite (see the repo root README's own "A note on SQLite vs PostgreSQL"
section) — deliberately, so the app is runnable on a clean machine with
nothing installed. SQLite has no schemas, no roles, no GRANT/REVOKE at
all, so that SQL cannot run against `devdb.sqlite` and was never going
to. The brief's own isolation GUARANTEE — M5 physically cannot write to
an application table even if its own code tried to — has a direct SQLite
equivalent that is, if anything, a STRONGER guarantee than a Postgres
schema+role: a completely separate `.sqlite` FILE. `m5_engine` below
never opens `devdb.sqlite` under any configuration; there is no
connection string that could point it there by accident, because
`M5Settings.database_url`'s default is a different filename entirely and
nothing in this module ever reads `app.config.settings.database_url`.

The brief's original Postgres role/schema SQL is kept, verbatim, at
`m5/migrations/pg_roles_reference.sql` — apply it when this module
actually moves onto the shared production Postgres instance; nothing in
this codebase runs it automatically today.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from m5.config import m5_settings

# `check_same_thread=False`: same reasoning as `app.db.session`'s own
# SQLite engine tuning (see that module's docstring) — a request handled
# by FastAPI's own worker thread is a different thread from the one that
# opened the connection under SQLAlchemy's default pooling.
_connect_args = {"check_same_thread": False} if m5_settings.database_url.startswith("sqlite") else {}

m5_engine = create_engine(m5_settings.database_url, connect_args=_connect_args)

M5SessionLocal = sessionmaker(bind=m5_engine, autoflush=False, autocommit=False)


class M5Base(DeclarativeBase):
    """M5's OWN declarative base — deliberately not `app.db.base.Base`.
    Even once this points at a shared Postgres instance in production
    (schema-qualified, `m5.` prefix), keeping a separate metadata object
    means an M5 model can never accidentally register into the same
    `MetaData` the application's own `alembic` migrations manage, and
    `alembic upgrade head` against the app's own migration chain can
    never see, and never touch, an M5 table."""


def get_m5_db() -> Session:
    """FastAPI dependency, mirroring `app.db.session.get_db`'s own shape
    — kept separate rather than imported, per this module's own
    docstring (`m5/` never imports `app.db`)."""
    db = M5SessionLocal()
    try:
        yield db
    finally:
        db.close()
