# Progress Log

Build date: 9 October 2026. Environment: cloud sandbox, Python 3.13, PostgreSQL 16, Node 22, Chromium 141, Docker engine available but Docker Hub blocked by network policy.

## Stage status

| Stage | Status | Notes |
|---|---|---|
| 1 Inspect and plan | done | empty workspace; `implementation-plan.md`, `architecture.md` |
| 2 Foundation | done | config, JSON logging, error envelope, SQLAlchemy models, Alembic migration, JWT auth + revocation, RBAC, health |
| 3 Data and ML | done | simulator, validation, adapters (canonical CSV, C-MAPSS), features, failure / anomaly / RUL, SHAP, registry, train + evaluate CLIs |
| 4 Equipment and maintenance | done | equipment, ingestion (single, batch, CSV), inference, alerts with dedup + cooldown, work-order state machine, dashboard, reports, admin, audit |
| 5 Frontend | done | 11 pages wired to the API, loading / error / empty states, light and dark themes |
| 6 Testing and security | done | see results below |
| 7 Deployment and docs | done | Dockerfiles, Compose (+ simulator profile), nginx, CI, README, 9 docs |
| 8 Final verification | done, with one gap | everything except building the Docker images (see Outstanding) |

## Tests executed and results

| Command | Result |
|---|---|
| `cd ml && pytest -q` | 25 passed |
| `cd backend && pytest -q --cov=app` | 67 passed, 87 % coverage |
| `cd frontend && npm run typecheck && npm run lint && npm test && npm run build` | clean, 17 passed, build ok |
| `ruff check` (backend, ml, scripts), `mypy app`, `alembic check` | clean |
| `alembic upgrade head` → `downgrade base` → `upgrade head` | ok |
| `npx playwright test` against Vite dev server + API with the seeded demo DB | 5 passed |
| `python scripts/smoke_test.py` against the dev API | 14 / 14 |
| `python -m maintenix_ml.evaluate --models-dir models` | 8 / 8 models reproduce stored metrics |
| Retrain motor models from scratch (seed 42) | identical test metrics and dataset fingerprint |
| Container entrypoint (`docker/backend-entrypoint.sh`) on an **empty database and empty models dir** | migrations, training (about 5 min), bootstrap (4 types, 8 models promoted), demo seed (12 assets), API up; smoke test 14 / 14 against it |
| Same entrypoint on restart | no retraining, no reseed, idempotent |
| `docker compose config` | valid |
| `docker compose up --build` | **not run**: `registry-1.docker.io` returned 403 from the sandbox egress proxy, so base images could not be pulled |

## Key files

```
ml/maintenix_ml/        simulator, validation, adapters/, features, failure, anomaly, rul, explain, registry, train, evaluate, inference
backend/app/            core/ (config, security, errors, logging, rate limit), models/, schemas/, services/, api/v1/, cli.py, main.py
backend/alembic/        env.py, versions/0001_initial_schema.py
backend/tests/          unit/, api/, integration/, conftest.py
frontend/src/           api/ (client, hooks, types), components/, pages/ (11), lib/, test/
tests/e2e/              Playwright journeys
scripts/                stream_simulator.py, smoke_test.py
docker/, docker-compose.yml, backend/Dockerfile, frontend/Dockerfile, frontend/nginx.conf, .github/workflows/ci.yml
```

## Outstanding issues

1. **Docker images unverified in this environment.** First thing to do on a machine with Docker Hub access: `cp .env.example .env`, fill secrets, `docker compose up --build`, then `python scripts/smoke_test.py` and the Playwright suite with `E2E_BASE_URL=http://localhost:8080`. The CI `e2e` job does exactly this.
2. **C-MAPSS not evaluated.** Download FD001 into `datasets/raw/cmapss/` and run `python -m maintenix_ml.train cmapss`. Add the resulting numbers to `ml-methodology.md`.
3. Frontend bundle is about 700 kB (200 kB gzip) in one chunk; route level code splitting would cut first load.
4. Recharts 2.x is marked deprecated upstream in favour of 3.x; works, but plan the upgrade.

## Exact next steps

1. Run the Compose stack and CI on GitHub; fix anything environment specific.
2. Evaluate on C-MAPSS FD001, then FD002 to FD004 (multiple operating conditions need per condition normalisation in `features.py`, bump `FEATURE_VERSION`).
3. Add drift monitoring: daily feature distribution comparison against training data and alert rate tracking per model version.
4. Close the loop: use work-order outcomes (failure found / not found) to measure real precision of alerts.
