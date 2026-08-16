"""
Master Spec §5, "THE SINGLE BIGGEST OPERATIONAL FRAGILITY":

    "The cse.lk JSON endpoints are reverse-engineered rather than
    officially documented, and they require no authentication but do
    warrant sensible self-imposed rate limiting. Treat them as a
    dependency that will break without notice: schema validation on every
    response, contract tests in CI, alerting on shape change rather than
    only on HTTP error, conservative pacing (>=2s between calls),
    exponential backoff, a circuit breaker, an identifying user-agent, and
    never parallel hammering."

This module implements every one of those requirements. Unlike the first
Phase-1 pass, the request semantics below are VERIFIED against the live
API (probed 16 Aug 2026 — see app/ingestion/README_ENDPOINTS.md for the
full trace and raw captured payloads), not transcribed from the spec:

  * Every endpoint uses POST, never GET (GET returns 405/400
    "Could not find the GET method for URL ..."). The spec's own naming
    (`marketStatus`, `tradeSummary`, ...) is correct; the HTTP method it
    implied was not.
  * Endpoints with no required parameters (marketStatus, tradeSummary,
    todaySharePrice, topGainers, topLooses, aspiData, dailyMarketSummery)
    accept a POST with a JSON body (verified with `{}`).
  * Endpoints that take a parameter (companyInfoSummery, detailedTrades,
    getAnnouncementByCompany, getAnnouncementById, getGeneralAnnouncementById)
    require application/x-www-form-urlencoded, NOT a JSON body — a JSON
    body against these returns 400 "symbol parameter is missing" even
    when the field is present, because the server reads form fields.
  * A 204 No Content is a real, valid response for some detail lookups
    (e.g. `getAnnouncementById` returns 204 for an announcement that only
    exists as a "general" announcement — the caller must retry against
    `getGeneralAnnouncementById`). Callers must not treat 204 as an error.

`get_json` is kept for API completeness/tests but no live cse.lk endpoint
found during this verification pass actually accepts GET.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.ingestion.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("cse_alpha.ingestion.cse_client")

ModelT = TypeVar("ModelT", bound=BaseModel)


class ShapeChangedError(RuntimeError):
    """Raised when a response fails pydantic validation against the
    expected schema — i.e. the endpoint still answers, but its shape has
    changed. Per §5 this must be distinguished from a plain HTTP error and
    alerted on separately."""


class TransientFetchError(RuntimeError):
    """Network/HTTP errors worth retrying (timeouts, 5xx, connection
    resets). Deliberately NOT retried: 4xx other than 429, and
    ShapeChangedError — retrying a shape mismatch just spams a broken
    endpoint."""


def _is_retryable_status(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500


class CseClient:
    """Thread-safe-enough for a single ingestion worker (one process, one
    scheduler per Master Spec §52 — this is deliberately not a
    high-concurrency client). Never call it from multiple threads
    concurrently for the same instance; that would defeat the whole point
    of `min_seconds_between_calls` pacing and the "never parallel
    hammering" rule.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        min_seconds_between_calls: float | None = None,
        user_agent: str | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or settings.cse_base_url).rstrip("/")
        self.min_seconds_between_calls = (
            min_seconds_between_calls
            if min_seconds_between_calls is not None
            else settings.cse_min_seconds_between_calls
        )
        self._user_agent = user_agent or settings.cse_user_agent
        self._breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=settings.cse_circuit_breaker_failure_threshold,
            reset_seconds=settings.cse_circuit_breaker_reset_seconds,
        )
        self._max_retries = max_retries if max_retries is not None else settings.cse_max_retries
        self._client = client or httpx.Client(
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            timeout=15.0,
        )
        self._last_call_monotonic: float | None = None
        self._pacing_lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CseClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _throttle(self) -> None:
        """Enforce the >=2s (default) minimum gap between outbound calls,
        regardless of retries — this is the "conservative pacing" rule."""
        with self._pacing_lock:
            if self._last_call_monotonic is not None:
                elapsed = time.monotonic() - self._last_call_monotonic
                remaining = self.min_seconds_between_calls - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            self._last_call_monotonic = time.monotonic()

    def _do_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(TransientFetchError),
        )
        def _attempt() -> httpx.Response:
            self._throttle()
            url = f"{self.base_url}/{path.lstrip('/')}"
            try:
                response = self._client.request(
                    method, url, params=params, json=json_body, data=form_body
                )
            except httpx.TimeoutException as exc:
                raise TransientFetchError(f"timeout calling {url}") from exc
            except httpx.TransportError as exc:
                raise TransientFetchError(f"transport error calling {url}: {exc}") from exc

            if _is_retryable_status(response):
                raise TransientFetchError(f"{response.status_code} from {url}")
            return response

        return _attempt()

    def _execute(
        self,
        method: str,
        path: str,
        *,
        model: type[ModelT] | None,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        form_body: dict[str, Any] | None,
        allow_empty: bool,
    ) -> ModelT | dict[str, Any] | list[Any] | None:
        self._breaker.before_call()

        try:
            response = self._do_request(
                method, path, params=params, json_body=json_body, form_body=form_body
            )
        except TransientFetchError:
            self._breaker.record_failure()
            raise

        if response.status_code == 204:
            # Verified real behaviour, not a bug to work around: some
            # detail-lookup endpoints (getAnnouncementById) return 204 for
            # an id that belongs to a different announcement family.
            self._breaker.record_success()
            if allow_empty:
                return None
            raise ShapeChangedError(f"{path} returned 204 No Content, which this caller doesn't allow")

        if response.status_code >= 400:
            self._breaker.record_failure()
            response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            self._breaker.record_failure()
            raise ShapeChangedError(f"{path} did not return valid JSON") from exc

        if model is not None:
            try:
                validated = model.model_validate(payload)
            except ValidationError as exc:
                self._breaker.record_failure()
                logger.warning("shape change detected on %s: %s", path, exc)
                raise ShapeChangedError(f"{path} response no longer matches {model.__name__}") from exc
            self._breaker.record_success()
            return validated

        self._breaker.record_success()
        return payload

    def get_json(
        self,
        path: str,
        *,
        model: type[ModelT] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ModelT | dict[str, Any] | list[Any] | None:
        """GET request. Kept for completeness/tests — no live cse.lk
        endpoint confirmed during Phase 1 verification actually accepts
        GET; prefer post_json/post_form for real ingestion."""
        return self._execute(
            "GET", path, model=model, params=params, json_body=None, form_body=None, allow_empty=False
        )

    def post_json(
        self,
        path: str,
        *,
        model: type[ModelT] | None = None,
        body: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> ModelT | dict[str, Any] | list[Any] | None:
        """POST with a JSON body. Verified for the no-parameter list
        endpoints: marketStatus, tradeSummary, todaySharePrice,
        topGainers, topLooses, aspiData, dailyMarketSummery — all accept
        `body={}`."""
        return self._execute(
            "POST", path, model=model, params=None, json_body=body or {}, form_body=None, allow_empty=allow_empty
        )

    def post_form(
        self,
        path: str,
        *,
        model: type[ModelT] | None = None,
        data: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> ModelT | dict[str, Any] | list[Any] | None:
        """POST with application/x-www-form-urlencoded data. Verified for
        the parameterised endpoints: companyInfoSummery, detailedTrades
        (symbol=...), getAnnouncementByCompany (symbol=...),
        getAnnouncementById / getGeneralAnnouncementById
        (announcementId=...). `allow_empty=True` is needed for
        getAnnouncementById specifically, which returns 204 for ids that
        belong to the "general announcement" family instead."""
        return self._execute(
            "POST", path, model=model, params=None, json_body=None, form_body=data or {}, allow_empty=allow_empty
        )
