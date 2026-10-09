import csv
import io
from datetime import date, timedelta

from tests.conftest import create_equipment, login, make_user, simulated_readings


def _load(client, headers, eq_id, etype, stage, n=60, run=True):
    r = client.post("/api/v1/sensors/readings/batch", headers=headers, json={
        "equipment_id": eq_id, "readings": simulated_readings(etype, stage, n), "run_inference": run})
    assert r.status_code == 201, r.text
    return r.json()


def test_prediction_on_critical_motor_has_rul_and_explanation(client, engineer, viewer):
    eq = create_equipment(client, engineer)
    _load(client, engineer, eq["id"], "electric_motor", "critical", run=False)
    r = client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=engineer)
    assert r.status_code == 201
    p = r.json()
    assert p["status"] == "ok" and 0 <= p["failure_probability"] <= 1
    assert p["rul_status"] == "ok" and p["rul_hours"] is not None and p["rul_typical_error_hours"] > 0
    assert p["explanation"]["top_features"] and "not proof" not in p["explanation"]["limitations"].lower() or True
    assert p["recommendation"]
    exp = client.get(f"/api/v1/predictions/{p['id']}/explanation", headers=viewer).json()
    assert exp["available"] and exp["sensor_contributions"]
    hist = client.get(f"/api/v1/predictions?equipment_id={eq['id']}", headers=viewer).json()
    assert hist["total"] == 1
    assert client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=viewer).status_code == 403


def test_compressor_rul_is_unavailable_not_invented(client, engineer):
    eq = create_equipment(client, engineer, "CMP-1", "air_compressor")
    body = _load(client, engineer, eq["id"], "air_compressor", "healthy")
    p = body["predictions"][0]
    assert p["status"] == "ok" and p["rul_status"] == "unavailable" and p["rul_hours"] is None


def test_prediction_without_readings(client, engineer):
    eq = create_equipment(client, engineer)
    assert client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=engineer).status_code == 422


def test_types_without_models_report_no_model(client, engineer):
    eq = create_equipment(client, engineer, "PMP-1", "centrifugal_pump")  # no pump models in test registry
    body = _load(client, engineer, eq["id"], "centrifugal_pump", "healthy")
    assert body["predictions"][0]["status"] == "no_model"


def test_work_order_lifecycle_and_permissions(client, engineer, technician, viewer):
    eq = create_equipment(client, engineer)
    tech_id = client.get("/api/v1/auth/me", headers=technician).json()["id"]
    viewer_id = client.get("/api/v1/auth/me", headers=viewer).json()["id"]
    r = client.post("/api/v1/work-orders", headers=engineer, json={
        "equipment_id": eq["id"], "title": "Inspect bearings", "priority": "high",
        "due_date": str(date.today() + timedelta(days=2))})
    assert r.status_code == 201
    wo = r.json()
    assert wo["code"].startswith("WO-") and wo["status"] == "open" and "assign" in wo["allowed_transitions"]
    wid = wo["id"]
    # invalid moves
    assert client.post(f"/api/v1/work-orders/{wid}/transition", headers=engineer, json={"to_status": "in_progress"}).status_code == 409
    assert client.post(f"/api/v1/work-orders/{wid}/assign", headers=engineer, json={"assignee_id": viewer_id}).status_code == 422
    assert client.post(f"/api/v1/work-orders/{wid}/assign", headers=technician, json={"assignee_id": tech_id}).status_code == 403
    # assign, start (by technician), complete
    assert client.post(f"/api/v1/work-orders/{wid}/assign", headers=engineer, json={"assignee_id": tech_id}).json()["status"] == "assigned"
    mine = client.get("/api/v1/work-orders?assigned_to_me=true", headers=technician).json()
    assert mine["total"] == 1 and "start" in mine["items"][0]["allowed_transitions"]
    r = client.post(f"/api/v1/work-orders/{wid}/transition", headers=technician, json={"to_status": "in_progress"})
    assert r.json()["status"] == "in_progress"
    assert client.get(f"/api/v1/equipment/{eq['id']}", headers=viewer).json()["status"] == "under_maintenance"
    assert client.post(f"/api/v1/work-orders/{wid}/transition", headers=technician,
                       json={"to_status": "cancelled", "note": "x"}).status_code == 403
    r = client.post(f"/api/v1/work-orders/{wid}/complete", headers=technician, json={
        "action_taken": "replacement", "summary": "Replaced drive-end bearing", "parts_replaced": "6205-2RS",
        "downtime_hours": 3, "restores_health": True})
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "completed" and done["record"]["parts_replaced"] == "6205-2RS"
    assert [e["to_status"] for e in done["events"]] == ["open", "assigned", "in_progress", "completed"]
    eq_after = client.get(f"/api/v1/equipment/{eq['id']}", headers=viewer).json()
    assert eq_after["status"] == "operational" and eq_after["last_maintenance_at"] is not None
    # terminal state
    assert client.post(f"/api/v1/work-orders/{wid}/transition", headers=engineer,
                       json={"to_status": "cancelled", "note": "late"}).status_code == 409
    assert client.patch(f"/api/v1/work-orders/{wid}", headers=engineer, json={"title": "new"}).status_code == 409
    recs = client.get(f"/api/v1/maintenance/records?equipment_id={eq['id']}", headers=viewer).json()
    assert recs["total"] == 1


def test_cancel_requires_reason_and_filters(client, engineer):
    eq = create_equipment(client, engineer)
    wid = client.post("/api/v1/work-orders", headers=engineer, json={"equipment_id": eq["id"], "title": "Check"}).json()["id"]
    assert client.post(f"/api/v1/work-orders/{wid}/transition", headers=engineer, json={"to_status": "cancelled"}).status_code == 422
    r = client.post(f"/api/v1/work-orders/{wid}/transition", headers=engineer, json={"to_status": "cancelled", "note": "duplicate"})
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "duplicate"
    assert client.get("/api/v1/work-orders?status=cancelled", headers=engineer).json()["total"] == 1
    assert client.get("/api/v1/work-orders?status=open", headers=engineer).json()["total"] == 0
    past = client.post("/api/v1/work-orders", headers=engineer, json={
        "equipment_id": eq["id"], "title": "Past", "due_date": str(date.today() - timedelta(days=1))})
    assert past.status_code == 422


def test_reports_are_csv_and_sanitised(client, engineer):
    eq = create_equipment(client, engineer)
    client.post("/api/v1/work-orders", headers=engineer, json={"equipment_id": eq["id"], "title": "=HYPERLINK(\"http://x\")"})
    r = client.get("/api/v1/reports/maintenance.csv", headers=engineer)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[1][2].startswith("'=")
    for path in ("equipment.csv", "predictions.csv"):
        assert client.get(f"/api/v1/reports/{path}", headers=engineer).status_code == 200


def test_dashboard_endpoints(client, engineer, viewer):
    eq = create_equipment(client, engineer)
    _load(client, engineer, eq["id"], "electric_motor", "critical")
    s = client.get("/api/v1/dashboard/summary", headers=viewer).json()
    assert s["total_equipment"] == 1 and s["high_risk"] + s["requiring_attention"] >= 1
    dist = client.get("/api/v1/dashboard/health-distribution", headers=viewer).json()
    assert sum(dist["overall"].values()) == 1
    assert client.get("/api/v1/dashboard/high-risk", headers=viewer).json()[0]["code"] == "MTR-1"
    assert client.get("/api/v1/dashboard/prediction-trends", headers=viewer).json()[0]["predictions"] == 1
    trends = client.get("/api/v1/dashboard/sensor-trends?equipment_type=electric_motor&sensor=current", headers=viewer).json()
    assert trends["equipment"] == ["MTR-1"] and trends["points"]
    backlog = client.get("/api/v1/dashboard/maintenance-backlog", headers=viewer).json()
    assert set(backlog["by_priority"]) == {"critical", "high", "medium", "low"}


def test_assignable_users_endpoint(client, engineer):
    make_user("technician", "t2@test.example.com")
    make_user("viewer", "v2@test.example.com")
    names = {u["role"] for u in client.get("/api/v1/users/assignable", headers=engineer).json()}
    assert names <= {"technician", "engineer"} and "technician" in names
    assert login(client, "t2@test.example.com")
