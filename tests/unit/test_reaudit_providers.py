"""Re-audit regression tests for cluster PROVIDER.

Two verified findings in the LLM provider / resilience layer:

  BUG (HIGH) — ``LiteLLMProvider._wrap_error`` built a *plain* ``ProviderError``
    for every failure. ``resilience.RetryPolicy`` only retries entries of
    ``_RETRYABLE`` (transient infra errors); a plain ``ProviderError`` matches
    none of them, so the LiteLLM fallback path NEVER retried transient failures
    (timeout / connection reset / 5xx / rate-limit). The fix mirrors
    ``AnthropicProvider._to_provider_error``: transient SDK exceptions become
    ``TransientProviderError`` (which IS in ``_RETRYABLE``), while permanent
    errors (auth / bad request / content policy) stay a plain, non-retryable
    ``ProviderError``.

  COVERAGE — two live ``CircuitBreaker`` branches were untested:
    * HALF_OPEN -> OPEN reopen when the single probe fails
      (resilience.py ~104-110).
    * HALF_OPEN probe-limit rejection when a probe is already in flight
      (resilience.py ~73-76).

Every test below FAILS against the pre-fix code (for the BUG tests) or pins a
previously-uncovered branch, and PASSES after the fix.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from litellm import (
    APIConnectionError,
    AuthenticationError,
    BadGatewayError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from open_chat_shop.core.exceptions import ProviderError
from open_chat_shop.core.litellm_provider import LiteLLMProvider
from open_chat_shop.core.provider import TransientProviderError
from open_chat_shop.core.resilience import (
    _RETRYABLE,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    RetryPolicy,
)
from open_chat_shop.core.types import Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL = "gpt-4o-mini"


def _provider() -> LiteLLMProvider:
    return LiteLLMProvider(model=_MODEL, api_key="test-key")


def _make_messages() -> list[Message]:
    return [Message(role="user", content="hi")]


def _litellm_exc(cls: type[Exception]) -> Exception:
    """Construct a litellm SDK exception with its required positional args."""
    return cls("boom", model=_MODEL, llm_provider="openai")  # type: ignore[call-arg]


def _wire_resilient_chat(provider: LiteLLMProvider) -> LiteLLMProvider:
    """Reproduce main.py's resilience wiring around provider.chat verbatim.

    This exercises the REAL contract between LiteLLMProvider._wrap_error and
    resilience.RetryPolicy/_RETRYABLE — not a mock of either side — so the two
    sides cannot silently disagree (the double-write lesson).
    """
    circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    retry_policy = RetryPolicy(max_retries=3, base_delay=0.001, max_delay=0.005)
    original_chat = provider.chat

    async def _resilient_chat(*args, **kwargs):  # type: ignore[no-untyped-def]
        async def _call():  # type: ignore[no-untyped-def]
            return await original_chat(*args, **kwargs)

        return await retry_policy.execute(circuit_breaker.call, _call)

    provider.chat = _resilient_chat  # type: ignore[method-assign]
    return provider


# ---------------------------------------------------------------------------
# BUG — LiteLLM transient errors must be classified retryable
# ---------------------------------------------------------------------------


_TRANSIENT_LITELLM = [
    Timeout,
    APIConnectionError,
    InternalServerError,
    ServiceUnavailableError,
    BadGatewayError,
    RateLimitError,
]

_PERMANENT_LITELLM = [
    AuthenticationError,
    BadRequestError,
    NotFoundError,
]


class TestWrapErrorClassification:
    @pytest.mark.parametrize("cls", _TRANSIENT_LITELLM)
    def test_transient_litellm_error_maps_to_transient(
        self, cls: type[Exception]
    ) -> None:
        # Pre-fix every one of these became a plain ProviderError → not retried.
        provider = _provider()
        mapped = provider._wrap_error(_litellm_exc(cls))
        assert isinstance(mapped, TransientProviderError), cls.__name__
        # And it must actually match what the retry layer retries on.
        assert isinstance(mapped, _RETRYABLE), cls.__name__

    @pytest.mark.parametrize("cls", _PERMANENT_LITELLM)
    def test_permanent_litellm_error_stays_plain(
        self, cls: type[Exception]
    ) -> None:
        provider = _provider()
        mapped = provider._wrap_error(_litellm_exc(cls))
        assert isinstance(mapped, ProviderError)
        assert not isinstance(mapped, TransientProviderError), cls.__name__
        assert not isinstance(mapped, _RETRYABLE), cls.__name__

    def test_raw_timeout_maps_to_transient(self) -> None:
        provider = _provider()
        mapped = provider._wrap_error(TimeoutError("slow"))
        assert isinstance(mapped, TransientProviderError)

    def test_raw_connection_reset_maps_to_transient(self) -> None:
        provider = _provider()
        mapped = provider._wrap_error(ConnectionResetError("reset"))
        assert isinstance(mapped, TransientProviderError)

    def test_httpx_transport_error_maps_to_transient(self) -> None:
        # litellm usually wraps these in its own Timeout/APIConnectionError, but
        # raw httpx transport errors can escape; they are NOT OSError subclasses
        # so they must be matched explicitly or retry would miss them.
        provider = _provider()
        for exc in (
            httpx.ConnectError("refused"),
            httpx.ReadTimeout("read timed out"),
            httpx.ConnectTimeout("connect timed out"),
        ):
            mapped = provider._wrap_error(exc)
            assert isinstance(mapped, TransientProviderError), exc

    def test_plain_exception_stays_non_retryable(self) -> None:
        # A generic, unclassifiable error must NOT be retried (fail fast).
        provider = _provider()
        mapped = provider._wrap_error(Exception("mystery"))
        assert isinstance(mapped, ProviderError)
        assert not isinstance(mapped, TransientProviderError)

    def test_already_transient_is_passed_through_unchanged(self) -> None:
        provider = _provider()
        original = TransientProviderError("already transient", _MODEL)
        assert provider._wrap_error(original) is original

    def test_wrapped_error_preserves_provider_and_message(self) -> None:
        provider = _provider()
        mapped = provider._wrap_error(_litellm_exc(RateLimitError))
        assert mapped.provider == _MODEL
        assert "boom" in mapped.message
        assert mapped.details["exception_type"] == "RateLimitError"


# ---------------------------------------------------------------------------
# BUG — the REAL retry path: transient litellm error must be retried to success
# ---------------------------------------------------------------------------


class TestLiteLLMTransientRetry:
    @pytest.mark.asyncio
    async def test_transient_failure_is_retried_then_succeeds(self) -> None:
        """litellm.acompletion raises a transient SDK error twice, then succeeds.

        Pre-fix _wrap_error produced a plain ProviderError that RetryPolicy
        ignored, so chat() raised on the FIRST attempt. After the fix the wrapped
        error is a TransientProviderError and the layer retries to recovery.
        """
        provider = _provider()
        calls = {"n": 0}

        async def _flaky(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] <= 2:
                raise _litellm_exc(ServiceUnavailableError)
            return _ok_response()

        _wire_resilient_chat(provider)
        with patch("litellm.acompletion", new=_flaky):
            result = await provider.chat(_make_messages())

        assert result.content == "recovered"
        assert calls["n"] == 3, "expected 2 retries before success"

    @pytest.mark.asyncio
    async def test_rate_limit_is_retried(self) -> None:
        """RateLimitError is a transient 429 and must be retried, not fail fast."""
        provider = _provider()
        calls = {"n": 0}

        async def _rate_limited_once(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                raise _litellm_exc(RateLimitError)
            return _ok_response()

        _wire_resilient_chat(provider)
        with patch("litellm.acompletion", new=_rate_limited_once):
            result = await provider.chat(_make_messages())

        assert result.content == "recovered"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_permanent_failure_is_not_retried(self) -> None:
        """A permanent auth error must fail fast — exactly one attempt."""
        provider = _provider()
        calls = {"n": 0}

        async def _always_auth_fail(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            raise _litellm_exc(AuthenticationError)

        _wire_resilient_chat(provider)
        with (
            patch("litellm.acompletion", new=_always_auth_fail),
            pytest.raises(ProviderError),
        ):
            await provider.chat(_make_messages())

        assert calls["n"] == 1, "permanent error must not be retried"

    @pytest.mark.asyncio
    async def test_transient_exhausts_retries_then_raises(self) -> None:
        """If the transient condition never clears, retries are exhausted and the
        wrapped TransientProviderError (still a ProviderError) surfaces."""
        provider = _provider()
        calls = {"n": 0}

        async def _always_down(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            raise _litellm_exc(InternalServerError)

        _wire_resilient_chat(provider)
        with (
            patch("litellm.acompletion", new=_always_down),
            pytest.raises(TransientProviderError),
        ):
            await provider.chat(_make_messages())

        # max_retries=3 → 1 initial + 3 retries = 4 attempts.
        assert calls["n"] == 4


def _ok_response() -> AsyncMock:
    """A minimal litellm completion response that _parse_response accepts."""
    resp = AsyncMock()
    choice = AsyncMock()
    choice.message.content = "recovered"
    choice.message.tool_calls = None
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.usage.prompt_tokens = 1
    resp.usage.completion_tokens = 1
    resp.usage.total_tokens = 2
    return resp


# ---------------------------------------------------------------------------
# COVERAGE — CircuitBreaker live branches that had no test
# ---------------------------------------------------------------------------


async def _ok(*args, **kwargs):  # type: ignore[no-untyped-def]
    return "ok"


def _make_failing(exc: type[Exception]):  # type: ignore[no-untyped-def]
    async def _fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise exc("boom")

    return _fail


class TestCircuitBreakerReopen:
    @pytest.mark.asyncio
    async def test_half_open_probe_failure_reopens_circuit(self) -> None:
        """HALF_OPEN -> OPEN when the single probe fails (resilience.py ~104-110).

        Existing tests only covered the HALF_OPEN -> CLOSED (probe succeeds)
        path. This pins the failure branch: a failed probe must NOT close the
        circuit and must NOT leak into CLOSED; it goes straight back to OPEN.
        """
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)

        # Trip OPEN.
        with pytest.raises(RuntimeError):
            await cb.call(_make_failing(RuntimeError))
        assert cb.state == CircuitState.OPEN

        # Wait past recovery_timeout so the next call transitions to HALF_OPEN.
        await asyncio.sleep(0.08)

        # The probe fails → must reopen (HALF_OPEN -> OPEN), not close.
        with pytest.raises(RuntimeError):
            await cb.call(_make_failing(RuntimeError))
        assert cb.state == CircuitState.OPEN

        # And immediately after reopening, calls are rejected fast again.
        with pytest.raises(CircuitOpenError):
            await cb.call(_ok)

    @pytest.mark.asyncio
    async def test_half_open_rejects_second_concurrent_probe(self) -> None:
        """HALF_OPEN probe-limit rejection (resilience.py ~73-76).

        With half_open_max=1, once a probe is in flight a second concurrent call
        in HALF_OPEN must be rejected with CircuitOpenError rather than also
        hitting the (assumed-fragile) downstream.
        """
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()

        async def _slow_probe(*args, **kwargs):  # type: ignore[no-untyped-def]
            probe_started.set()
            await release_probe.wait()
            return "probe-ok"

        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.05, half_open_max=1
        )

        # Trip OPEN.
        with pytest.raises(RuntimeError):
            await cb.call(_make_failing(RuntimeError))
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.08)  # OPEN -> eligible for HALF_OPEN on next call.

        # Launch the first probe; it parks inside the downstream call, holding
        # the single half-open slot.
        first = asyncio.create_task(cb.call(_slow_probe))
        await probe_started.wait()
        assert cb.state == CircuitState.HALF_OPEN

        # A second probe while the first is in flight must be rejected.
        with pytest.raises(CircuitOpenError, match="probe limit"):
            await cb.call(_ok)

        # Let the first probe finish; it should close the circuit.
        release_probe.set()
        assert await first == "probe-ok"
        assert cb.state == CircuitState.CLOSED
