# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden OpenChatShop for single-node production: reliability, observability, business capability, infrastructure.

**Architecture:** 4 parallel streams touching non-overlapping files (except `app.py` merged at end). Each stream produces independently testable code. Final integration task merges shared files and runs full test suite.

**Tech Stack:** Python 3.11+, FastAPI, prometheus-client, Redis Sorted Sets, Locust, GitHub Actions, Docker multi-stage build.

---

## Stream 1: Reliability

### Task 1: Circuit Breaker + Retry Policy

**Files:**
- Create: `src/open_chat_shop/core/resilience.py`
- Test: `tests/unit/test_resilience.py`

- [ ] **Step 1: Write failing tests for CircuitBreaker**

```python
# tests/unit/test_resilience.py
"""Tests for circuit breaker and retry policy."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from open_chat_shop.core.resilience import CircuitBreaker, CircuitState, RetryPolicy


class TestCircuitBreaker:
    @pytest.fixture
    def cb(self) -> CircuitBreaker:
        return CircuitBreaker(failure_threshold=3, recovery_timeout=0.5)

    @pytest.mark.asyncio
    async def test_starts_closed(self, cb: CircuitBreaker) -> None:
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_succeeds_when_closed(self, cb: CircuitBreaker) -> None:
        fn = AsyncMock(return_value="ok")
        result = await cb.call(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, cb: CircuitBreaker) -> None:
        fn = AsyncMock(side_effect=Exception("fail"))
        for _ in range(3):
            with pytest.raises(Exception):
                await cb.call(fn)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self, cb: CircuitBreaker) -> None:
        fn = AsyncMock(side_effect=Exception("fail"))
        for _ in range(3):
            with pytest.raises(Exception):
                await cb.call(fn)
        with pytest.raises(Exception, match="circuit open"):
            await cb.call(AsyncMock(return_value="ok"))

    @pytest.mark.asyncio
    async def test_half_open_after_recovery_timeout(self, cb: CircuitBreaker) -> None:
        fn = AsyncMock(side_effect=Exception("fail"))
        for _ in range(3):
            with pytest.raises(Exception):
                await cb.call(fn)
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.6)
        good_fn = AsyncMock(return_value="recovered")
        result = await cb.call(good_fn)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_succeeds_immediately(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        fn = AsyncMock(return_value="ok")
        result = await policy.execute(fn)
        assert result == "ok"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        fn = AsyncMock(side_effect=[TimeoutError("t"), TimeoutError("t"), "ok"])
        result = await policy.execute(fn)
        assert result == "ok"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        fn = AsyncMock(side_effect=TimeoutError("t"))
        with pytest.raises(TimeoutError):
            await policy.execute(fn)
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_non_retryable(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        fn = AsyncMock(side_effect=ValueError("bad"))
        with pytest.raises(ValueError):
            await policy.execute(fn)
        assert fn.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_resilience.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement CircuitBreaker and RetryPolicy**

```python
# src/open_chat_shop/core/resilience.py
"""Circuit breaker and retry policy for resilient LLM calls."""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open."""


class CircuitBreaker:
    """Prevents cascading failures by opening after consecutive failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                else:
                    raise CircuitOpenError(
                        f"circuit open (failures={self._failure_count})"
                    )

            if (
                self._state == CircuitState.HALF_OPEN
                and self._half_open_calls >= self._half_open_max
            ):
                raise CircuitOpenError("circuit open (half-open limit reached)")

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            await self._on_failure()
            raise
        await self._on_success()
        return result

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("circuit breaker opened (failures=%d)", self._failure_count)
            elif self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("circuit breaker closed after successful half-open")
            self._failure_count = 0

    @property
    def failure_count(self) -> int:
        return self._failure_count


_RETRYABLE = (TimeoutError, ConnectionError, OSError)


class RetryPolicy:
    """Exponential backoff retry for transient failures."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
        exponential_base: float = 2.0,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._exponential_base = exponential_base

    async def execute(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = min(
                        self._base_delay * (self._exponential_base ** attempt),
                        self._max_delay,
                    )
                    logger.info(
                        "retry attempt %d/%d after %.1fs: %s",
                        attempt + 1, self._max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
            except Exception:
                raise
        raise last_exc  # type: ignore[misc]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_resilience.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/open_chat_shop/core/resilience.py tests/unit/test_resilience.py
git commit -m "feat: add circuit breaker and retry policy for resilient LLM calls"
```

---

### Task 2: Graceful Shutdown (Lifespan)

**Files:**
- Modify: `main.py:353-373`
- Test: `tests/unit/test_lifespan.py`

- [ ] **Step 1: Write test for lifespan**

```python
# tests/unit/test_lifespan.py
"""Tests for FastAPI lifespan (graceful shutdown)."""
from __future__ import annotations

from fastapi.testclient import TestClient


class TestLifespan:
    def test_health_endpoint_works(self) -> None:
        from main import create_main_app
        app = create_main_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
```

- [ ] **Step 2: Implement lifespan in main.py**

Modify `create_main_app()` to use FastAPI lifespan context manager. Pass `lifespan` param to `create_app()`. Add `lifespan` param to `create_app` in `app.py`. Change `uvicorn.run` to use app object directly with `timeout_graceful_shutdown=10`.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_lifespan.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add main.py src/open_chat_shop/api/app.py tests/unit/test_lifespan.py
git commit -m "feat: graceful shutdown via FastAPI lifespan context manager"
```

---

### Task 3: Enhanced Health Checks

**Files:**
- Modify: `src/open_chat_shop/api/app.py:100-105`
- Test: `tests/unit/test_health.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_health.py
"""Tests for enhanced health check endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


class TestHealthEndpoints:
    def test_liveness_returns_ok(self) -> None:
        from open_chat_shop.api.app import create_app
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_readiness_returns_checks(self) -> None:
        from open_chat_shop.api.app import create_app
        client = TestClient(create_app())
        resp = client.get("/health/ready")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "checks" in data
        assert "status" in data
        assert "uptime_seconds" in data
```

- [ ] **Step 2: Implement `/health/ready` in app.py**

Add `ReadyResponse` model, `_check_database`, `_check_redis` helpers, and `/health/ready` endpoint. Health checker reads db_engine and redis_client from app.state.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_health.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/open_chat_shop/api/app.py tests/unit/test_health.py
git commit -m "feat: enhanced health checks with readiness probe"
```

---

## Stream 2: Observability

### Task 4: Prometheus Metrics Module

**Files:**
- Create: `src/open_chat_shop/observability/metrics.py`
- Test: `tests/unit/test_metrics.py`
- Modify: `pyproject.toml` (add prometheus-client dependency)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_metrics.py
"""Tests for Prometheus metrics."""
from open_chat_shop.observability.metrics import (
    record_chat_request,
    record_llm_call,
    record_tool_call,
    get_metrics_content,
)


class TestMetrics:
    def test_record_chat_request(self) -> None:
        record_chat_request(intent="query_order", status="success")
        content = get_metrics_content()
        assert b"openchatshop_chat_requests_total" in content

    def test_record_llm_call(self) -> None:
        record_llm_call(model="gpt-4o-mini", status="success", prompt_tokens=10, completion_tokens=20)
        content = get_metrics_content()
        assert b"openchatshop_llm_calls_total" in content

    def test_record_tool_call(self) -> None:
        record_tool_call(tool="query_order", status="success")
        content = get_metrics_content()
        assert b"openchatshop_tool_calls_total" in content
```

- [ ] **Step 2: Implement metrics module**

Create `src/open_chat_shop/observability/metrics.py` with:
- Counters: `openchatshop_chat_requests_total`, `openchatshop_llm_calls_total`, `openchatshop_llm_tokens_total`, `openchatshop_llm_cost_usd_total`, `openchatshop_tool_calls_total`, `openchatshop_cache_hits_total`
- Histogram: `openchatshop_chat_duration_seconds` (buckets: 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
- Gauges: `openchatshop_active_sessions`, `openchatshop_handoff_queue_size`
- Helper functions: `record_chat_request`, `observe_chat_duration`, `record_llm_call`, `record_tool_call`, `get_metrics_content`
- ASGI `metrics_app` for `/metrics` endpoint

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_metrics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/open_chat_shop/observability/metrics.py tests/unit/test_metrics.py pyproject.toml
git commit -m "feat: add Prometheus metrics module"
```

---

### Task 5: Grafana + Prometheus Monitoring Stack

**Files:**
- Create: `monitoring/prometheus.yml`
- Create: `monitoring/prometheus/alerts.yml`
- Create: `monitoring/grafana/datasources/prometheus.yml`
- Create: `monitoring/grafana/dashboards/openchatshop.json`
- Modify: `docker-compose.yml` (add services)

- [ ] **Step 1: Create monitoring configs**

Create Prometheus scrape config, alert rules (HighErrorRate, HighLatency, QueueBacklog), Grafana datasource provisioning, and dashboard JSON.

- [ ] **Step 2: Add services to docker-compose.yml**

Add `prometheus` and `grafana` services with volume mounts and `restart: unless-stopped`.

- [ ] **Step 3: Commit**

```bash
git add monitoring/ docker-compose.yml
git commit -m "feat: add Prometheus + Grafana monitoring stack"
```

---

### Task 6: Trace ID Propagation Fix

**Files:**
- Modify: `src/open_chat_shop/core/orchestrator.py`
- Test: `tests/unit/test_trace_propagation.py`

- [ ] **Step 1: Add `_trace_extras` helper to DialogueOrchestrator**

Method reads current span context from OTel and returns `{"trace_id": ..., "span_id": ..., "session_id": ...}` dict.

- [ ] **Step 2: Update key logger calls to use trace extras**

Security blocked (line 134), topic switch (line 189), LLM enhancement failures.

- [ ] **Step 3: Commit**

```bash
git add src/open_chat_shop/core/orchestrator.py tests/unit/test_trace_propagation.py
git commit -m "fix: propagate trace_id and span_id into structured logs"
```

---

## Stream 3: Business Capability

### Task 7: Redis Rate Limiter

**Files:**
- Modify: `src/open_chat_shop/core/rate_limiter.py`
- Test: `tests/unit/test_redis_rate_limiter.py`

- [ ] **Step 1: Write failing tests**

Tests for `RedisRateLimiter` (mock redis.eval returning [1, 29] or [0, 0]), `RateLimitGuard` auto-detection (with/without redis_client).

- [ ] **Step 2: Implement RedisRateLimiter**

Add Lua sliding window script, `RedisRateLimiter` class with `check_and_consume` using `redis.eval`, fallback to allow on Redis failure. Update `RateLimitGuard.__init__` to accept optional `redis_client`.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_redis_rate_limiter.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/open_chat_shop/core/rate_limiter.py tests/unit/test_redis_rate_limiter.py
git commit -m "feat: add Redis-backed rate limiter with Lua sliding window"
```

---

### Task 8: Response Cache

**Files:**
- Create: `src/open_chat_shop/core/cache.py`
- Test: `tests/unit/test_cache.py`

- [ ] **Step 1: Write failing tests**

Tests for cache miss, set/get, different params, invalidation, mutable intents not cached.

- [ ] **Step 2: Implement ResponseCache**

`ResponseCache` with `_make_key` (hash sorted params), TTL per intent (search_product: 300s, query_order: 60s, query_logistics: 30s), no-cache for mutable intents, Redis + memory backends.

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/unit/test_cache.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/open_chat_shop/core/cache.py tests/unit/test_cache.py
git commit -m "feat: add response cache for read-only query intents"
```

---

### Task 9: Load Test Baseline

**Files:**
- Create: `tests/load/locustfile.py`
- Create: `tests/load/README.md`
- Modify: `pyproject.toml` (add locust to dev deps)

- [ ] **Step 1: Create locustfile with 4 user classes**

ChatUser, OrderQuerier, ProductSearcher, MixedWorkload (70/20/10).

- [ ] **Step 2: Add locust to dev dependencies**

- [ ] **Step 3: Commit**

```bash
git add tests/load/ pyproject.toml
git commit -m "feat: add Locust load test scenarios"
```

---

## Stream 4: Infrastructure

### Task 10: GitHub Actions CI Pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow with 5 parallel jobs**

lint (ruff), type-check (mypy), test (Python 3.11+3.12 matrix), frontend (npm build), docker (build verification).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "feat: add GitHub Actions CI pipeline"
```

---

### Task 11: Docker Security Hardening

**Files:**
- Modify: `Dockerfile` (full rewrite to multi-stage)
- Create: `.dockerignore`
- Modify: `docker-compose.yml` (security hardening)

- [ ] **Step 1: Rewrite Dockerfile**

Two stages: builder (gcc + pip install) and runtime (copy wheels, add non-root user, HEALTHCHECK).

- [ ] **Step 2: Create .dockerignore**

Exclude `.venv/`, `node_modules/`, `.git/`, `.env`, `data/`, etc.

- [ ] **Step 3: Harden docker-compose.yml**

Remove DB/Redis port exposure, add restart policy, parameterize credentials, add resource limits.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat: Docker multi-stage build, non-root user, compose hardening"
```

---

### Task 12: Security Headers + CORS

**Files:**
- Modify: `src/open_chat_shop/api/app.py`

- [ ] **Step 1: Add SecurityHeadersMiddleware**

X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, CSP, HSTS (HTTPS only).

- [ ] **Step 2: Update CORS to read CORS_ORIGINS env var**

Default: `["http://localhost:3000", "http://localhost:8000"]`. Replace `allow_origins=["*"]`.

- [ ] **Step 3: Commit**

```bash
git add src/open_chat_shop/api/app.py
git commit -m "feat: add security headers middleware and configurable CORS"
```

---

## Integration

### Task 13: Wire Everything + Full Test Suite

**Files:**
- Modify: `main.py` (wire resilience, cache, Redis rate limiter)
- Modify: `src/open_chat_shop/api/app.py` (mount /metrics)

- [ ] **Step 1: Mount /metrics endpoint**

- [ ] **Step 2: Wire circuit breaker + retry around LLM provider in main.py**

- [ ] **Step 3: Wire Redis rate limiter in main.py**

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All 791+ tests PASS

- [ ] **Step 5: Commit**

```bash
git add main.py src/open_chat_shop/api/app.py
git commit -m "feat: wire resilience, Redis rate limiter, and metrics endpoint"
```
