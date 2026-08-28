"""
M5-only settings. Reads `M5_*` env vars exclusively — this is a SEPARATE
`pydantic_settings.BaseSettings` instance from `app.config.settings`,
deliberately: M5's own config must never be reachable by, or entangled
with, the main application's config object (brief §0 rule 3's spirit
extended to config, not just components).

The ONE exception, and it is on the main application's side, not this
one: `app/config.py` gained a single `m5_enabled: bool = False` field so
`app/main.py`'s own allowlisted guard line (brief §1.3) — literally
written as `if settings.M5_ENABLED:` — has something real to read.
`pydantic_settings.BaseSettings` with `extra="ignore"` (the app's own
config, see `app/config.py`'s `model_config`) silently drops any env var
without a matching declared field, so that guard would otherwise always
evaluate falsy regardless of the real `M5_ENABLED` env var. This is a
disclosed, minimal deviation from brief §1.3's literal "ONE file, ONE
line" — flagged here rather than silently done, per the brief's own
"if you believe an existing file must change, STOP and raise it" rule.
It grants M5 no write access to anything and changes no existing
behaviour; it's a boolean toggle the app's own entrypoint reads, nothing
in `m5/` depends on it.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class M5Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="m5_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    enabled: bool = False
    """Mirrors `app.config.settings.m5_enabled` (see this module's own
    docstring) — kept here too so every m5/ module can gate its own
    behaviour off the SAME env var without importing `app.config`."""

    database_url: str = "sqlite+pysqlite:///./m5.sqlite"
    """A COMPLETELY SEPARATE database from the main application's
    `database_url` (`app.config.settings.database_url`) — see `m5.db`'s
    own docstring for why a separate SQLite file, not a Postgres schema
    with role-based grants, is this project's actual dev-environment
    isolation mechanism, and where the brief's original Postgres SQL
    (§1.1) is kept for the eventual production move."""

    holdout_after: str | None = None
    """§0.5 D3 — `M5_HOLDOUT_AFTER`: the date the backtester must refuse
    to read past. `None` (unset) until Task 6/9 actually need it; no
    validation logic reads this yet at the Task 1 (isolation scaffold)
    stage."""

    max_modifiers: int = 1
    """§0.5 D1(c): capped at 1 until panel depth reaches the ~8-year
    equivalent threshold, then auto-relaxes to 2. The relaxation logic
    itself belongs to Task 4 (state classifier); this is just the
    config default Task 4 will read."""


m5_settings = M5Settings()
