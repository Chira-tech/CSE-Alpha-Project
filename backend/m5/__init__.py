"""
M5 — Convergence Engine & Playbook System.

See `docs/CLAUDE_CODE_BRIEF_M5.md` §0 for the prime directive this whole
package exists to satisfy: M5 is strictly additive. It never writes to
an existing table, never imports the main application's DB session or
ORM models, and never modifies a shared frontend component. Every
module under this package is self-contained; `m5.db` opens its OWN
connection (a separate SQLite file in dev — see that module's own
docstring for why the brief's Postgres role/schema SQL doesn't apply to
this project's actual dev database, and where the Postgres version is
kept for when this moves to production).

This package is currently isolation-scaffold only (Task 1 of the brief).
Every submodule below Task 1 (panel/, states/, baserates/, playbooks/,
validation/, shadow/) is a structural stub — the real directory layout
the later tasks will fill in, not yet containing any real logic. See
each module's own docstring for which task builds it.
"""
