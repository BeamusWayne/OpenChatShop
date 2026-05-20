"""Gunicorn configuration for production deployment."""
import os
import multiprocessing

# Server socket
bind = f"{os.environ.get('APP_HOST', '0.0.0.0')}:{os.environ.get('APP_PORT', '8000')}"

# Worker processes
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
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
