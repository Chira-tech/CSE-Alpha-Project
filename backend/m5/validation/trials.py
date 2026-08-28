"""Task 6.1 (brief §6.1) — the append-only `m5.trials` registry:
`mechanism_text` >= 200 chars enforced at the DATABASE level (a CHECK
constraint, not a UI nicety — deliberate friction), `result_json`
writable exactly once, update/delete on a completed trial a silent
no-op via a real Postgres RULE. This project's SQLite dev database has
no `CREATE RULE` equivalent — see `m5.db`'s own docstring for the same
Postgres-vs-SQLite gap already named for the schema/role isolation; the
SQLite version of this table will need the same immutability enforced
in application code instead (a real, disclosed weaker guarantee in dev
than production gets, not silently glossed over). Not yet implemented."""
