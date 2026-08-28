"""Task 2 (brief §2) — the nightly panel snapshot builder: one read-only
pass from the application's data into `m5.panel`, run after the existing
nightly batch completes. Not yet implemented — Task 1 (isolation
scaffold) only proves the module CAN exist without touching anything;
this file intentionally contains no logic yet.

WHEN THIS IS BUILT: it may read the application's tables (Fundamental,
PriceDaily, etc. — read-only) but must still never import `app.db`'s
session directly (brief §0 rule 1) — read via the m5_reader role in
Postgres, or, for this project's SQLite dev equivalent, a read-only
connection to the app's own `devdb.sqlite` file opened independently of
`app.db.session` (never sharing that module's engine/session objects).
"""
