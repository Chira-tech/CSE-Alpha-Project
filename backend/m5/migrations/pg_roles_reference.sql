-- Reference only — NOT run automatically by anything in this codebase.
--
-- This is the brief's own §1.1 isolation SQL (docs/CLAUDE_CODE_BRIEF_M5.md),
-- preserved verbatim for when M5 moves off this project's SQLite dev
-- database (m5.sqlite, see m5/db.py's own docstring for why that — not
-- this — is what actually runs today) onto the shared production
-- Postgres instance. Apply by hand (or via a real Postgres-only
-- migration tool) at that point; SQLite has no schemas, roles, or
-- GRANT/REVOKE, so this cannot run against devdb.sqlite and was never
-- meant to.

CREATE SCHEMA IF NOT EXISTS m5;

CREATE ROLE m5_reader NOLOGIN;
GRANT USAGE ON SCHEMA public TO m5_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO m5_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO m5_reader;
-- explicitly NO insert/update/delete on public

CREATE ROLE m5_writer NOLOGIN;
GRANT ALL ON SCHEMA m5 TO m5_writer;

CREATE ROLE m5_service LOGIN PASSWORD :'m5_pw';
GRANT m5_reader, m5_writer TO m5_service;

ALTER ROLE m5_service SET statement_timeout = '30s';
ALTER ROLE m5_service SET lock_timeout = '5s';

-- The M5 service connects ONLY as m5_service, via a separate M5_DATABASE_URL
-- (see m5/config.py) — never the application's own primary connection string.
