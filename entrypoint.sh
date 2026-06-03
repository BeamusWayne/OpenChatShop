#!/bin/bash
set -e

# Run database migrations if DATABASE_URL is configured.
# A failed migration is fatal by default (set -e) so the app never starts
# against an inconsistent schema. Set ALLOW_MIGRATION_SKIP=1 to soft-fail.
if [ -n "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] Running database migrations..."
    if [ "${ALLOW_MIGRATION_SKIP:-0}" = "1" ]; then
        alembic upgrade head || echo "[entrypoint] WARNING: migration failed; ALLOW_MIGRATION_SKIP=1, continuing anyway..."
    else
        alembic upgrade head
    fi
else
    echo "[entrypoint] No DATABASE_URL set, skipping migrations (in-memory mode)"
fi

echo "[entrypoint] Starting application..."
exec "$@"
