"""Gunicorn configuration for production deployment."""
import multiprocessing  # noqa: F401  (kept for ops reference; see worker note below)
import os

# Server socket
bind = f"{os.environ.get('APP_HOST', '0.0.0.0')}:{os.environ.get('APP_PORT', '8000')}"

# ---------------------------------------------------------------------------
# Worker processes — SINGLE WORKER IS THE SAFE DEFAULT.
# ---------------------------------------------------------------------------
# The human-handoff / agent-dashboard subsystem keeps ALL of its live state in
# per-process Python objects created inside create_app():
#   - WebSocket registries  (_agent_sockets / _customer_sockets, app.py)
#   - session mode + message buffers (_session_modes / _session_messages)
#   - HandoffQueue (_agents / _queue / _active_transfers, handoff.py)
#   - InMemoryRateLimiter / SessionBudgetManager
# With preload_app=True each gunicorn worker forks its OWN independent copy of
# this state, and they NEVER converge. Under >1 worker, a customer WS that
# lands on worker A while the agent WS / REST accept land on worker B silently
# drops every agent reply, partitions the queue, and makes behaviour depend on
# OS request routing — a data-loss/correctness hole on a normal path.
#
# Until the shared-state work lands (Redis pub/sub WS fan-out + Redis-backed
# handoff queue / agent registry / rate limiter), running more than one worker
# is UNSAFE. See docs/production-hardening-audit.md (C-01..C-04, multi-worker
# coordination) for the required backend work. Scale this process via async
# concurrency (a single UvicornWorker handles many concurrent connections), or
# run multiple single-worker replicas behind a Redis-backed shared state once
# that exists.
#
# GUNICORN_WORKERS can override this, but doing so without the shared backend
# WILL break human handoff; we log a loud warning when it is set above 1.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
if workers > 1:
    import logging

    logging.getLogger("gunicorn.error").warning(
        "GUNICORN_WORKERS=%d (>1) with per-process in-memory handoff/socket "
        "state: human handoff WILL break (dropped agent replies, partitioned "
        "queue). Pin GUNICORN_WORKERS=1 until the Redis-backed shared-state "
        "work lands — see docs/production-hardening-audit.md.",
        workers,
    )
worker_class = "uvicorn.workers.UvicornWorker"
threads = 1

# Timeouts
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 10
keepalive = 5

# Application
wsgi_app = "main:app"

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()

# Process naming
proc_name = "openchatshop"

# Server mechanics
preload_app = True
max_requests = 1000
max_requests_jitter = 50
