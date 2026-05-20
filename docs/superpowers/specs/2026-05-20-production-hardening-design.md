# Production Hardening Design — Minimal Viable Production

**Date:** 2026-05-20
**Scope:** Reliability, Observability, Business Capability, Infrastructure
**Approach:** 4 parallel streams, merge shared files at the end
**Target:** Single-node production-safe deployment

---

## Overview

Four parallel workstreams, each touching non-overlapping files (except `app.py`, merged last).

| Stream | Focus | Key Files |
|--------|-------|-----------|
| 1 | Reliability | `app.py` (health), `main.py` (lifespan), new `resilience.py` |
| 2 | Observability | new `metrics.py`, new `monitoring/`, `orchestrator.py` (trace fix) |
| 3 | Business Capability | `rate_limiter.py`, new `cache.py`, new `tests/load/` |
| 4 | Infrastructure | new `.github/`, `Dockerfile`, new `.dockerignore`, `app.py` (security) |

---

## Stream 1: Reliability

### 1a. Health Check Enhancement

**Current:** `/health` returns `{"status": "ok", "version": "0.1.0"}` with no dependency checks.

**Target:**
- `/health` — liveness probe (always returns 200 if process is up)
- `/health/ready` — readiness probe (checks DB, Redis, LLM provider)
- Response structure:
  ```json
  {
    "status": "ok|degraded|unhealthy",
    "version": "0.1.0",
    "checks": {
      "database": {"status": "ok", "latency_ms": 3},
      "redis": {"status": "ok", "latency_ms": 1},
      "llm": {"status": "degraded", "provider": "anthropic", "last_error": "timeout"}
    },
    "uptime_seconds": 3600
  }
  ```
- `status` logic: all ok -> "ok", any degraded -> "degraded", any unhealthy -> "unhealthy"
- `/health/ready` returns 503 when status is "unhealthy"

**Implementation:**
- Add `HealthChecker` class in `app.py` that accepts optional engine, redis_client, provider references
- LLM health: no actual API call -- check provider capability flag + last error timestamp (within 5 min = degraded)
- DB health: `SELECT 1` via engine
- Redis health: `PING` command
- Track start_time for uptime_seconds

### 1b. Graceful Shutdown

**Current:** No signal handling, no lifespan events. Uvicorn kills process on SIGTERM.

**Target:**
- FastAPI `lifespan` context manager in `main.py`:
  - Startup: record start_time, log component initialization
  - Shutdown: drain WebSocket connections (close with 1001 going-away), close Redis client (`await redis.aclose()`), dispose DB engine (`engine.dispose()`), log shutdown complete
- Grace period: 10 seconds (uvicorn `timeout-graceful-shutdown=10`)
- Replace `uvicorn.run("main:app", reload=True)` with `uvicorn.run(app, ...)` using the built app object + production settings

**Implementation:**
- Modify `main.py` to use `@asynccontextmanager` lifespan pattern
- Pass lifespan to `create_app()` as parameter
- Store redis_client and engine references in app.state for cleanup

### 1c. Circuit Breaker + Retry

**Current:** `CascadeStrategy` falls back across providers but does not retry the same provider. No circuit breaker.

**Target:**
- New file: `src/open_chat_shop/core/resilience.py`
- `CircuitBreaker` class:
  - States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
  - Configurable: `failure_threshold=5`, `recovery_timeout=30`, `half_open_max=1`
  - Thread-safe via asyncio Lock
  - `async def call(fn, *args, **kwargs)` -- wraps any async function
- `RetryPolicy` class:
  - Configurable: `max_retries=3`, `base_delay=1.0`, `max_delay=8.0`, `exponential_base=2`
  - Retryable exceptions: timeout, 429 (rate limit), 503 (service unavailable), connection errors
  - Non-retryable: auth errors, validation errors, circuit open
  - `async def execute(fn, *args, **kwargs)` -- wraps with retry + backoff
- Integration: wrap provider calls in orchestrator:
  ```python
  resilient_chat = circuit_breaker(retry(provider.chat))
  ```
- Wire in `main.py` per-provider, before cascade

---

## Stream 2: Observability

### 2a. Prometheus Metrics

**Current:** No metrics collection. OTel tracing exists but uses ConsoleSpanExporter.

**Target:**
- New file: `src/open_chat_shop/observability/metrics.py`
- New dependency: `prometheus-client>=0.20` in `pyproject.toml`
- Metrics:

| Name | Type | Labels | Description |
|------|------|--------|-------------|
| `openchatshop_chat_requests_total` | Counter | intent, status | Total chat requests |
| `openchatshop_chat_duration_seconds` | Histogram | intent | Request latency |
| `openchatshop_llm_calls_total` | Counter | model, status | LLM API calls |
| `openchatshop_llm_tokens_total` | Counter | model, type (prompt/completion) | Token usage |
| `openchatshop_llm_cost_usd_total` | Counter | model | Cumulative cost |
| `openchatshop_active_sessions` | Gauge | -- | Current active sessions |
| `openchatshop_tool_calls_total` | Counter | tool, status | Tool invocations |
| `openchatshop_handoff_queue_size` | Gauge | -- | Pending handoff requests |

- Histogram buckets: `[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]`
- `/metrics` endpoint via `prometheus_client.make_asgi_app()` mounted on FastAPI
- Instrument points: orchestrator handle_message (chat metrics), provider chat (LLM metrics), tool execute (tool metrics), handoff queue (gauge)

### 2b. Grafana + Prometheus Stack

**Current:** None.

**Target:**
- New directory: `monitoring/`
  - `monitoring/prometheus.yml` -- scrape config targeting `agent-api:8000`
  - `monitoring/grafana/datasources/prometheus.yml` -- auto-provisioned data source
  - `monitoring/grafana/dashboards/openchatshop.json` -- pre-built dashboard with panels:
    - Request rate by intent (time series)
    - P50/P95/P99 latency (time series)
    - Error rate percentage (stat panel)
    - LLM cost over time (time series)
    - Token usage by model (stacked bar)
    - Active sessions (gauge)
    - Tool call distribution (pie chart)
    - Handoff queue size (gauge)
  - `monitoring/prometheus/alerts.yml` -- alert rules:
    - `HighErrorRate`: error rate > 1% for 5 min
    - `HighLatency`: P99 > 3s for 5 min
    - `LLMCostSpike`: hourly cost > 2x daily average
    - `QueueBacklog`: handoff queue > 50 for 5 min
- `docker-compose.yml` additions:
  - `prometheus` service (image: `prom/prometheus:v2.51.0`, mount config)
  - `grafana` service (image: `grafana/grafana:10.4.0`, mount dashboards + datasources, admin password via env)

### 2c. Trace ID Propagation Fix

**Current:** `StructuredFormatter` supports trace_id/span_id fields but no code populates them.

**Target:**
- In `orchestrator.py`, within each traced span, inject trace context into log calls:
  ```python
  span = trace.get_current_span()
  ctx = span.get_span_context()
  logger.info("...", extra={"trace_id": format(ctx.trace_id, '032x'), "span_id": format(ctx.span_id, '016x')})
  ```
- Apply to the top-level `handle_message` span and key sub-spans (intent, tool, security)
- This links structured logs to traces in Jaeger/Tempo

---

## Stream 3: Business Capability

### 3a. Redis Rate Limiter

**Current:** `InMemoryRateLimiter` uses a dict -- not shared across processes.

**Target:**
- Add `RedisRateLimiter` class in `rate_limiter.py`:
  - Uses Redis Sorted Sets (ZADD + ZRANGEBYSCORE + ZREMRANGEBYSCORE)
  - Atomic check+consume via Lua script:
    ```lua
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    local count = redis.call('ZCARD', key)
    if count < limit then
      redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
      redis.call('EXPIRE', key, window / 1000)
      return {1, limit - count - 1}
    else
      return {0, 0}
    end
    ```
  - Returns `RateLimitResult` (same interface as InMemory)
- `RateLimitGuard` auto-detects: constructor accepts optional `redis_client` -- if provided, use Redis limiter; otherwise fall back to InMemory
- Add response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Wire in `main.py`: pass redis_client to RateLimitGuard when available

### 3b. Response Cache

**Current:** No caching at all. Every request hits the full pipeline.

**Target:**
- New file: `src/open_chat_shop/core/cache.py`
- `ResponseCache` class:
  - Backend: Redis when available, in-memory dict otherwise
  - TTL per intent type:
    - `search_product`: 300s (5 min) -- product catalog changes infrequently
    - `query_order`: 60s (1 min) -- order status can change
    - `query_logistics`: 30s -- logistics updates frequently
    - Other intents: no cache (user-specific, mutable)
  - Cache key: `cache:{intent}:{hash(sorted(params))}`
  - Methods: `get(key) -> AgentMessage | None`, `set(key, value, ttl)`, `invalidate(pattern)`
  - Cache hit increments `openchatshop_cache_hits_total` metric
- Integration point: orchestrator `_core_handle()` -- check cache before intent classification, store result after response generation
- Cache invalidation: on tool calls that mutate data (create_refund, cancel_order, modify_address)

### 3c. Load Test Baseline

**Current:** No load testing.

**Target:**
- New directory: `tests/load/`
- New dependency: `locust>=2.20` in `pyproject.toml [dev]`
- `tests/load/locustfile.py` with scenarios:
  - `ChatUser`: sends random chat messages from golden dataset, expects 200 with valid response
  - `OrderQuerier`: sends order query messages, expects order_card response
  - `ProductSearcher`: sends product search messages, expects product_list response
  - `MixedWorkload`: 70% chat, 20% order, 10% search (realistic distribution)
- Baseline targets (documented in `tests/load/README.md`):
  - P99 latency < 2000ms
  - Throughput > 100 RPS (single instance)
  - Error rate < 0.1%
  - Memory usage stable (no leak over 10 min run)
- Run command: `locust -f tests/load/locustfile.py --host=http://localhost:8000 --headless -u 100 -r 10 -t 5m`

---

## Stream 4: Infrastructure

### 4a. GitHub Actions CI

**Current:** No CI/CD.

**Target:**
- New file: `.github/workflows/ci.yml`
- Triggers: push to main, pull_request to main
- Jobs:
  1. **lint**: `ruff check src/ tests/`
  2. **type-check**: `mypy src/`
  3. **test**:
     - Matrix: Python 3.11, 3.12
     - Steps: `pip install -e ".[dev]"`, `pytest --cov=open_chat_shop --cov-fail-under=80`
     - Upload coverage artifact
  4. **frontend**:
     - `cd frontend && npm install && npm run build`
     - Verify dist/ exists
  5. **docker**: `docker build .` (verify build succeeds)
- All jobs run in parallel (no dependencies)
- Fail-fast: if any job fails, mark PR as failing

### 4b. Docker Security Hardening

**Current:** Single-stage build, root user, no healthcheck, build deps in final image.

**Target `Dockerfile`:**
```dockerfile
# Stage 1: Builder
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY configs/ configs/
COPY static/ static/
COPY main.py ./
COPY alembic.ini ./
RUN groupadd -r appuser && useradd -r -g appuser appuser && mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
ENV PYTHONPATH=/app/src
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python", "-c", "import httpx; httpx.get('http://localhost:8000/health')"]
CMD ["python3", "main.py"]
```

**New `.dockerignore`:**
```
.venv/
node_modules/
.git/
.harness/
.claude/
.env
.env.local
data/
*.sqlite3
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
*.egg-info/
dist/
build/
```

**`docker-compose.yml` production hardening:**
- Remove port exposure for postgres (5432) and redis (6379) -- only expose app port
- Add `restart: unless-stopped` to all services
- Parameterize credentials via `${POSTGRES_USER}`, `${POSTGRES_PASSWORD}`, `${POSTGRES_DB}`
- Add Redis `requirepass` via `${REDIS_PASSWORD}`
- Add `deploy.resources.limits` for memory (app: 512MB, postgres: 256MB, redis: 128MB)

### 4c. Security Headers + CORS

**Current:** CORS `allow_origins=["*"]`, no security headers.

**Target:**
- New middleware in `app.py` (`SecurityHeadersMiddleware`):
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (only when request is HTTPS)
- CORS: read `CORS_ORIGINS` env var (comma-separated), default to `["http://localhost:3000", "http://localhost:8000"]` for development
- Remove `allow_origins=["*"]`

### 4d. API Version Prefix

**Current:** All endpoints at root (`/chat`, `/ws/chat/{session_id}`, etc.)

**Target:**
- All business endpoints mounted under `/api/v1/` prefix:
  - `/api/v1/chat` (POST)
  - `/api/v1/chat/stream` (POST, SSE)
  - `/api/v1/ws/chat/{session_id}` (WebSocket)
  - `/api/v1/ws/agent/{agent_id}` (WebSocket)
  - `/api/v1/agent/*` (Agent dashboard API)
- Health endpoints stay at root: `/health`, `/health/ready`
- Static files stay at root: `/`, `/assets/*`
- Implementation: create a sub-API with `APIRouter(prefix="/api/v1")` and mount existing routes there
- Frontend WebSocket URLs updated to match new paths

---

## Integration & Verification

After all 4 streams complete:

1. **Merge `app.py`** -- combine health check changes (stream 1) with security headers + CORS + version prefix (stream 4)
2. **Run full test suite** -- `pytest` must pass all 791+ existing tests + new tests
3. **Docker smoke test** -- `docker compose up` + `/health/ready` returns 200 + `/metrics` returns metrics
4. **Load test** -- run locust baseline, verify P99 < 2s
5. **CI verification** -- push to branch, verify GitHub Actions passes

---

## New Dependencies

```
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "prometheus-client>=0.20",    # Stream 2: Prometheus metrics
]

[project.optional-dependencies]
dev = [
    # ... existing ...
    "locust>=2.20",               # Stream 3: Load testing
]
```

---

## Files Changed Summary

| File | Stream | Action |
|------|--------|--------|
| `src/open_chat_shop/core/resilience.py` | 1 | **New** -- CircuitBreaker + RetryPolicy |
| `src/open_chat_shop/core/cache.py` | 3 | **New** -- ResponseCache |
| `src/open_chat_shop/observability/metrics.py` | 2 | **New** -- Prometheus metrics |
| `monitoring/prometheus.yml` | 2 | **New** -- Prometheus scrape config |
| `monitoring/grafana/datasources/prometheus.yml` | 2 | **New** -- Grafana datasource |
| `monitoring/grafana/dashboards/openchatshop.json` | 2 | **New** -- Grafana dashboard |
| `monitoring/prometheus/alerts.yml` | 2 | **New** -- Alert rules |
| `tests/load/locustfile.py` | 3 | **New** -- Locust load tests |
| `tests/load/README.md` | 3 | **New** -- Load test baseline docs |
| `.github/workflows/ci.yml` | 4 | **New** -- CI pipeline |
| `.dockerignore` | 4 | **New** -- Docker build exclusions |
| `src/open_chat_shop/api/app.py` | 1+4 | **Modify** -- Health checks + security headers + CORS + version prefix |
| `main.py` | 1 | **Modify** -- Lifespan + resilience wiring |
| `src/open_chat_shop/core/orchestrator.py` | 2 | **Modify** -- trace_id injection in logs |
| `src/open_chat_shop/core/rate_limiter.py` | 3 | **Modify** -- Add RedisRateLimiter |
| `Dockerfile` | 4 | **Modify** -- Multi-stage build + non-root user |
| `docker-compose.yml` | 2+4 | **Modify** -- Prometheus + Grafana services + security hardening |
| `pyproject.toml` | 2+3 | **Modify** -- New dependencies |
