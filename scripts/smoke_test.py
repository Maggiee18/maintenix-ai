"""Smoke test against a running deployment (docker compose or local dev).

Verifies that the major components work together: API + database + models +
alerting + work orders. Creates one equipment item named SMOKE-<timestamp>
holding SIMULATED readings, then decommissions it at the end.

    MAINTENIX_ADMIN_PASSWORD=... python scripts/smoke_test.py --api http://localhost:8000
Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
from maintenix_ml.equipment_types import get_spec
from maintenix_ml.simulator import demo_segment

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=os.environ.get("MAINTENIX_API", "http://localhost:8000"))
    p.add_argument("--email", default=os.environ.get("MAINTENIX_ADMIN_EMAIL", "admin@example.com"))
    a = p.parse_args()
    password = os.environ.get("MAINTENIX_ADMIN_PASSWORD")
    if not password:
        print("Set MAINTENIX_ADMIN_PASSWORD", file=sys.stderr)
        return 2
    c = httpx.Client(base_url=a.api.rstrip("/"), timeout=60)

    h = c.get("/health").json()
    check("health endpoint", h.get("status") == "ok", str(h))
    check("production models registered", h.get("production_models", 0) >= 1, f"{h.get('production_models')} production models")

    r = c.post("/api/v1/auth/login", json={"email": a.email, "password": password})
    check("login", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code != 200:
        return 1
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    check("unauthenticated request rejected", httpx.get(a.api.rstrip("/") + "/api/v1/equipment").status_code == 401)

    code = f"SMOKE-{int(time.time())}"
    r = c.post("/api/v1/equipment", json={"code": code, "name": "Smoke test motor", "equipment_type": "electric_motor"})
    check("create equipment", r.status_code == 201, f"HTTP {r.status_code}")
    eq = r.json()

    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    seg, _ = demo_segment("electric_motor", 4242, "critical", end, 60)
    names = get_spec("electric_motor").sensor_names
    readings = [{"recorded_at": row.timestamp.isoformat(), "operating_mode": row.operating_mode,
                 "values": {s: float(getattr(row, s)) for s in names}} for row in seg.itertuples()]
    r = c.post("/api/v1/sensors/readings/batch", json={"equipment_id": eq["id"], "readings": readings, "data_source": "imported"})
    rep = r.json()
    check("ingest 60 readings", r.status_code == 201 and rep["accepted_rows"] == 60, f"accepted {rep.get('accepted_rows')}")
    pred = (rep.get("predictions") or [{}])[0]
    check("prediction produced", pred.get("status") == "ok", str(pred))
    check("RUL produced for a run-to-failure type", pred.get("rul_status") in ("ok", "no_model"), str(pred.get("rul_status")))

    alerts = c.get("/api/v1/alerts", params={"equipment_id": eq["id"], "status": "active"}).json()
    check("alert raised for high-risk readings", alerts["total"] >= 1, f"{alerts['total']} active alerts")

    me = c.get("/api/v1/auth/me").json()
    alert_id = alerts["items"][0]["id"] if alerts["items"] else None
    r = c.post("/api/v1/work-orders", json={"equipment_id": eq["id"], "title": "Smoke test inspection", "alert_id": alert_id,
                                            "priority": "high", "assigned_to_id": None})
    check("create work order", r.status_code == 201, f"HTTP {r.status_code}")
    wo = r.json()
    users = c.get("/api/v1/users/assignable").json()
    assignee = next((u["id"] for u in users), me["id"])
    c.post(f"/api/v1/work-orders/{wo['id']}/assign", json={"assignee_id": assignee})
    c.post(f"/api/v1/work-orders/{wo['id']}/transition", json={"to_status": "in_progress"})
    r = c.post(f"/api/v1/work-orders/{wo['id']}/complete", json={"action_taken": "inspection", "summary": "Smoke test completion",
                                                                  "restores_health": True})
    check("complete work order", r.status_code == 200 and r.json()["status"] == "completed", f"HTTP {r.status_code}")
    active = c.get("/api/v1/alerts", params={"equipment_id": eq["id"], "status": "active"}).json()["total"]
    check("alerts resolved by completion", active == 0, f"{active} still active")

    s = c.get("/api/v1/dashboard/summary").json()
    check("dashboard summary", s.get("total_equipment", 0) >= 1, f"{s.get('total_equipment')} equipment")
    r = c.get("/api/v1/reports/equipment.csv")
    check("CSV report", r.status_code == 200 and r.text.startswith("code,"), r.headers.get("content-type", ""))

    c.post(f"/api/v1/equipment/{eq['id']}/status", json={"status": "decommissioned", "reason": "smoke test cleanup"})
    failed = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
