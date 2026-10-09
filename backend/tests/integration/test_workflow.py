"""End-to-end flows through the real API and database (models: tiny test models)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import get_engine
from tests.conftest import create_equipment, simulated_readings


def test_ingest_predict_alert_workorder_complete(client, engineer, technician, viewer):
    eq = create_equipment(client, engineer)
    # 1-4. readings arrive, are validated, features computed, risk predicted
    body = client.post("/api/v1/sensors/readings/batch", headers=engineer, json={
        "equipment_id": eq["id"], "readings": simulated_readings("electric_motor", "critical", 60)}).json()
    pred = body["predictions"][0]
    assert pred["risk_level"] == "high"
    # 5. threshold breach raises an alert
    alerts = client.get(f"/api/v1/alerts?status=active&equipment_id={eq['id']}", headers=viewer).json()["items"]
    risk_alert = next(a for a in alerts if a["kind"] == "failure_risk")
    assert risk_alert["severity"] == "critical" and risk_alert["prediction_id"] == pred["prediction_id"]
    # 6. user reviews evidence
    detail = client.get(f"/api/v1/predictions/{pred['prediction_id']}", headers=viewer).json()
    assert detail["explanation"]["sensor_contributions"]
    # 7-8. work order from the alert, assigned and started
    tech_id = client.get("/api/v1/auth/me", headers=technician).json()["id"]
    wo = client.post("/api/v1/work-orders", headers=engineer, json={
        "equipment_id": eq["id"], "title": "Investigate high risk", "priority": "critical",
        "alert_id": risk_alert["id"], "prediction_id": pred["prediction_id"], "assigned_to_id": tech_id}).json()
    assert wo["status"] == "assigned"
    ack = client.get(f"/api/v1/alerts?equipment_id={eq['id']}&kind=failure_risk", headers=viewer).json()["items"][0]
    assert ack["status"] == "acknowledged" and ack["work_order_id"] == wo["id"]
    client.post(f"/api/v1/work-orders/{wo['id']}/transition", headers=technician, json={"to_status": "in_progress"})
    # 9. completion recorded
    done = client.post(f"/api/v1/work-orders/{wo['id']}/complete", headers=technician, json={
        "action_taken": "replacement", "summary": "Rewound stator and replaced bearings", "restores_health": True,
        "downtime_hours": 6}).json()
    assert done["status"] == "completed"
    # 10. history updated, alerts resolved
    active = client.get(f"/api/v1/alerts?status=active&equipment_id={eq['id']}", headers=viewer).json()
    assert active["total"] == 0
    hh = client.get(f"/api/v1/equipment/{eq['id']}/health-history", headers=viewer).json()
    assert hh["points"] and hh["maintenance"][0]["restores_health"] is True


def test_alert_deduplication_and_cooldown(client, engineer, admin):
    eq = create_equipment(client, engineer)
    client.post("/api/v1/sensors/readings/batch", headers=engineer, json={
        "equipment_id": eq["id"], "readings": simulated_readings("electric_motor", "critical", 60)})
    for _ in range(3):
        client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=engineer)
    alerts = client.get(f"/api/v1/alerts?equipment_id={eq['id']}&kind=failure_risk", headers=engineer).json()["items"]
    assert len(alerts) == 1 and alerts[0]["occurrence_count"] == 4  # 1 from ingestion + 3 reruns
    # resolve -> cooldown suppresses an identical alert
    client.post(f"/api/v1/alerts/{alerts[0]['id']}/resolve", headers=engineer, json={"note": "checked"})
    client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=engineer)
    assert client.get(f"/api/v1/alerts?equipment_id={eq['id']}&kind=failure_risk&status=active", headers=engineer).json()["total"] == 0
    # cooldown 0 -> a new alert is allowed
    client.put("/api/v1/admin/thresholds/electric_motor", headers=admin, json={
        "risk_warning": 0.3, "risk_critical": 0.7, "cooldown_minutes": 0})
    client.post(f"/api/v1/predictions/equipment/{eq['id']}/run", headers=engineer)
    assert client.get(f"/api/v1/alerts?equipment_id={eq['id']}&kind=failure_risk&status=active", headers=engineer).json()["total"] == 1


def test_fleet_run(client, engineer):
    a = create_equipment(client, engineer, "MTR-A")
    create_equipment(client, engineer, "MTR-B")  # no readings: skipped
    client.post("/api/v1/sensors/readings/batch", headers=engineer, json={
        "equipment_id": a["id"], "readings": simulated_readings("electric_motor", "healthy", 60), "run_inference": False})
    r = client.post("/api/v1/predictions/run-fleet", headers=engineer).json()
    assert r["equipment_evaluated"] == 2 and r["predictions_created"] == 1


def test_database_constraints(client, engineer):
    eq = create_equipment(client, engineer)
    eng = get_engine()
    with pytest.raises(IntegrityError), eng.begin() as c:
        c.execute(text("UPDATE equipment SET status = 'exploded' WHERE id = :i"), {"i": eq["id"]})
    with pytest.raises(IntegrityError), eng.begin() as c:
        c.execute(text("INSERT INTO users (email, full_name, password_hash, role_id) VALUES ('UPPER@x.com','x','x',1)"))
    with eng.begin() as c:
        c.execute(text("INSERT INTO alerts (equipment_id, kind, severity, status, title, message, first_seen_at, last_seen_at, occurrence_count) "
                       "VALUES (:i, 'anomaly', 'warning', 'open', 't', 'm', now(), now(), 1)"), {"i": eq["id"]})
    with pytest.raises(IntegrityError), eng.begin() as c:  # partial unique index: one active alert per kind
        c.execute(text("INSERT INTO alerts (equipment_id, kind, severity, status, title, message, first_seen_at, last_seen_at, occurrence_count) "
                       "VALUES (:i, 'anomaly', 'warning', 'acknowledged', 't', 'm', now(), now(), 1)"), {"i": eq["id"]})
    with pytest.raises(IntegrityError), eng.begin() as c:
        c.execute(text("UPDATE alert_thresholds SET risk_warning = 0.9, risk_critical = 0.5"))
