"""Circuit breaker and retry policy for resilient LLM calls."""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["CircuitBreaker", "CircuitState", "RetryPolicy"]


class CircuitState(str, enum.Enum):
    """States of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejects a call."""


@dataclass
class CircuitBreaker:
    """Protects downstream services by breaking the circuit on repeated failures.

    State machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
    - CLOSED: requests pass through; consecutive failures are counted.
    - OPEN: requests are rejected immediately; after *recovery_timeout* the
      circuit transitions to HALF_OPEN.
    - HALF_OPEN: a single probe request is allowed; success resets to CLOSED,
      failure reopens the circuit.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, fn, *args, **kwargs):
        """Wrap an async function with circuit-breaker logic."""
        async with self._lock:
            await self._maybe_transition()

            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(
                    "Circuit breaker is open — rejecting call"
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max:
                    raise CircuitOpenError(
                        "Circuit breaker is half-open — probe limit reached"
                    )
                self._half_open_calls += 1

        # Execute outside the lock so concurrent calls don't block each other
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            await self._record_failure()
            raise

        await self._record_success()
        return result

    async def _maybe_transition(self) -> None:
        """Transition from OPEN -> HALF_OPEN after recovery_timeout."""
        if (
            self._state == CircuitState.OPEN
            and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            logger.info("Circuit breaker transitioned to HALF_OPEN")

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker probe failed — back to OPEN "
                    "(failures=%d)",
                    self._failure_count,
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker tripped OPEN (failures=%d, threshold=%d)",
                    self._failure_count,
                    self.failure_threshold,
                )

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker probe succeeded — closing circuit")
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._half_open_calls = 0


# Exceptions that are safe to retry (transient infrastructure errors).
_RETRYABLE: tuple[type[Exception], ...] = (TimeoutError, ConnectionError, OSError)


@dataclass
class RetryPolicy:
    """Exponential-backoff retry for async functions.

    Only retries on transient errors (TimeoutError, ConnectionError, OSError).
    Business errors (ValueError, etc.) are re-raised immediately.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0
    exponential_base: float = 2.0

    async def execute(self, fn, *args, **kwargs):
        """Execute *fn* with retry and exponential back-off."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except _RETRYABLE as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (self.exponential_base ** attempt),
                        self.max_delay,
                    )
                    logger.info(
                        "Retry attempt %d/%d after %.1fs for %s",
                        attempt + 1,
                        self.max_retries,
                        delay,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(delay)
            except Exception:
                # Non-retryable — propagate immediately
                raise

        # All retries exhausted
        raise last_error  # type: ignore[misc]
