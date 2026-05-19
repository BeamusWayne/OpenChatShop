FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e .

COPY configs/ configs/

EXPOSE 8000

CMD ["uvicorn", "commerce_agent.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
