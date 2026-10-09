# API Guide

Interactive OpenAPI docs: `http://localhost:8000/docs` (ReDoc at `/redoc`, schema at `/openapi.json`). All endpoints except health and login need `Authorization: Bearer <token>`.

## Conventions

* Prefix `/api/v1`. JSON in and out. Timestamps are ISO 8601 and must include a timezone.
* Lists return `{"items": [...], "total", "page", "page_size"}` with `page` and `page_size` query parameters.
* Errors always use one envelope; the `X-Request-ID` response header matches `request_id`:

```json
{"error": {"code": "invalid_transition", "message": "Cannot move work order from 'open' to 'in_progress'",
           "details": {"from": "open", "to": "in_progress", "allowed": ["assigned", "cancelled"]}, "request_id": "a1b2c3"}}
```

| Status | Code examples |
|---|---|
| 401 | `unauthorized` (missing, invalid, expired or revoked token) |
| 403 | `forbidden` (role not allowed) |
| 404 | `not_found` |
| 409 | `conflict`, `invalid_transition` |
| 422 | `validation_failed` (body or business rule; `details` lists problems) |
| 429 | `rate_limited` (login) |
| 500 | `internal_error` (no internals exposed; see server logs by request id) |

## Roles

| Capability | viewer | technician | engineer | admin |
|---|---|---|---|---|
| Read dashboards, equipment, predictions, reports | ✓ | ✓ | ✓ | ✓ |
| Start / complete work orders assigned to them | | ✓ | ✓ | ✓ |
| Register equipment, ingest data, run predictions, plan work orders, handle alerts | | | ✓ | ✓ |
| Users, thresholds, model promotion, audit log | | | | ✓ |

## Endpoints

| Area | Method and path | Notes |
|---|---|---|
| Health | `GET /health`, `GET /api/v1/health` | DB status, production model count |
| Auth | `POST /auth/login` | `{email, password}` → token, expiry, user |
| | `GET /auth/me`, `POST /auth/logout` | logout revokes the token server side |
| Catalogue | `GET /equipment-types` | sensors with units and ranges |
| Equipment | `GET /equipment` | `search, equipment_type, status, health, sort=code\|name\|risk\|updated` |
| | `POST /equipment`, `GET/PATCH /equipment/{id}` | detail includes latest reading and type info |
| | `POST /equipment/{id}/status` | `{status, reason}`; decommission blocked with active work orders |
| | `GET /equipment/{id}/health-history` | predictions over time + maintenance records |
| Sensors | `POST /sensors/readings` | one reading, then inference |
| | `POST /sensors/readings/batch` | up to 5000 readings, row level report, inference once |
| | `POST /sensors/readings/validate` | dry run, nothing stored |
| | `POST /sensors/readings/upload` | multipart CSV, max 5 MB |
| | `GET /sensors/readings`, `GET /sensors/latest` | paginated history; latest per equipment |
| | `GET /sensors/equipment/{id}/series` | `bucket=raw\|hour\|day`, `sensors`, `days`, `start`, `end` |
| Predictions | `POST /predictions/equipment/{id}/run`, `POST /predictions/run-fleet` | |
| | `GET /predictions`, `GET /predictions/{id}`, `GET /predictions/{id}/explanation` | filters: equipment, risk level, anomalies only, time range |
| | `GET /anomalies` | anomaly events with deviating sensors |
| Models | `GET /models`, `GET /models/{id}` | metrics, dataset info, feature schema |
| | `POST /models/{id}/promote`, `POST /models/sync` | admin |
| Alerts | `GET /alerts` | `status=open\|acknowledged\|resolved\|active`, `kind`, `equipment_id` |
| | `POST /alerts/{id}/acknowledge`, `POST /alerts/{id}/resolve` | |
| Maintenance | `GET/POST /work-orders`, `GET/PATCH /work-orders/{id}` | filters: status (repeatable), priority, search, `assigned_to_me`, `overdue` |
| | `POST /work-orders/{id}/assign` | `{assignee_id}` (technician or engineer) |
| | `POST /work-orders/{id}/transition` | `{to_status: in_progress\|open\|cancelled, note}` |
| | `POST /work-orders/{id}/complete` | maintenance record; `restores_health` resolves active alerts |
| | `GET /maintenance/records`, `GET /users/assignable` | |
| Dashboard | `GET /dashboard/summary`, `/health-distribution`, `/high-risk`, `/prediction-trends`, `/sensor-trends`, `/maintenance-backlog` | |
| Reports | `GET /reports/equipment.csv`, `/predictions.csv`, `/maintenance.csv` | audited, formula injection safe |
| Admin | `GET/POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/reset-password` | |
| | `GET /admin/thresholds`, `PUT /admin/thresholds/{type}`, `GET /admin/audit-events` | |

## Metric definitions (dashboard)

| Metric | Definition |
|---|---|
| Total equipment | equipment with status ≠ decommissioned |
| Requiring attention | latest prediction health is watch (anomaly, low risk), at risk (elevated) or critical (high) |
| High risk | latest failure probability ≥ the type's critical threshold |
| Health state | from the latest prediction: unknown (none or insufficient data) → critical / at_risk by risk level → watch if anomalous → healthy |
| Risk level | low below warning, elevated from warning, high from critical (per type thresholds) |
| Mean failure probability (daily) | mean of `failure_probability` of predictions with `as_of` on that day |
| Mean time to complete | mean of completed_at − created_at for work orders completed in the last 30 days |

## Example session

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s -X POST $API/auth/login -H 'content-type: application/json' \
  -d '{"email":"engineer@example.com","password":"<password>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"

curl -s -X POST $API/equipment -H "$H" -H 'content-type: application/json' \
  -d '{"code":"MTR-900","name":"Test motor","equipment_type":"electric_motor"}'

curl -s -X POST $API/sensors/readings -H "$H" -H 'content-type: application/json' -d '{
  "equipment_id": 13, "recorded_at": "2026-10-09T10:00:00Z", "operating_mode": "normal",
  "values": {"temperature": 74.1, "vibration": 1.9, "rotational_speed": 1476, "current": 88.2}}'
# -> accepted_rows: 1, predictions: [{"status": "insufficient_data", ...}] until 48 readings exist

curl -s -X POST $API/predictions/equipment/13/run -H "$H"
```
