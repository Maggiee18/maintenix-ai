#!/bin/sh
# Startup sequence: migrate -> (train if no models) -> reference data -> (demo seed) -> serve.
set -e
echo "[entrypoint] applying database migrations"
alembic upgrade head

if [ "${TRAIN_ON_START:-true}" = "true" ] && ! ls "$MODELS_DIR"/*/*/*/metadata.json >/dev/null 2>&1; then
  echo "[entrypoint] no model artifacts in $MODELS_DIR; training on SIMULATED data (first start takes a few minutes)"
  python -m maintenix_ml.train --models-dir "$MODELS_DIR" --output "$MODELS_DIR/training_summary.json" simulated --all > /dev/null
fi

echo "[entrypoint] syncing equipment types, models, thresholds and bootstrap admin"
python -m app.cli bootstrap

if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[entrypoint] seeding SIMULATED demo fleet (skipped if equipment exists)"
  python -m app.cli seed-demo
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers "${WEB_CONCURRENCY:-2}"
