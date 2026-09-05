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

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import (
    auth,
    composite_ranking,
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
from app.security import AuthGateMiddleware, SecurityHeadersMiddleware, auth_enabled

logging.basicConfig(level=settings.log_level)

logger = logging.getLogger("cse_alpha.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Optionally run `app.jobs.scheduler` inside the API process.

    Off by default (`settings.run_scheduler_in_process`): a production
    deployment keeps the API and the always-on `python -m app.worker`
    separate, for the reasons `app/worker.py`'s own docstring gives (the
    API must be restartable at will; the scheduler must not be, and
    `--reload` would double-fire every cron job). Turned on for a
    single-process box where nothing else runs the schedule — the intended
    use is one long-lived `uvicorn app.main:app` (NO `--reload`).
    """
    scheduler = None
    if settings.run_scheduler_in_process:
        from app.db.session import SessionLocal
        from app.jobs.runner import recover_orphaned_runs
        from app.jobs.scheduler import build_scheduler

        with SessionLocal() as _db:
            recovered = recover_orphaned_runs(_db)
        if recovered:
            logger.warning("recovered %d job run(s) orphaned by a previous exit", recovered)

        scheduler = build_scheduler()
        scheduler.start()
        logger.info(
            "in-process scheduler started with %d job(s) (Asia/Colombo)",
            len(scheduler.get_jobs()),
        )
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=True)
            logger.info("in-process scheduler stopped")


app = FastAPI(
    title="CSE Alpha Engine",
    description=(
        "Decision-support API for CSE equities. Deterministic code computes; "
        "AI explains. This service never places an order and never exposes a "
        "single-verdict recommendation endpoint — see Design Law 6, Master "
        "Spec §4."
    ),
    version="0.1.0-phase1",
    lifespan=lifespan,
)

# --- Access gate (app.security) ----------------------------------------------
# Fails LOUD and at import time, not quietly at the first real request: a
# password gate whose signing key nobody actually set would either crash
# on first login (annoying) or, worse, get "fixed" by someone hard-coding
# a key into source (a real leaked-secret incident waiting to happen).
# Refusing to start is the safer failure mode for a security feature.
if auth_enabled() and not settings.session_secret_key:
    raise RuntimeError(
        "ADMIN_PASSWORD is set but SESSION_SECRET_KEY is not — refusing to start with a "
        "login gate whose session cookie nobody can trust the signing of. Set "
        "SESSION_SECRET_KEY to a long random value (e.g. `python -c \"import secrets; "
        "print(secrets.token_hex(32))\"`) in this environment's own secrets, once, and "
        "keep it stable across restarts (rotating it logs every session out)."
    )
_session_secret = settings.session_secret_key or secrets.token_hex(32)
if not settings.session_secret_key:
    logger.info(
        "SESSION_SECRET_KEY not set — using an ephemeral key for this process. Fine while "
        "the access gate is off (ADMIN_PASSWORD unset); every session would silently log "
        "out on restart if the gate were ever turned on without also setting this."
    )
logger.info("access gate: %s", "ON (ADMIN_PASSWORD set)" if auth_enabled() else "off (dev default)")

# Registered in this order so, per Starlette's "last-added wraps
# outermost" rule, requests flow CORS -> security headers -> session ->
# auth gate -> routes on the way in (SessionMiddleware must populate
# `scope["session"]` before AuthGateMiddleware reads it — see that
# class's own docstring for why getting this backwards 401s everything).
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=14 * 24 * 60 * 60,  # 14 days — a personal tool, not a banking session
)
app.add_middleware(SecurityHeadersMiddleware)

# Confirm-queue frontend (frontend/) runs on the Vite dev server during
# development. This is an internal review tool, not a public API — origins
# are limited to local dev ports plus whatever the operator explicitly
# names for a real hosted deployment (`settings.extra_allowed_origins`),
# never a wildcard. `allow_credentials=True` is what lets the session
# cookie above actually travel on a cross-origin request at all (a
# wildcard origin and `allow_credentials=True` cannot be combined per the
# CORS spec — the browser rejects it — which is one more reason the
# allowlist stays a real list, never "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5180",
        *settings.extra_allowed_origins,
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
    # R1 T3.1/T3.2: Content-Disposition isn't one of the handful of
    # "simple response headers" a cross-origin fetch can read by default —
    # without this, the frontend's own export download silently falls
    # back to a generic filename instead of the server's real one.
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router)
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
app.include_router(composite_ranking.router)
app.include_router(export.router)

# M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md
# §1.3): the ONE allowlisted edit to this file, guarded so the app is
# byte-identical in behaviour with the flag off (§0 rule 6) — with
# `m5_enabled` false, `m5.api.router` is never even imported, and
# `/api/v5/*` 404s exactly as if M5 didn't exist.
if settings.m5_enabled:
    from m5.api.router import router as m5_router

    app.include_router(m5_router, prefix="/api/v5")
