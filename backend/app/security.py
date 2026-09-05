"""
The access gate for a hosted, single-operator deployment.

THREAT MODEL, STATED PLAINLY. There are no user accounts, roles or
signup anywhere in this codebase, and none are being added here — the
product owner is the only intended user. Once this API is reachable from
the open internet (rather than only `localhost`), the real risk is not
"a rival user does something they shouldn't" but "a stranger who finds
the URL reads the fundamentals queue, triggers a `/jobs/{job}/run`
ingestion sweep against cse.lk under this system's own identity, or pokes
at the confirm-batch endpoints." A single shared password behind a
signed session cookie closes that door completely for that threat model;
building real multi-user auth (accounts, roles, password reset email)
would be solving a problem this product doesn't have.

HOW IT STAYS OFF IN DEV. `settings.admin_password` unset is the single
switch that keeps every request passing through exactly as it always
has — `AuthGateMiddleware` below is a no-op the moment `app.config.
settings.admin_password is None`. Local development (this whole
project's day-to-day, `uvicorn app.main:app` against `localhost:5173`)
never sets it, so nothing here has ever changed that workflow. The gate
exists to be turned on by setting one environment variable on whatever
actually hosts this, never by editing code.

WHY A SIGNED SESSION COOKIE, NOT A BEARER TOKEN THE FRONTEND STORES.
`localStorage`/`sessionStorage` are readable by any script that runs on
the page — a real XSS in any one dependency would hand over the token
outright. An `httpOnly` cookie is invisible to page JavaScript entirely;
`starlette.middleware.sessions.SessionMiddleware` (added in `app.main`)
signs it with `itsdangerous`, so a client can read that a cookie exists
but cannot forge or tamper with its content without `session_secret_key`,
which never leaves the server.
"""
from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

logger = logging.getLogger("cse_alpha.security")

#: Paths reachable with NO session — deliberately tiny. A load balancer's
#: own health probe needs `/health` before any operator has ever logged
#: in; `/auth/login` and `/auth/status` obviously cannot themselves
#: require the session they establish or report on. Everything else,
#: including `/docs`/`/openapi.json`, sits behind the gate — API
#: shape/version fingerprinting is exactly the kind of low-cost
#: reconnaissance a public, unauthenticated docs page hands a stranger
#: for free.
_PUBLIC_PATHS = frozenset({"/health", "/auth/login", "/auth/status"})


def auth_enabled() -> bool:
    """The gate is live the moment an operator has set a password —
    never based on `settings.environment`, which is easy to leave at its
    "development" default by mistake on a real host. Presence of the
    password is the one fact that cannot be forgotten silently."""
    return bool(settings.admin_password)


def verify_password(candidate: str) -> bool:
    """Constant-time comparison (`hmac.compare_digest`) — a naive `==`
    leaks how many leading characters matched via response timing, a
    real and well-documented attack against exactly this shape of check.
    """
    if not settings.admin_password:
        return False
    return hmac.compare_digest(candidate, settings.admin_password)


# --- Login rate limiting -----------------------------------------------------
# In-memory, per-process — correct for the single-uvicorn-worker
# deployment this whole project's `app/worker.py` docstring already
# assumes (a real multi-worker deployment would need a shared store, e.g.
# Redis, but that is a scale this single-operator tool is not at). Blunts
# a password-guessing script, not a distributed attack; the fix for that
# class of threat is a strong password, which is on the operator, not
# this module.
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300.0
_login_attempts: dict[str, list[float]] = defaultdict(list)


def register_login_attempt(client_key: str) -> None:
    _login_attempts[client_key].append(time.monotonic())


def login_rate_limited(client_key: str) -> float | None:
    """Returns the seconds until the next attempt is allowed, or `None`
    if the client is clear to try. Old attempts fall out of the window on
    every check rather than needing a separate sweep."""
    now = time.monotonic()
    attempts = _login_attempts[client_key]
    attempts[:] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(attempts) < _LOGIN_MAX_ATTEMPTS:
        return None
    return _LOGIN_WINDOW_SECONDS - (now - attempts[0])


def clear_login_attempts(client_key: str) -> None:
    _login_attempts.pop(client_key, None)


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting only — never used
    for anything security-load-bearing beyond "slow down the same
    caller", so a spoofed `X-Forwarded-For` merely lets an attacker reset
    their own counter, not bypass the password itself."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class AuthGateMiddleware:
    """Requires `request.session["authed"]` on every path not in
    `_PUBLIC_PATHS`, whenever `auth_enabled()` — pure ASGI middleware
    (not `BaseHTTPMiddleware`) so it sits in front of routing itself and
    a 401 here never runs a single line of handler code, including for a
    path FastAPI would otherwise 404 on (this must not leak which routes
    exist to an unauthenticated caller either).

    Depends on `SessionMiddleware` already having populated
    `scope["session"]` before this middleware runs — Starlette wraps each
    `add_middleware` call around the current stack, so the LAST-added
    middleware is OUTERMOST and sees the request FIRST. `app.main`
    therefore adds THIS middleware before it adds `SessionMiddleware`, so
    on the way in `SessionMiddleware` (outer) runs first and sets
    `scope["session"]`, then this one (inner) reads it — get that order
    backwards and every request 401s, because `scope["session"]` would
    not exist yet when this class runs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not auth_enabled():
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        session = scope.get("session", {})
        if session.get("authed"):
            await self.app(scope, receive, send)
            return

        response = JSONResponse({"detail": "Not authenticated"}, status_code=401)
        await response(scope, receive, send)


class SecurityHeadersMiddleware:
    """A handful of standard, low-cost response headers with no behavior
    trade-off — every one of these narrows a real, named class of attack
    and never changes what a legitimate request sees:

      - `X-Content-Type-Options: nosniff` — stops a browser from
        second-guessing a response's declared content type, the root
        cause class behind serving a JSON/CSV response as executable
        script.
      - `X-Frame-Options: DENY` — this app has no reason to ever be
        framed by another site; blocks clickjacking outright.
      - `Referrer-Policy: strict-origin-when-cross-origin` — an internal
        ticker/decision URL never needs to leak into another site's
        referrer logs.
      - `Strict-Transport-Security` — tells the browser to remember
        "always HTTPS for this host" for a year. Harmless to send over
        plain HTTP (browsers ignore HSTS on a non-HTTPS response), so
        sent unconditionally rather than gated on `session_cookie_secure`
        — the day this IS served over HTTPS, the header is already there
        with no further deploy step.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in (
                        ("X-Content-Type-Options", "nosniff"),
                        ("X-Frame-Options", "DENY"),
                        ("Referrer-Policy", "strict-origin-when-cross-origin"),
                        ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
                    )
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)
