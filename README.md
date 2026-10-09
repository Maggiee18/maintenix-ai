# Maintenix AI

**Intelligent equipment health monitoring, failure prediction and predictive maintenance.**

Maintenix AI ingests equipment sensor readings, predicts the probability that a machine fails within the next 48 hours, detects abnormal behaviour, estimates remaining useful life (RUL) where the data supports it, explains each prediction, and turns the results into deduplicated alerts and a full maintenance work-order workflow. It is an advisory system: nothing in it controls equipment.

> **About the data.** Out of the box, every machine and reading is **simulated** by a documented generator (`ml/maintenix_ml/simulator.py`), labelled "Simulated" throughout the UI and API. Model metrics in this repository are measured on that synthetic data. A NASA C-MAPSS adapter is included for real benchmark work (download required, see `datasets/README.md`).

## Contents

[Problem](#problem-statement) · [Features](#key-features) · [Architecture](#architecture) · [Stack](#technology-stack) · [Quick start](#quick-start-docker) · [Local development](#local-development) · [Environment](#environment-variables) · [Data and models](#data-demo-data-and-models) · [Testing](#testing) · [Workflows](#example-workflows) · [Limitations](#known-limitations) · [Docs](#documentation)

## Problem statement

Unplanned equipment failures stop production, damage neighbouring components and create safety risk, while fixed interval maintenance replaces parts that still have life left. Sensor data (vibration, temperature, pressure, speed, current) usually shows degradation before a failure. The goal is to surface that early, explain why, and connect it to the people and work orders that act on it, while being honest about uncertainty.

## Key features

* Equipment registry with per type, configurable sensor definitions (pumps, motors, compressors, C-MAPSS turbofans)
* Single, batch and CSV ingestion with row level validation reports (missing values, types, ranges, timezones, duplicates, unknown columns, sampling gaps)
* Per equipment type models: failure risk (Logistic Regression vs Random Forest vs XGBoost, chosen on validation PR-AUC, isotonic calibration, F2 threshold), anomaly detection (Isolation Forest + per sensor control limits), RUL regression only where run to failure data exists, otherwise "RUL unavailable"
* SHAP explanations per prediction, aggregated per sensor, with stated limitations
* Model registry: versioned artifacts, dataset fingerprint, feature schema, metrics, SHA-256 verification, promotion with audit trail
* Alerts with database enforced deduplication and configurable cooldown
* Work orders: open → assigned → in progress → completed / cancelled, with event history, completion records and permissions
* Dashboard, equipment detail, sensor monitoring, prediction, anomaly, model performance, reports (CSV, injection safe) and admin pages, light and dark themes
* JWT auth with logout revocation, four roles, rate limited login, audit log
* Reproducible training and evaluation commands; 67 backend, 25 ML, 17 frontend and 5 end-to-end tests

## Architecture

```mermaid
flowchart LR
  UI[React SPA] -->|/api/v1, JWT| API[FastAPI]
  SIM[stream simulator<br/>SIMULATED feed] -->|/api/v1| API
  API --> SVC[services: ingestion, inference,<br/>alerting, work orders, reports, audit]
  SVC --> DB[(PostgreSQL)]
  SVC --> ML[maintenix_ml<br/>features + registry]
  ML --> ART[(model artifacts)]
  TRAIN[train / evaluate CLIs] --> ART
```

Details: [docs/architecture.md](docs/architecture.md).

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | React 18, TypeScript 5.7, Vite 5, Tailwind CSS 3, React Router 6, TanStack Query 5, Recharts 2 |
| Backend | Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, PyJWT, bcrypt |
| ML | pandas, NumPy, scikit-learn, XGBoost, SHAP, joblib |
| Testing | pytest, HTTPX / TestClient, Vitest, Testing Library, Playwright |
| Delivery | Docker, Docker Compose, nginx, GitHub Actions |

## System requirements

Docker path: Docker 24+ with Compose v2, 4 GB RAM, about 3 GB disk. Local path: Python 3.11 to 3.13, Node 20+, PostgreSQL 14+.

## Quick start (Docker)

```bash
cp .env.example .env          # then replace every CHANGE_ME value
docker compose up --build
```

* App: <http://localhost:8080> · API docs: <http://localhost:8000/docs>
* First start trains models on simulated data (a few minutes on 2 CPUs), then seeds the demo fleet. Later starts reuse the `models` and `pgdata` volumes.
* Sign in as `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`, or a demo user with `DEMO_USER_PASSWORD`:

| Demo user | Role |
|---|---|
| `engineer@example.com` | engineer (plans work, ingests data, runs predictions) |
| `technician@example.com`, `technician2@example.com` | technician (works assigned orders) |
| `viewer@example.com` | viewer (read only) |

Optional live simulated feed (posts the hourly readings that are due, every 5 minutes):

```bash
docker compose --profile simulator up -d
```

Production build notes: set `ENVIRONMENT=production`, `SEED_DEMO=false`, a 32+ character `JWT_SECRET`, put TLS in front of the `frontend` service and run migrations as a one-off job if you scale the API. See [docs/security.md](docs/security.md).

## Local development

```bash
# 1. Python environment
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
pip install --no-deps -e ml

# 2. Database (any PostgreSQL)
createdb maintenix && createdb maintenix_test
cp .env.example backend/.env   # set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/maintenix and MODELS_DIR=../models

# 3. Models (simulated data, seed 42, about 5 minutes)
python -m maintenix_ml.train --models-dir models simulated --all
python -m maintenix_ml.evaluate --models-dir models      # verifies stored metrics reproduce

# 4. Schema, reference data, demo fleet, API
cd backend
alembic upgrade head
python -m app.cli bootstrap
DEMO_USER_PASSWORD=Your-demo-pass1 python -m app.cli seed-demo
uvicorn app.main:app --reload --port 8000

# 5. Frontend (proxies /api to :8000)
cd ../frontend && npm ci && npm run dev    # http://localhost:5173
```

Other commands: `python -m app.cli create-user EMAIL "Name" ROLE`, `python -m app.cli run-fleet`, `python scripts/stream_simulator.py --once`.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes (local) | — | SQLAlchemy URL (Compose builds it from `POSTGRES_*`) |
| `POSTGRES_PASSWORD` | yes (Compose) | — | database password |
| `JWT_SECRET` | yes | — | token signing secret, 32+ chars enforced in production |
| `ENVIRONMENT` | no | development | `production` enables secret and CORS checks |
| `JWT_EXPIRE_MINUTES` | no | 60 | token lifetime |
| `CORS_ORIGINS` | no | localhost dev ports | comma separated allow list |
| `MODELS_DIR` | no | `models` | registry directory |
| `BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | first run | — | creates the first admin once |
| `SEED_DEMO`, `DEMO_USER_PASSWORD` | no | true / — | simulated demo fleet and demo users |
| `TRAIN_ON_START` | no | true | train if the models volume is empty |
| `PREDICTION_WINDOW` | no | 60 | readings loaded per inference (≥ 48) |
| `LOGIN_RATE_LIMIT`, `LOGIN_RATE_WINDOW_SECONDS` | no | 10, 300 | login throttling |
| `MAX_UPLOAD_BYTES`, `MAX_BATCH_ROWS` | no | 5 MB, 5000 | ingestion limits |

## Data, demo data and models

* Dataset setup, schemas, C-MAPSS acquisition and licence: [datasets/README.md](datasets/README.md)
* Training: `python -m maintenix_ml.train simulated --all` or `... cmapss --data-dir datasets/raw/cmapss`
* Evaluation and reproducibility: `python -m maintenix_ml.evaluate`
* Method, metrics and limitations: [docs/ml-methodology.md](docs/ml-methodology.md)

Headline test results on held-out simulated units:

| Type | Failure model | Precision | Recall | PR-AUC | Failures warned in advance | RUL MAE near failure |
|---|---|---|---|---|---|---|
| Pump | Logistic Regression | 0.83 | 0.96 | 0.97 | 12 / 12 | 24.9 h |
| Motor | Logistic Regression | 0.93 | 0.91 | 0.97 | 12 / 12 | 19.8 h |
| Compressor | Logistic Regression | 0.66 | 0.76 | 0.80 | 24 / 24 | unavailable by design |

## Database migrations

`cd backend && alembic upgrade head` on any empty database; `alembic check` verifies models and migrations match. Design notes: [docs/database-design.md](docs/database-design.md).

## API documentation

OpenAPI at `/docs`; guide with roles, endpoints, errors and metric definitions: [docs/api-guide.md](docs/api-guide.md).

## Testing

```bash
cd ml && pytest -q                         # 25 tests
cd backend && pytest -q --cov=app          # 67 tests, 87 % coverage, uses TEST_DATABASE_URL
cd frontend && npm test                    # 17 tests
python scripts/smoke_test.py               # 14 checks against a running API
cd tests/e2e && npx playwright test        # 5 journeys against a running stack
```

Details and the results of this build: [docs/testing.md](docs/testing.md).

## Example workflows

1. **Triage**: Fleet overview → highest-risk table → equipment detail shows probability, anomaly score, RUL with typical error, contributing sensors and readings against the healthy baseline.
2. **Act**: on the alert, *Create work order* (acknowledges the alert) → assign a technician → technician *Start work* → *Record completion* with action, parts, downtime and "restores health" → linked alerts resolve and the maintenance history updates.
3. **Import**: Sensor monitoring → upload a CSV (see `datasets/samples/readings_example.csv`) → row level report → predictions refresh.
4. **Govern**: Model performance → compare candidates, confusion matrix, calibration → admin promotes a version; Administration → thresholds, users, audit log.

## Known limitations

* Demo data and all reported metrics are synthetic; the simulator has one failure mode per type and clean noise, so real data will be harder.
* C-MAPSS adapter and training path are implemented and unit tested with a format fixture, but no C-MAPSS results are reported (dataset not downloadable during the build).
* Docker images were not built in the build environment (Docker Hub blocked by its network policy). Compose configuration validated, entrypoint sequence verified locally, and CI builds the stack.
* Rate limiting and model caches are per process; no self-service password reset or MFA; token in sessionStorage.
* Inference runs synchronously after ingestion; very high frequency feeds would need a queue.

## Future improvements

Real data connectors (OPC UA / MQTT), drift monitoring and feedback from work-order outcomes, survival / multi failure mode RUL, shadow deployments, TimescaleDB, OIDC SSO, notification channels (email, Teams), spare parts and cost tracking.

## Documentation

[Architecture](docs/architecture.md) · [Implementation plan](docs/implementation-plan.md) · [Database design](docs/database-design.md) · [ML methodology](docs/ml-methodology.md) · [API guide](docs/api-guide.md) · [Security](docs/security.md) · [Testing](docs/testing.md) · [Interview guide](docs/interview-guide.md) · [Progress log](docs/progress.md)

## Dataset attribution

NASA C-MAPSS: A. Saxena, K. Goebel, D. Simon, N. Eklund, "Damage Propagation Modeling for Aircraft Engine Run-to-Failure Simulation", International Conference on Prognostics and Health Management, 2008. Public domain US Government data, distributed by the NASA Prognostics Center of Excellence. Not redistributed here.
