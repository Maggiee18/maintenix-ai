# Build context: repository root (the API imports the ml/ package).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

COPY ml /app/ml
RUN pip install --no-deps /app/ml
COPY backend /app/backend
COPY scripts /app/scripts
COPY docker/backend-entrypoint.sh /app/entrypoint.sh

RUN useradd --create-home --uid 10001 maintenix && mkdir -p /app/models /app/datasets \
    && chown -R maintenix /app/models /app/datasets && chmod +x /app/entrypoint.sh
USER maintenix
WORKDIR /app/backend
ENV MODELS_DIR=/app/models DATASETS_DIR=/app/datasets
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=600s --retries=5 CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
