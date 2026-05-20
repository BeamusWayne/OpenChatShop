FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY alembic.ini ./
RUN pip install --no-cache-dir .

COPY configs/ configs/
COPY static/ static/
COPY main.py ./

# Create data directory for SQLite fallback
RUN mkdir -p /app/data

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["python3", "main.py"]
