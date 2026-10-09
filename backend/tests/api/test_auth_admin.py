from tests.conftest import PASSWORD, login, make_user


def test_health_endpoints(client):
    for path in ("/health", "/api/v1/health"):
        r = client.get(path)
        assert r.status_code == 200
        body = r.json()
        assert body["database"] == "ok" and body["production_models"] >= 4


def test_login_me_logout_revokes_token(client):
    make_user("engineer")
    headers = login(client, "engineer@test.example.com")
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["role"] == "engineer"
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401 and r.json()["error"]["message"] == "Token revoked"


def test_bad_credentials_and_error_envelope(client):
    make_user("viewer")
    r = client.post("/api/v1/auth/login", json={"email": "viewer@test.example.com", "password": "nope"})
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthorized" and "request_id" in err and "Traceback" not in r.text
    r = client.post("/api/v1/auth/login", json={"email": "nobody@test.example.com", "password": "x"})
    assert r.status_code == 401  # same response for unknown email


def test_inactive_user_cannot_login(client):
    make_user("viewer", active=False)
    r = client.post("/api/v1/auth/login", json={"email": "viewer@test.example.com", "password": PASSWORD})
    assert r.status_code == 401


def test_login_rate_limit(client):
    make_user("viewer")
    codes = [client.post("/api/v1/auth/login", json={"email": "viewer@test.example.com", "password": "bad"}).status_code
             for _ in range(12)]
    assert codes[-1] == 429 and 401 in codes


def test_missing_and_invalid_tokens(client):
    assert client.get("/api/v1/equipment").status_code == 401
    assert client.get("/api/v1/equipment", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_admin_user_management_and_audit(client, admin):
    r = client.post("/api/v1/admin/users", headers=admin, json={
        "email": "New.Tech@Test.example.com", "full_name": "New Tech", "role": "technician", "password": "Weak"})
    assert r.status_code == 422  # password policy
    r = client.post("/api/v1/admin/users", headers=admin, json={
        "email": "New.Tech@Test.example.com", "full_name": "New Tech", "role": "technician", "password": "Strong-pass-123"})
    assert r.status_code == 201 and r.json()["email"] == "new.tech@test.example.com"
    uid = r.json()["id"]
    dup = client.post("/api/v1/admin/users", headers=admin, json={
        "email": "new.tech@test.example.com", "full_name": "Dup", "role": "viewer", "password": "Strong-pass-123"})
    assert dup.status_code == 409
    r = client.patch(f"/api/v1/admin/users/{uid}", headers=admin, json={"role": "engineer"})
    assert r.json()["role"] == "engineer"
    events = client.get("/api/v1/admin/audit-events?action=user.", headers=admin).json()["items"]
    actions = {e["action"] for e in events}
    assert {"user.create", "user.update"} <= actions
    assert all("password" not in str(e["details"]).lower() for e in events)


def test_admin_cannot_demote_self(client, admin):
    me = client.get("/api/v1/auth/me", headers=admin).json()
    r = client.patch(f"/api/v1/admin/users/{me['id']}", headers=admin, json={"is_active": False})
    assert r.status_code == 422


def test_non_admin_forbidden_from_admin_routes(client, engineer):
    assert client.get("/api/v1/admin/users", headers=engineer).status_code == 403
    assert client.get("/api/v1/admin/audit-events", headers=engineer).status_code == 403
    assert client.put("/api/v1/admin/thresholds/electric_motor", headers=engineer, json={
        "risk_warning": 0.2, "risk_critical": 0.8}).status_code == 403


def test_thresholds_update_validated_and_audited(client, admin):
    r = client.put("/api/v1/admin/thresholds/electric_motor", headers=admin, json={"risk_warning": 0.8, "risk_critical": 0.5})
    assert r.status_code == 422
    r = client.put("/api/v1/admin/thresholds/electric_motor", headers=admin,
                   json={"risk_warning": 0.25, "risk_critical": 0.8, "cooldown_minutes": 30})
    assert r.status_code == 200 and r.json()["cooldown_minutes"] == 30
    actions = [e["action"] for e in client.get("/api/v1/admin/audit-events", headers=admin).json()["items"]]
    assert "threshold.update" in actions


def test_models_listed_and_promotion_rules(client, admin, viewer):
    models = client.get("/api/v1/models", headers=viewer).json()
    assert {m["task"] for m in models} >= {"failure", "anomaly", "rul"}
    prod = next(m for m in models if m["status"] == "production" and m["task"] == "failure")
    detail = client.get(f"/api/v1/models/{prod['id']}", headers=viewer).json()
    assert "test" in detail["metrics"] and detail["feature_names"]
    assert client.post(f"/api/v1/models/{prod['id']}/promote", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/models/{prod['id']}/promote", headers=admin).status_code == 409  # already production
