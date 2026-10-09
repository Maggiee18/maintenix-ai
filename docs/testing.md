# Testing

| Suite | Location | Tool | Count | What it covers |
|---|---|---|---|---|
| ML unit | `ml/tests` | pytest | 25 | simulator determinism and labels (incl. censoring), every validation rule, no future leakage in features, window = frame features, slope correctness, unit split disjointness, threshold and regression metrics, end-to-end mini training, inference incl. "RUL unavailable", insufficient history, registry tamper / schema / path traversal rejection, C-MAPSS adapter on a format fixture, stored metrics reproduce via `evaluate` |
| Backend unit | `backend/tests/unit` | pytest | 34 | work-order state machine table, risk levels, health states, CSV injection cases, password policy and hashing, JWT round trip, rate limiter |
| Backend API | `backend/tests/api` | pytest + FastAPI TestClient | 29 | auth (login, logout revocation, bad credentials, inactive users, rate limit, missing token), RBAC on every role, equipment CRUD, filters, pagination, conflicts, status rules, single / batch / CSV ingestion and row errors, idempotency, series queries, predictions, compressor RUL unavailable, "no model" types, work-order lifecycle and permissions, cancellation reason, reports, dashboard, thresholds, model promotion rules |
| Backend integration | `backend/tests/integration` | pytest | 4 | ingest → predict → alert → work order → complete → alerts resolved and history updated; alert dedup + cooldown; fleet run; database CHECK, unique and partial unique constraints |
| Frontend | `frontend/src/**/*.test.ts(x)` | Vitest + Testing Library | 17 | formatters, API client (token header, error envelope, network failure), login validation / error / success, QueryState loading / error / empty / content, badges, pagination, dashboard rendering from API data and error state, work-order completion form validation and payload, cancel requires reason, empty state |
| End to end | `tests/e2e` | Playwright | 5 | dashboard with simulated notice, full alert → work order → assign → start → complete journey, viewer restrictions, admin models + audit log, invalid login |
| Smoke | `scripts/smoke_test.py` | httpx | 14 checks | health, models, login, auth rejection, create equipment, ingest 60 readings, prediction, RUL, alert, work order lifecycle, alert resolution, dashboard, CSV |

Backend line coverage: 87 % (`pytest --cov=app`).

## Principles

* **Dedicated test database.** `TEST_DATABASE_URL` (default `maintenix_test`). The schema is dropped and rebuilt with the real Alembic migrations at session start; data tables are truncated after every test while reference data (types, sensors, thresholds, models) is kept.
* **No expensive training in tests.** A session fixture trains tiny deterministic models (10 units, seed 7) once into a temp directory. Pump models are deliberately absent so the "no model" path is tested.
* **Deterministic fixtures.** All sensor data in tests comes from the seeded simulator.
* **No external services.** Nothing calls the network.

## Commands

```bash
# Python (from repo root, venv active, PostgreSQL reachable)
cd ml && pytest -q
cd backend && pytest -q --cov=app
ruff check backend/app backend/tests ml scripts --config backend/pyproject.toml
cd backend && mypy app && alembic check

# Frontend
cd frontend && npm run typecheck && npm run lint && npm test && npm run build

# Against a running stack (docker compose up, or API + Vite)
MAINTENIX_ADMIN_PASSWORD=... python scripts/smoke_test.py --api http://localhost:8000
cd tests/e2e && npm install && npx playwright install chromium
E2E_BASE_URL=http://localhost:8080 E2E_ADMIN_PASSWORD=... E2E_DEMO_PASSWORD=... npx playwright test

# Model reproducibility
python -m maintenix_ml.evaluate --models-dir models
```

## Results recorded for this build

All suites above passed in the build environment (Python 3.13, PostgreSQL 16, Node 22, Chromium 141): ML 25/25, backend 67/67, frontend 17/17, Playwright 5/5 (against the Vite dev server + API, seeded demo database), smoke 14/14, `ruff`, `mypy`, `tsc`, `eslint` clean, `alembic check` clean, `python -m maintenix_ml.evaluate` 8/8 reproduced.

**Not run here:** `docker compose up --build`. The build environment's network policy blocked Docker Hub (`registry-1.docker.io` returned 403), so base images could not be pulled. `docker compose config` validated, and the container entrypoint sequence was executed step by step against a fresh database (see `progress.md`). The CI workflow builds and tests the full Compose stack on GitHub's runners.
