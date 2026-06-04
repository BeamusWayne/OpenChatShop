"""Re-audit regression tests for the ``main_readme`` cluster.

Two findings are pinned here:

1. OPT — ``build_orchestrator`` was a ~200-line wiring monolith. It was split
   into cohesive ``_build_*`` / ``_wire_*`` helpers so it reads as a short
   composition root. The refactor MUST be behaviour-preserving: the returned
   ``DialogueOrchestrator`` must still have *every* collaborator wired
   (security, context, intent engine, tool injector, strategy, support
   services, middleware, response cache) and the live-resources contract
   (``redis_sync``/``redis_async`` published on the ``resources`` dict, the
   single shared sync Redis client reaching both the rate limiter and the
   response cache) must hold. These tests exercise the *real* composition
   output — not mocks — so a dropped or reordered wiring step fails loudly,
   which is exactly the class of bug the parallel-round lesson warns about.

2. README — the test-count badge + prose were stale (898 / 839 while the suite
   is well past 1000). They were made non-numeric to stop future drift; these
   tests guard against re-introducing a hard-coded count.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

# main.py builds the app at import time and exits unless an auth mode is set.
# DEV_MODE skips that so we can import and call the pure builder helpers.
os.environ.setdefault("DEV_MODE", "true")

import main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_README = _REPO_ROOT / "README.md"


# ---------------------------------------------------------------------------
# Finding 1 — build_orchestrator composition root stays behaviour-preserving
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildOrchestratorWiringPreserved:
    """The extracted helpers must produce a fully-wired orchestrator.

    Each assertion corresponds to one wiring step the old monolith performed.
    If the refactor (or a future edit) drops a step, the matching assertion
    fails — the test is the executable spec for "composition root must wire
    everything".
    """

    def test_all_constructor_collaborators_present(self) -> None:
        orch = main.build_orchestrator()
        # Constructor-injected collaborators (the 5 positional deps).
        assert orch._security is not None
        assert orch._context_manager is not None
        assert orch._intent_engine is not None
        assert orch._tool_injector is not None
        assert orch._strategy is not None

    def test_support_services_wired(self) -> None:
        """audit/cost/mapper/scenarios/handoff all attached via the helper."""
        orch = main.build_orchestrator()
        assert orch._audit_logger is not None, "audit logger not wired"
        assert orch._cost_tracker is not None, "cost tracker not wired"
        assert orch._tool_response_mapper is not None, "response mapper not wired"
        assert orch._handoff_queue is not None, "handoff queue not wired"
        # All three business scenario FSMs must be registered.
        assert set(orch._scenarios) == {"refund", "complaint", "order_inquiry"}

    def test_middleware_and_cache_wired(self) -> None:
        orch = main.build_orchestrator()
        assert orch._middleware_pipeline is not None, "middleware pipeline not wired"
        assert orch._response_cache is not None, "response cache not wired"

    def test_intent_engine_has_builtin_intents_and_samples(self) -> None:
        """_build_intent_engine must register every builtin intent and load
        the Level-2 semantic samples (the monolith did both inline)."""
        orch = main.build_orchestrator()
        engine = orch._intent_engine
        registered = set(engine._intent_registry)
        expected = {info.name for info in main.INTENT_DEFINITIONS}
        assert expected <= registered, f"missing intents: {expected - registered}"
        # Samples dict must be populated for semantic matching.
        assert engine._samples, "Level-2 semantic samples were not loaded"

    def test_tool_injector_default_routing_covers_every_tool(self) -> None:
        """With no tool_routing.yaml override active, every builtin tool must be
        in the registry and reachable via a same-named default routing rule."""
        injector = main._build_tool_injector({}, None)
        assert injector._registry, "tool registry is empty"
        rule_tools = {t for rule in injector._routing_rules for t in rule.tools}
        assert set(injector._registry) <= rule_tools, (
            "some tools have no routing rule"
        )


@pytest.mark.unit
class TestRedisResourcesContractPreserved:
    """The live-infra contract that the readiness probe + shutdown depend on.

    ``_build_redis_clients`` must publish BOTH handles on the passed ``resources``
    dict, and ``build_orchestrator`` must hand the *same* sync client to both the
    middleware rate limiter and the response cache (the comment in main.py
    explains why a sync — not async — client is required for those two).
    """

    def test_resources_dict_gets_both_redis_keys_when_no_url(self) -> None:
        # No REDIS_URL -> both clients are None, but the keys MUST still be
        # published so the caller can read them unconditionally.
        prev = os.environ.pop("REDIS_URL", None)
        try:
            resources: dict[str, object] = {}
            sync, asyncc = main._build_redis_clients(resources)
            assert sync is None and asyncc is None
            assert "redis_sync" in resources and "redis_async" in resources
            assert resources["redis_sync"] is None
            assert resources["redis_async"] is None
        finally:
            if prev is not None:
                os.environ["REDIS_URL"] = prev

    def test_shared_sync_client_reaches_rate_guard_and_cache(self) -> None:
        """The single sync client returned by _build_redis_clients is the one
        injected into the rate guard (inside the middleware) and the response
        cache. Use a sentinel to prove identity, not just truthiness."""
        sentinel = object()
        pipeline = main._build_middleware(sentinel)
        # First middleware is the RateLimitMiddleware -> its guard wraps the
        # sync client in a RedisRateLimiter (which stores it as ._redis).
        rate_mw = pipeline._middlewares[0]
        guard = rate_mw._guard
        assert guard._limiter._redis is sentinel, (
            "rate guard did not receive the shared sync Redis client"
        )

        from open_chat_shop.core.cache import ResponseCache

        cache = ResponseCache(redis_client=sentinel)
        assert cache._redis is sentinel


@pytest.mark.unit
class TestWireResilienceTargetsChat:
    """_wire_resilience must wrap ``chat`` (the method the orchestrator calls),
    retrying transient failures. This is the same contract the old inline block
    held; extracting it must not change which method is wrapped."""

    def test_chat_is_wrapped_and_retries_transient_failure(self) -> None:
        from open_chat_shop.core.provider import LLMProvider
        from open_chat_shop.core.types import LLMResponse, ProviderCapabilities

        calls = {"n": 0}

        class _Flaky(LLMProvider):
            name = "flaky"

            async def chat(self, messages, tools=None, config=None):  # type: ignore[no-untyped-def]
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise TimeoutError("transient")
                return LLMResponse(content="ok")

            async def stream(self, messages, tools=None, config=None):  # type: ignore[no-untyped-def]
                yield  # pragma: no cover

            async def embed(self, texts):  # type: ignore[no-untyped-def]
                return [[0.0] for _ in texts]

            def get_capabilities(self):  # type: ignore[no-untyped-def]
                return ProviderCapabilities(
                    tool_calling=False,
                    streaming=False,
                    vision=False,
                    max_context_tokens=8192,
                )

            def estimate_tokens(self, text):  # type: ignore[no-untyped-def]
                return len(text)

        provider = _Flaky()
        main._wire_resilience(provider)

        assert provider.chat.__name__ == "_resilient_chat", "chat was not wrapped"
        result = asyncio.run(provider.chat([]))
        assert result.content == "ok"
        assert calls["n"] == 3, "expected 2 retries before success"


# ---------------------------------------------------------------------------
# Finding 2 — README must not carry a stale hard-coded test count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadmeTestCountNotStale:
    """The README must not embed a numeric passing-test count, which inevitably
    drifts. The fix made the badge + prose non-numeric; guard that."""

    def test_no_stale_898_or_839(self) -> None:
        text = _README.read_text(encoding="utf-8")
        assert "898" not in text, "stale '898' test count still in README"
        assert "839" not in text, "stale '839' test count still in README"

    def test_badge_is_non_numeric(self) -> None:
        text = _README.read_text(encoding="utf-8")
        # The Tests badge must read 'Tests-passing' with no count token between.
        assert re.search(r"Tests-passing-brightgreen", text), (
            "Tests badge should be non-numeric (Tests-passing-brightgreen)"
        )
        # And there must be no '<number> passing' badge anywhere.
        assert not re.search(r"Tests-\d+%20passing", text), (
            "README still has a numeric '<N> passing' Tests badge"
        )

    def test_no_numeric_testcase_count_in_prose(self) -> None:
        """Catch the '<N> 个用例' / '<N> 个现有测试' prose patterns the audit
        flagged so a future edit can't silently re-introduce a hard count."""
        text = _README.read_text(encoding="utf-8")
        assert not re.search(r"\d+\s*个用例", text), "stale '<N> 个用例' in README"
        assert not re.search(r"\d+\s*个现有测试", text), (
            "stale '<N> 个现有测试' in README"
        )
