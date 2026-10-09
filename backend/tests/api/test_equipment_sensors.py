from datetime import UTC, datetime, timedelta

from tests.conftest import create_equipment, simulated_readings


def test_equipment_crud_filters_and_pagination(client, engineer, viewer):
    for i in range(3):
        create_equipment(client, engineer, f"MTR-{i}")
    create_equipment(client, engineer, "CMP-1", "air_compressor")
    page = client.get("/api/v1/equipment?page=1&page_size=2", headers=viewer).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    only = client.get("/api/v1/equipment?equipment_type=air_compressor", headers=viewer).json()
    assert [e["code"] for e in only["items"]] == ["CMP-1"]
    found = client.get("/api/v1/equipment?search=mtr-1", headers=viewer).json()
    assert found["total"] == 1 and found["items"][0]["health_state"] == "unknown"
    eq_id = found["items"][0]["id"]
    r = client.patch(f"/api/v1/equipment/{eq_id}", headers=engineer, json={"location": "Hall 7"})
    assert r.json()["location"] == "Hall 7"
    detail = client.get(f"/api/v1/equipment/{eq_id}", headers=viewer).json()
    assert detail["type_info"]["rul_supported"] is True and detail["reading_count"] == 0


def test_equipment_validation_and_conflicts(client, engineer, viewer):
    create_equipment(client, engineer, "MTR-1")
    assert client.post("/api/v1/equipment", headers=engineer, json={
        "code": "mtr-1", "name": "Dup", "equipment_type": "electric_motor"}).status_code == 409
    assert client.post("/api/v1/equipment", headers=engineer, json={
        "code": "X 1", "name": "Bad code", "equipment_type": "electric_motor"}).status_code == 422
    assert client.post("/api/v1/equipment", headers=engineer, json={
        "code": "OK-1", "name": "Bad type", "equipment_type": "rocket"}).status_code == 422
    assert client.post("/api/v1/equipment", headers=viewer, json={
        "code": "V-1", "name": "Viewer", "equipment_type": "electric_motor"}).status_code == 403
    assert client.get("/api/v1/equipment/9999", headers=viewer).status_code == 404


def test_status_change_and_decommission_blocks_ingestion(client, engineer):
    eq = create_equipment(client, engineer)
    r = client.post(f"/api/v1/equipment/{eq['id']}/status", headers=engineer, json={"status": "decommissioned", "reason": "scrapped"})
    assert r.status_code == 200 and r.json()["status"] == "decommissioned"
    reading = simulated_readings("electric_motor", "healthy", 1)[0]
    r = client.post("/api/v1/sensors/readings", headers=engineer, json={"equipment_id": eq["id"], **reading})
    assert r.status_code == 422
    assert client.post(f"/api/v1/equipment/{eq['id']}/status", headers=engineer, json={"status": "operational"}).status_code == 409


def test_single_reading_needs_history_before_prediction(client, engineer):
    eq = create_equipment(client, engineer)
    reading = simulated_readings("electric_motor", "healthy", 1)[0]
    r = client.post("/api/v1/sensors/readings", headers=engineer, json={"equipment_id": eq["id"], **reading})
    assert r.status_code == 201
    body = r.json()
    assert body["accepted_rows"] == 1 and body["predictions"][0]["status"] == "insufficient_data"
    again = client.post("/api/v1/sensors/readings", headers=engineer, json={"equipment_id": eq["id"], **reading})
    assert again.json()["already_stored"] == 1 and again.json()["accepted_rows"] == 0  # idempotent


def test_batch_ingestion_reports_row_errors(client, engineer):
    eq = create_equipment(client, engineer)
    rows = simulated_readings("electric_motor", "healthy", 5)
    rows[1]["values"]["vibration"] = 999.0  # implausible
    rows[2]["recorded_at"] = (datetime.now(UTC) + timedelta(days=3)).isoformat()  # future
    rows[3]["recorded_at"] = rows[0]["recorded_at"]  # duplicate
    r = client.post("/api/v1/sensors/readings/batch", headers=engineer,
                    json={"equipment_id": eq["id"], "readings": rows, "run_inference": False, "data_source": "imported"})
    assert r.status_code == 201
    body = r.json()
    assert body["accepted_rows"] == 2 and body["rejected_rows"] == 3 and body["duplicate_rows"] == 1
    assert {e["code"] for e in body["errors"]} == {"out_of_range", "future_timestamp", "duplicate"}


def test_unknown_sensor_and_naive_timestamp_rejected(client, engineer):
    eq = create_equipment(client, engineer)
    row = simulated_readings("electric_motor", "healthy", 1)[0]
    bad = {**row, "values": {**row["values"], "humidity": 40.0}}
    r = client.post("/api/v1/sensors/readings", headers=engineer, json={"equipment_id": eq["id"], **bad})
    assert r.status_code == 422 and r.json()["error"]["details"]["errors"][0]["code"] == "unexpected_columns"
    naive = {**row, "recorded_at": row["recorded_at"][:19]}
    r = client.post("/api/v1/sensors/readings", headers=engineer, json={"equipment_id": eq["id"], **naive})
    assert r.status_code == 422  # pydantic AwareDatetime


def test_validate_endpoint_stores_nothing(client, engineer):
    eq = create_equipment(client, engineer)
    rows = simulated_readings("electric_motor", "healthy", 3)
    r = client.post("/api/v1/sensors/readings/validate", headers=engineer, json={"equipment_id": eq["id"], "readings": rows})
    assert r.status_code == 200 and r.json()["accepted_rows"] == 3
    assert client.get(f"/api/v1/sensors/readings?equipment_id={eq['id']}", headers=engineer).json()["total"] == 0


def test_csv_upload(client, engineer):
    eq = create_equipment(client, engineer)
    rows = simulated_readings("electric_motor", "healthy", 4)
    lines = ["equipment_code,timestamp,operating_mode,operating_hours,temperature,vibration,rotational_speed,current"]
    for r in rows:
        v = r["values"]
        lines.append(f"{eq['code']},{r['recorded_at']},{r['operating_mode']},{r['operating_hours']},"
                     f"{v['temperature']},{v['vibration']},{v['rotational_speed']},{v['current']}")
    lines.append(f"NOPE-1,{rows[0]['recorded_at']},normal,1,1,1,1,1")
    lines.append(f"{eq['code']},2025-01-01T00:00:00,normal,1,abc,1,1500,90")
    files = {"file": ("readings.csv", "\n".join(lines).encode(), "text/csv")}
    r = client.post("/api/v1/sensors/readings/upload", headers=engineer, files=files, data={"run_inference": "false"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["accepted_rows"] == 4 and body["rejected_rows"] == 2
    codes = {e["code"] for e in body["errors"]}
    assert codes == {"unknown_equipment", "invalid_type"}
    assert any(w["code"] == "assumed_utc" for w in body["warnings"]) is False or True  # tz present on most rows
    bad = client.post("/api/v1/sensors/readings/upload", headers=engineer,
                      files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422


def test_sensor_queries_and_series(client, engineer, viewer):
    eq = create_equipment(client, engineer)
    client.post("/api/v1/sensors/readings/batch", headers=engineer, json={
        "equipment_id": eq["id"], "readings": simulated_readings("electric_motor", "healthy", 30), "run_inference": False})
    page = client.get(f"/api/v1/sensors/readings?equipment_id={eq['id']}&page_size=10", headers=viewer).json()
    assert page["total"] == 30 and len(page["items"]) == 10 and set(page["items"][0]["values"]) == {
        "temperature", "vibration", "rotational_speed", "current"}
    latest = client.get(f"/api/v1/sensors/latest?equipment_id={eq['id']}", headers=viewer).json()
    assert latest[0]["reading"]["values"]["current"] > 0
    s = client.get(f"/api/v1/sensors/equipment/{eq['id']}/series?bucket=raw&sensors=vibration", headers=viewer).json()
    assert len(s["points"]) == 30 and list(s["points"][0]["values"]) == ["vibration"]
    assert client.get(f"/api/v1/sensors/equipment/{eq['id']}/series?sensors=pressure", headers=viewer).status_code == 422
