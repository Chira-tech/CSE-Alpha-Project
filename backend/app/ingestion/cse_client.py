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

This module implements every one of those requirements generically. It
does NOT hard-code the actual endpoint paths/response shapes as fact —
Part II §5.2 names several (`marketStatus`, `marketSummery`,
`tradeSummary`, `todaySharePrice`, `companyInfoSummery`,
`detailedTrades`, `dailyMarketSummery`, `aspiData`, `snpData`,
`topGainers`, `topLooses`) but these are undocumented and may have
drifted since the spec was written (9 Aug 2026). ROADMAP.md tracks
confirming them against the live API as the next task. Endpoint-specific
loaders (app.ingestion.price_loader etc.) pass a pydantic model in for
validation; a shape mismatch raises ShapeChangedError rather than
returning silently-wrong data — this is the "alert on shape change, not
just HTTP error" requirement.
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
    high-concurrency client). Never call `.get()` from multiple threads
    concurrently for the same instance; that would defeat the whole point
    of `--min_seconds_between_calls` pacing and the "never parallel
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

    def _do_request(self, path: str, params: dict[str, Any] | None) -> httpx.Response:
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
                response = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise TransientFetchError(f"timeout calling {url}") from exc
            except httpx.TransportError as exc:
                raise TransientFetchError(f"transport error calling {url}: {exc}") from exc

            if _is_retryable_status(response):
                raise TransientFetchError(f"{response.status_code} from {url}")
            return response

        return _attempt()

    def get_json(
        self,
        path: str,
        *,
        model: type[ModelT] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ModelT | dict[str, Any] | list[Any]:
        """Fetch `path` and, if `model` is given, validate the response
        against it. Raises ShapeChangedError (not silently returning
        malformed data) if validation fails, and CircuitOpenError without
        making a network call at all once the breaker has tripped.
        """
        self._breaker.before_call()

        try:
            response = self._do_request(path, params)
        except TransientFetchError:
            self._breaker.record_failure()
            raise

        if response.status_code >= 400:
            # Non-retryable client error (e.g. 404) — still a failure for
            # breaker purposes, but we don't retry it.
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
