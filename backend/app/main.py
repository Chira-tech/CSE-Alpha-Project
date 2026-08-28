from __future__ import annotations

import logging
import sys

# Same fix as `app/worker.py`'s own top-of-file comment explains in
# full: this process's stdout/stderr default to the Windows console
# code page (cp1252), not UTF-8, even redirected to a log file — and
# this codebase's own real log/exception messages routinely contain
# characters outside it. Reconfigured before any logging happens so a
# genuine Unicode character in a request log or exception traceback
# degrades to a substitution glyph instead of taking the whole API
# process down.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    composite_score,
    corporate_actions,
    data_health,
    decisions,
    export,
    fundamentals,
    health,
    jobs,
    market,
    national_projects,
    opportunities,
    portfolio,
    securities,
    valuation,
)
from app.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="CSE Alpha Engine",
    description=(
        "Decision-support API for CSE equities. Deterministic code computes; "
        "AI explains. This service never places an order and never exposes a "
        "single-verdict recommendation endpoint — see Design Law 6, Master "
        "Spec §4."
    ),
    version="0.1.0-phase1",
)

# Confirm-queue frontend (frontend/) runs on the Vite dev server during
# development. This is an internal review tool, not a public API — origins
# are limited to local dev ports, never a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
    # R1 T3.1/T3.2: Content-Disposition isn't one of the handful of
    # "simple response headers" a cross-origin fetch can read by default —
    # without this, the frontend's own export download silently falls
    # back to a generic filename instead of the server's real one.
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(securities.router)
app.include_router(market.router)
app.include_router(corporate_actions.router)
app.include_router(fundamentals.router)
app.include_router(data_health.router)
app.include_router(valuation.router)
app.include_router(national_projects.router)
app.include_router(portfolio.router)
app.include_router(opportunities.router)
app.include_router(decisions.router)
app.include_router(jobs.router)
app.include_router(composite_score.router)
app.include_router(export.router)

# M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md
# §1.3): the ONE allowlisted edit to this file, guarded so the app is
# byte-identical in behaviour with the flag off (§0 rule 6) — with
# `m5_enabled` false, `m5.api.router` is never even imported, and
# `/api/v5/*` 404s exactly as if M5 didn't exist.
if settings.m5_enabled:
    from m5.api.router import router as m5_router

    app.include_router(m5_router, prefix="/api/v5")
