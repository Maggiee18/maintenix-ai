#!/bin/sh
# Startup sequence: migrate -> (train if no models) -> (C-MAPSS download + train) -> reference data -> (demo seed + C-MAPSS import) -> serve.
set -e
echo "[entrypoint] applying database migrations"
alembic upgrade head

if [ "${TRAIN_ON_START:-true}" = "true" ] && ! ls "$MODELS_DIR"/*/*/*/metadata.json >/dev/null 2>&1; then
  echo "[entrypoint] no model artifacts in $MODELS_DIR; training on SIMULATED data (first start takes a few minutes)"
  python -m maintenix_ml.train --models-dir "$MODELS_DIR" --output "$MODELS_DIR/training_summary.json" simulated --all > /dev/null
fi

if [ "${CMAPSS:-true}" = "true" ]; then
  echo "[entrypoint] NASA C-MAPSS FD001: download (checksum verified) and train if needed"
  if python /app/scripts/download_cmapss.py --dest "$DATASETS_DIR/cmapss"; then
    if ! ls "$MODELS_DIR"/turbofan_engine/*/*/metadata.json >/dev/null 2>&1; then
      python -m maintenix_ml.train --models-dir "$MODELS_DIR" --output "$MODELS_DIR/cmapss_summary.json" \
        cmapss --data-dir "$DATASETS_DIR/cmapss" --subset FD001 > /dev/null
    fi
  else
    echo "[entrypoint] C-MAPSS unavailable; continuing with simulated data only"
  fi
fi

echo "[entrypoint] syncing equipment types, models, thresholds and bootstrap admin"
python -m app.cli bootstrap

if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[entrypoint] seeding SIMULATED demo fleet (skipped if equipment exists)"
  python -m app.cli seed-demo
  if [ "${CMAPSS:-true}" = "true" ] && [ -f "$DATASETS_DIR/cmapss/test_FD001.txt" ]; then
    echo "[entrypoint] importing real C-MAPSS test engines (skips engines already imported)"
    python -m app.cli import-cmapss --data-dir "$DATASETS_DIR/cmapss" --engines 8 > /dev/null
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers "${WEB_CONCURRENCY:-2}"
