"""The login gate for a hosted deployment — see `app.security`'s own
module docstring for the full threat model and why this is a single
shared password behind a signed session cookie, not real multi-user
accounts.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.security import (
    auth_enabled,
    clear_login_attempts,
    client_key,
    login_rate_limited,
    register_login_attempt,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    """The frontend calls this once on load to decide whether to show
    the login screen at all — `required=False` (auth disabled, e.g.
    local dev) means it renders the app straight away; `required=True,
    authenticated=False` shows the password prompt; both `True` renders
    the app. Deliberately in `_PUBLIC_PATHS` (`app.security`) so a
    logged-out visitor's very first request isn't itself a 401."""
    required = auth_enabled()
    return {
        "required": required,
        "authenticated": bool(request.session.get("authed")) if required else True,
    }


@router.post("/login")
def login(body: LoginIn, request: Request) -> JSONResponse:
    if not auth_enabled():
        # Nothing to log into — this deployment has no password set.
        return JSONResponse({"ok": True})

    key = client_key(request)
    retry_after = login_rate_limited(key)
    if retry_after is not None:
        return JSONResponse(
            {"detail": "Too many attempts — try again later.", "retry_after": math.ceil(retry_after)},
            status_code=429,
        )

    if not verify_password(body.password):
        register_login_attempt(key)
        return JSONResponse({"detail": "Incorrect password."}, status_code=401)

    clear_login_attempts(key)
    request.session["authed"] = True
    return JSONResponse({"ok": True})


@router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}
