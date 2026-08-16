"""Master Spec §5: "Treat them as a dependency that will break without
notice: ... a circuit breaker." Minimal, dependency-free implementation —
no need to pull in a library for something this small and this important
to have full visibility into.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class CircuitOpenError(RuntimeError):
    """Raised instead of attempting a call while the breaker is open. The
    caller (a loader/job) is expected to catch this, log/alert, and skip —
    never to retry in a hot loop."""


@dataclass
class CircuitBreaker:
    failure_threshold: int
    reset_seconds: float
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_seconds:
            # half-open: allow the next call through to test the waters
            return False
        return True

    def before_call(self) -> None:
        if self.is_open:
            raise CircuitOpenError(
                f"circuit open after {self._consecutive_failures} consecutive failures; "
                f"will retry after {self.reset_seconds}s cool-down"
            )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
