# Stage 1: Frontend builder
FROM node:20-slim AS frontend-builder
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./frontend/
COPY frontend-agent/package.json frontend-agent/package-lock.json* ./frontend-agent/

RUN cd frontend && npm install --production=false
RUN cd frontend-agent && npm install --production=false

COPY frontend/ ./frontend/
COPY frontend-agent/ ./frontend-agent/

RUN cd frontend && npm run build
RUN cd frontend-agent && npm run build

# Stage 2: Python builder
FROM python:3.11-slim AS python-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

# Stage 3: Runtime
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=python-builder /install /usr/local
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
COPY --from=frontend-builder /build/frontend-agent/dist ./frontend-agent/dist
COPY configs/ configs/
COPY static/ static/
COPY main.py ./
COPY alembic.ini ./
COPY gunicorn.conf.py ./
COPY entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
ENV PYTHONPATH=/app/src
EXPOSE 8000
# Probe the deep readiness endpoint and assert the JSON status, not just that
# the socket answers. /health is a shallow always-200 liveness ping; /health/ready
# actually checks DB/Redis and returns 503 (status != "ok") when a dependency is
# down, so a wedged-but-listening container is now reported unhealthy and the
# `restart: unless-stopped` policy can recycle it.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys,json; r=urllib.request.urlopen('http://localhost:8000/health/ready',timeout=4); sys.exit(0 if json.load(r).get('status')=='ok' else 1)"]
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py"]
