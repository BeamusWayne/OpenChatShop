"""Tests for circuit breaker and retry policy."""
from __future__ import annotations

import asyncio

import pytest

from open_chat_shop.core.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    RetryPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ok(*args, **kwargs):
    """A coroutine that always succeeds."""
    return "ok"


def _make_failing(exc: type[Exception]):
    """Return a coroutine function that always raises *exc*."""

    async def _fail(*args, **kwargs):
        raise exc("boom")

    return _fail


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_state_is_closed():
    cb = CircuitBreaker()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_successful_call_returns_result():
    cb = CircuitBreaker()
    result = await cb.call(_ok)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_consecutive_failures_open_circuit():
    cb = CircuitBreaker(failure_threshold=3)
    fail = _make_failing(RuntimeError)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(fail)

    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_rejects_calls():
    cb = CircuitBreaker(failure_threshold=1)
    with pytest.raises(RuntimeError):
        await cb.call(_make_failing(RuntimeError))

    assert cb.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


@pytest.mark.asyncio
async def test_half_open_recovery_after_timeout():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)

    # Trip the breaker open
    with pytest.raises(RuntimeError):
        await cb.call(_make_failing(RuntimeError))
    assert cb.state == CircuitState.OPEN

    # Wait for recovery timeout so it transitions to HALF_OPEN
    await asyncio.sleep(0.1)

    # A successful probe should close the circuit
    result = await cb.call(_ok)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# RetryPolicy tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures():
    call_count = 0

    async def _flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("transient")
        return "recovered"

    policy = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1)
    result = await policy.execute(_flaky)
    assert result == "recovered"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises_last_error():
    policy = RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.1)

    with pytest.raises(TimeoutError):
        await policy.execute(_make_failing(TimeoutError))


@pytest.mark.asyncio
async def test_non_retryable_exception_not_retried():
    call_count = 0

    async def _bad_value(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("bad input")

    policy = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1)

    with pytest.raises(ValueError, match="bad input"):
        await policy.execute(_bad_value)

    # Should have been called exactly once — no retries for ValueError
    assert call_count == 1
