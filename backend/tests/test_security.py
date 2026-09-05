"""app.security — the hosted-deployment access gate.

`app.main.app` bakes `SessionMiddleware`'s `https_only` flag in at import
time (a real Starlette constructor argument, not something re-read per
request), so a full login-round-trip-over-plain-http test against the
already-imported app would need `SESSION_COOKIE_SECURE=false` set before
collection ever imports `app.main` — not something a single test can
arrange. `TestFullGateRoundTrip` below builds its own small Starlette app
with the same three middlewares and `https_only=False` instead, exactly
for this reason; every other test here exercises the REAL `app.main.app`
via the `client` fixture, since `auth_enabled()`/`verify_password()` read
`app.config.settings` fresh on every call and respond correctly to
`monkeypatch.setattr` regardless of when the app was constructed.
"""
from __future__ import annotations

import time

from app import security
from app.config import settings


class TestVerifyPassword:
    def test_correct_password_true(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        assert security.verify_password("hunter2") is True

    def test_wrong_password_false(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        assert security.verify_password("wrong") is False

    def test_no_password_configured_always_false(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", None)
        assert security.verify_password("anything") is False


class TestAuthEnabled:
    def test_off_when_unset(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", None)
        assert security.auth_enabled() is False

    def test_on_when_set(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        assert security.auth_enabled() is True


class TestLoginRateLimit:
    def test_clears_below_the_limit(self):
        key = "test-client-a"
        security.clear_login_attempts(key)
        for _ in range(security._LOGIN_MAX_ATTEMPTS - 1):
            security.register_login_attempt(key)
        assert security.login_rate_limited(key) is None

    def test_locks_out_at_the_limit(self):
        key = "test-client-b"
        security.clear_login_attempts(key)
        for _ in range(security._LOGIN_MAX_ATTEMPTS):
            security.register_login_attempt(key)
        retry_after = security.login_rate_limited(key)
        assert retry_after is not None
        assert 0 < retry_after <= security._LOGIN_WINDOW_SECONDS

    def test_a_successful_login_clears_the_counter(self):
        key = "test-client-c"
        security.clear_login_attempts(key)
        for _ in range(security._LOGIN_MAX_ATTEMPTS):
            security.register_login_attempt(key)
        assert security.login_rate_limited(key) is not None
        security.clear_login_attempts(key)
        assert security.login_rate_limited(key) is None

    def test_old_attempts_fall_out_of_the_window(self, monkeypatch):
        key = "test-client-d"
        security.clear_login_attempts(key)
        fake_now = [time.monotonic()]
        monkeypatch.setattr(security.time, "monotonic", lambda: fake_now[0])
        for _ in range(security._LOGIN_MAX_ATTEMPTS):
            security.register_login_attempt(key)
        assert security.login_rate_limited(key) is not None
        fake_now[0] += security._LOGIN_WINDOW_SECONDS + 1
        assert security.login_rate_limited(key) is None


class TestAuthGateOverHttp:
    """Exercises the real `app.main.app` — `auth_enabled()` is read fresh
    on every request, so toggling `settings.admin_password` here takes
    effect immediately with no app rebuild needed."""

    def test_gate_off_by_default_every_route_reachable(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", None)
        assert client.get("/health").status_code == 200
        assert client.get("/data-health").status_code == 200

    def test_gate_on_blocks_an_unauthenticated_request(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        r = client.get("/data-health")
        assert r.status_code == 401

    def test_public_paths_stay_reachable_with_the_gate_on(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        assert client.get("/health").status_code == 200
        assert client.get("/auth/status").status_code == 200

    def test_docs_are_gated_too(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        assert client.get("/docs").status_code == 401
        assert client.get("/openapi.json").status_code == 401

    def test_wrong_password_401_and_does_not_authenticate(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        security.clear_login_attempts("testclient")
        r = client.post("/auth/login", json={"password": "wrong"})
        assert r.status_code == 401
        assert client.get("/data-health").status_code == 401

    def test_login_locks_out_after_repeated_failures(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", "hunter2")
        security.clear_login_attempts("testclient")
        for _ in range(security._LOGIN_MAX_ATTEMPTS):
            client.post("/auth/login", json={"password": "wrong"})
        r = client.post("/auth/login", json={"password": "wrong"})
        assert r.status_code == 429
        assert "retry_after" in r.json()

    def test_status_reports_required_and_authenticated_honestly(self, client, monkeypatch):
        monkeypatch.setattr(settings, "admin_password", None)
        assert client.get("/auth/status").json() == {"required": False, "authenticated": True}


class TestFullGateRoundTrip:
    """A standalone app with the same three middlewares (in the same
    order `app.main` uses) but `https_only=False`, so the session cookie
    actually round-trips over TestClient's plain-http `testserver` —
    proves the login -> authenticated -> logout -> logged-out cycle
    genuinely works end to end, not just that each response code is
    individually correct in isolation."""

    def test_full_login_logout_cycle(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware

        from app.api.routes.auth import router as auth_router
        from app.security import AuthGateMiddleware, SecurityHeadersMiddleware

        monkeypatch.setattr(settings, "admin_password", "hunter2")
        security.clear_login_attempts("testclient")

        app = FastAPI()
        app.add_middleware(AuthGateMiddleware)
        app.add_middleware(SessionMiddleware, secret_key="test-only-key", https_only=False)
        app.add_middleware(SecurityHeadersMiddleware)
        app.include_router(auth_router)

        @app.get("/protected")
        def protected():
            return {"ok": True}

        with TestClient(app) as c:
            assert c.get("/protected").status_code == 401

            r = c.post("/auth/login", json={"password": "wrong"})
            assert r.status_code == 401
            assert c.get("/protected").status_code == 401

            r = c.post("/auth/login", json={"password": "hunter2"})
            assert r.status_code == 200
            assert c.get("/auth/status").json()["authenticated"] is True
            assert c.get("/protected").status_code == 200

            r = c.post("/auth/logout")
            assert r.status_code == 200
            assert c.get("/protected").status_code == 401

    def test_security_headers_present_on_every_response(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.security import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/x")
        def x():
            return {"ok": True}

        with TestClient(app) as c:
            r = c.get("/x")
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
            assert "max-age=31536000" in r.headers["strict-transport-security"]
