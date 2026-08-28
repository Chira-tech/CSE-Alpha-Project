"""
Mounted at `/api/v5` by `app/main.py`'s own allowlisted guard line
(brief §1.3) — ONLY when `settings.m5_enabled` is true. With the flag
off, this module is never imported at all and `/api/v5/*` 404s exactly
as if M5 didn't exist (`app.main`'s own `import` sits inside the `if`).

Task 1 (isolation scaffold) only — a single real endpoint proving the
wiring works end to end, not yet the real `/api/v5` surface (panel,
base rates, playbooks, trials) later tasks will add.
"""
from __future__ import annotations

from fastapi import APIRouter

from m5.config import m5_settings

router = APIRouter(tags=["m5"])


@router.get("/status")
def status() -> dict:
    """Proves the module is mounted and reading its OWN config — not a
    real M5 feature endpoint, just Task 1's own acceptance signal."""
    return {"m5_enabled": m5_settings.enabled, "database_url": m5_settings.database_url}
