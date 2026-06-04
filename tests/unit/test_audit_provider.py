
"""Regression tests for audit cluster PROVIDER.

Three production bugs in the LLM provider / resilience layer:

  HIGH  — RetryPolicy never retried real provider failures. Both real providers
          wrap every downstream error into ``ProviderError``, which is NOT a
          ``TimeoutError``/``OSError``; so a wrapped transient (timeout / 5xx /
          connection reset) never matched ``_RETRYABLE`` and was re-raised on
          the first attempt. The retry half of the circuit-breaker+retry layer
          was dead for the code path real traffic takes.
  HIGH  — AnthropicProvider built a brand-new ``AsyncAnthropic`` (and a fresh
          httpx connection pool) on EVERY chat()/stream() call and never closed
          it — leaking sockets and defeating keep-alive on the hot path.
  MEDIUM— AnthropicProvider passed no request timeout, so a stalled GLM endpoint
          could hang ~600s (SDK default) and, via the per-session lock, stall
          the whole session.

Each test below FAILS against the pre-fix code and PASSES after the fix.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from open_chat_shop.core.anthropic_provider import (
    _DEFAULT_TIMEOUT_SECONDS,
    AnthropicProvider,
)
from open_chat_shop.core.exceptions import ProviderError
from open_chat_shop.core.provider import TransientProviderError
from open_chat_shop.core.resilience import (
    _RETRYABLE,
    CircuitBreaker,
    RetryPolicy,
)
from open_chat_shop.core.types import GenerateConfig, Message

# ---------------------------------------------------------------------------
# Test doubles mirroring the anthropic SDK response shape
# ---------------------------------------------------------------------------


class _Block:
    def __init__(self, type: str, text: str | None = None) -> None:
        self.type = type
        self.text = text


class _Usage:
    def __init__(self, i: int, o: int) -> None:
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, content: list[_Block]) -> None:
        self.content = content
        self.stop_reason = "end_turn"
        self.usage = _Usage(10, 20)


def _provider() -> AnthropicProvider:
    return AnthropicProvider(api_key="test-key", base_url="http://x", model="glm-test")


# ---------------------------------------------------------------------------
# HIGH — wrapped transient ProviderError must be retried
# ---------------------------------------------------------------------------


def _wire_resilient_chat(provider: AnthropicProvider) -> AnthropicProvider:
    """Reproduce main.py's resilience wiring around provider.chat verbatim."""
    circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    retry_policy = RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.05)
    original_chat = provider.chat

    async def _resilient_chat(*args, **kwargs):  # type: ignore[no-untyped-def]
        async def _call():  # type: ignore[no-untyped-def]
            return await original_chat(*args, **kwargs)

        return await retry_policy.execute(circuit_breaker.call, _call)

    provider.chat = _resilient_chat  # type: ignore[method-assign]
    return provider


class TestTransientRetry:
    def test_transient_provider_error_is_in_retryable_set(self) -> None:
        # Pinning the contract: the wrapped-transient class must be retryable.
        # Before the fix _RETRYABLE was only (TimeoutError, ConnectionError,
        # OSError) and a wrapped ProviderError matched none of them.
        assert TransientProviderError in _RETRYABLE
        assert issubclass(TransientProviderError, ProviderError)

    def test_transient_provider_error_matches_retryable(self) -> None:
        err = TransientProviderError("upstream 503", "glm")
        assert isinstance(err, _RETRYABLE)

    def test_plain_provider_error_is_not_retryable(self) -> None:
        # A permanent failure (auth / bad request) must NOT be retried.
        err = ProviderError("invalid api key", "glm")
        assert not isinstance(err, _RETRYABLE)

    @pytest.mark.asyncio
    async def test_wrapped_transient_failure_is_retried_then_succeeds(self) -> None:
        """The real path: SDK raises a transient error, provider wraps it into a
        TransientProviderError, and the resilience layer retries until success.

        Pre-fix the provider wrapped it into a plain ProviderError that the retry
        layer ignored, so this raised on the first attempt instead of recovering.
        """
        provider = _provider()
        client = MagicMock()
        calls = {"n": 0}

        async def _flaky_create(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] <= 2:
                # A genuine transient transport error from httpx/anthropic.
                raise httpx.ConnectError("connection reset")
            return _Resp([_Block("text", text="recovered")])

        client.messages.create = _flaky_create
        provider._get_client = lambda: client  # type: ignore[method-assign]
        _wire_resilient_chat(provider)

        result = await provider.chat([Message(role="user", content="hi")])

        assert result.content == "recovered"
        assert calls["n"] == 3, "expected 2 retries before success"

    @pytest.mark.asyncio
    async def test_wrapped_permanent_failure_is_not_retried(self) -> None:
        """A permanent provider error (e.g. bad request) must fail fast — exactly
        one attempt, no retries — so we don't hammer a broken upstream."""
        provider = _provider()
        client = MagicMock()
        calls = {"n": 0}

        async def _always_bad(**kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            raise ValueError("malformed request body")

        client.messages.create = _always_bad
        provider._get_client = lambda: client  # type: ignore[method-assign]
        _wire_resilient_chat(provider)

        with pytest.raises(ProviderError):
            await provider.chat([Message(role="user", content="hi")])
        assert calls["n"] == 1, "permanent error must not be retried"


class TestErrorClassification:
    def test_raw_timeout_maps_to_transient(self) -> None:
        provider = _provider()
        mapped = provider._to_provider_error(TimeoutError("slow"))
        assert isinstance(mapped, TransientProviderError)

    def test_raw_connection_error_maps_to_transient(self) -> None:
        provider = _provider()
        mapped = provider._to_provider_error(ConnectionResetError("reset"))
        assert isinstance(mapped, TransientProviderError)

    def test_sdk_connection_error_maps_to_transient(self) -> None:
        from anthropic import APIConnectionError

        provider = _provider()
        exc = APIConnectionError(request=httpx.Request("POST", "http://x"))
        mapped = provider._to_provider_error(exc)
        assert isinstance(mapped, TransientProviderError)

    def test_httpx_transport_error_maps_to_transient(self) -> None:
        # httpx transport errors are NOT builtin OSError subclasses and the
        # anthropic SDK can let them escape raw — they must still be retryable.
        provider = _provider()
        for exc in (
            httpx.ConnectError("refused"),
            httpx.ReadTimeout("read timed out"),
            httpx.ConnectTimeout("connect timed out"),
        ):
            mapped = provider._to_provider_error(exc)
            assert isinstance(mapped, TransientProviderError), exc

    def test_value_error_maps_to_plain_provider_error(self) -> None:
        provider = _provider()
        mapped = provider._to_provider_error(ValueError("bad"))
        assert isinstance(mapped, ProviderError)
        assert not isinstance(mapped, TransientProviderError)


# ---------------------------------------------------------------------------
# HIGH — the AsyncAnthropic client must be built once and reused (+ closeable)
# ---------------------------------------------------------------------------


class TestClientReuse:
    def test_get_client_returns_same_instance(self) -> None:
        # Pre-fix _get_client constructed a brand-new client every call, leaking
        # a fresh httpx pool per turn. It must now return one cached instance.
        provider = _provider()
        first = provider._get_client()
        second = provider._get_client()
        assert first is second

    @pytest.mark.asyncio
    async def test_chat_constructs_async_anthropic_only_once(self) -> None:
        """Two chat() calls must allocate exactly one AsyncAnthropic (one httpx
        pool). Pre-fix every call rebuilt the client, leaking a pool per turn."""
        import anthropic

        constructed = {"n": 0}
        real_init = anthropic.AsyncAnthropic.__init__

        def _spy_init(self, **kwargs):  # type: ignore[no-untyped-def]
            constructed["n"] += 1
            real_init(self, **kwargs)
            # Stub the network on the freshly built client.
            self.messages = MagicMock()
            self.messages.create = AsyncMock(
                return_value=_Resp([_Block("text", text="ok")])
            )

        anthropic.AsyncAnthropic.__init__ = _spy_init  # type: ignore[method-assign]
        try:
            provider = _provider()
            await provider.chat([Message(role="user", content="a")])
            await provider.chat([Message(role="user", content="b")])
        finally:
            anthropic.AsyncAnthropic.__init__ = real_init  # type: ignore[method-assign]

        assert constructed["n"] == 1, "client must be constructed exactly once"

    @pytest.mark.asyncio
    async def test_aclose_closes_and_resets_client(self) -> None:
        provider = _provider()
        fake_client = MagicMock()
        fake_client.close = AsyncMock()
        provider._client = fake_client

        await provider.aclose()

        fake_client.close.assert_awaited_once()
        assert provider._client is None
        # Idempotent: a second close is a no-op (no AttributeError).
        await provider.aclose()


# ---------------------------------------------------------------------------
# MEDIUM — a request timeout must be supplied (no ~600s hangs)
# ---------------------------------------------------------------------------


class TestRequestTimeout:
    @pytest.mark.asyncio
    async def test_default_timeout_is_passed_to_create(self) -> None:
        provider = _provider()
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=_Resp([_Block("text", text="ok")]))
        provider._get_client = lambda: client  # type: ignore[method-assign]

        await provider.chat([Message(role="user", content="hi")])

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["timeout"] == _DEFAULT_TIMEOUT_SECONDS
        # Sanity: the SDK default (600s) must NOT be what we send.
        assert kwargs["timeout"] < 600

    @pytest.mark.asyncio
    async def test_config_timeout_overrides_default(self) -> None:
        provider = _provider()
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=_Resp([_Block("text", text="ok")]))
        provider._get_client = lambda: client  # type: ignore[method-assign]

        await provider.chat(
            [Message(role="user", content="hi")],
            config=GenerateConfig(timeout_seconds=7),
        )

        assert client.messages.create.call_args.kwargs["timeout"] == 7

    def test_client_constructor_gets_timeout_and_no_sdk_retries(self) -> None:
        # The constructed client must carry a finite timeout and disable the
        # SDK's own retries (resilience.RetryPolicy owns retrying).
        captured: dict[str, object] = {}

        provider = _provider()

        import anthropic

        real_init = anthropic.AsyncAnthropic.__init__

        def _spy_init(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            real_init(self, **kwargs)

        anthropic.AsyncAnthropic.__init__ = _spy_init  # type: ignore[method-assign]
        try:
            provider._get_client()
        finally:
            anthropic.AsyncAnthropic.__init__ = real_init  # type: ignore[method-assign]

        assert captured["timeout"] == _DEFAULT_TIMEOUT_SECONDS
        assert captured["max_retries"] == 0
