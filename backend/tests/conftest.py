"""Test fixtures.

* Uses a dedicated database (TEST_DATABASE_URL, default maintenix_test on localhost).
  The schema is created with the real Alembic migrations, so migrations are tested too.
* Trains tiny deterministic models once per session into a temp directory
  (no dependency on the repository's models/ folder, no expensive training).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_MODELS = Path(os.environ.get("TEST_MODELS_DIR", "/tmp/maintenix_test_models"))
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://maintenix:maintenix_dev@localhost:5432/maintenix_test")
os.environ["JWT_SECRET"] = "test-secret-value-with-enough-length"
os.environ["ENVIRONMENT"] = "test"
os.environ["MODELS_DIR"] = str(_MODELS)
os.environ["LOG_LEVEL"] = "WARNING"
os.environ.pop("BOOTSTRAP_ADMIN_EMAIL", None)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Test-password-123"
_DATA_TABLES = ("audit_events", "work_order_events", "maintenance_records", "work_orders", "alerts", "anomaly_events",
                "sensor_values", "sensor_readings", "revoked_tokens")


def _train_models() -> None:
    from maintenix_ml.features import FEATURE_VERSION
    from maintenix_ml.registry import list_metadata
    from maintenix_ml.train import run_simulated

    metas = list_metadata(_MODELS)
    current = {m["equipment_type"] for m in metas if m["feature_schema"]["feature_version"] == FEATURE_VERSION}
    if current >= {"electric_motor", "air_compressor"}:
        return
    import shutil

    shutil.rmtree(_MODELS, ignore_errors=True)  # stale models from an older feature version
    run_simulated(["electric_motor", "air_compressor"], units=10, seed=7, models_dir=_MODELS)


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    _train_models()
    engine = get_engine()
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    from app.services.bootstrap import bootstrap

    with get_sessionmaker()() as db:
        bootstrap(db)
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    from app.api.v1.auth import login_limiter
    from app.services.models_registry import model_cache

    login_limiter.reset()
    with get_engine().begin() as c:
        c.execute(text("UPDATE equipment SET latest_prediction_id = NULL"))
        c.execute(text("TRUNCATE prediction_results, equipment, " + ", ".join(_DATA_TABLES) + " RESTART IDENTITY CASCADE"))
        # users are referenced by reference data (thresholds, model promotions): delete, do not truncate-cascade
        c.execute(text("UPDATE model_versions SET promoted_by_id = NULL"))
        c.execute(text("UPDATE alert_thresholds SET updated_by_id = NULL"))
        c.execute(text("DELETE FROM users"))
        c.execute(text("UPDATE alert_thresholds SET cooldown_minutes = 360, anomaly_alerts_enabled = true, anomaly_score_override = NULL"))
    model_cache.clear()


@pytest.fixture
def db() -> Iterator[Session]:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def make_user(role: str, email: str | None = None, active: bool = True) -> int:
    from sqlalchemy import select

    from app.models import entities as m

    with get_sessionmaker()() as s:
        r = s.scalar(select(m.Role).where(m.Role.name == role))
        u = m.User(email=email or f"{role}@test.example.com", full_name=f"Test {role.title()}", role=r,
                   password_hash=hash_password(PASSWORD), is_active=active)
        s.add(u)
        s.commit()
        return u.id


def login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    make_user("admin")
    return login(client, "admin@test.example.com")


@pytest.fixture
def engineer(client: TestClient) -> dict[str, str]:
    make_user("engineer")
    return login(client, "engineer@test.example.com")


@pytest.fixture
def technician(client: TestClient) -> dict[str, str]:
    make_user("technician")
    return login(client, "technician@test.example.com")


@pytest.fixture
def viewer(client: TestClient) -> dict[str, str]:
    make_user("viewer")
    return login(client, "viewer@test.example.com")


def create_equipment(client: TestClient, headers: dict[str, str], code: str = "MTR-1",
                     equipment_type: str = "electric_motor") -> dict[str, Any]:
    r = client.post("/api/v1/equipment", headers=headers,
                    json={"code": code, "name": f"Test {code}", "equipment_type": equipment_type, "location": "Lab"})
    assert r.status_code == 201, r.text
    return r.json()


def simulated_readings(equipment_type: str, stage: str, n: int, seed: int = 11) -> list[dict[str, Any]]:
    """n hourly readings ending one hour ago, taken from a SIMULATED trajectory."""
    from maintenix_ml.equipment_types import get_spec
    from maintenix_ml.simulator import demo_segment

    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    seg, _ = demo_segment(equipment_type, seed, stage, end, n)
    names = get_spec(equipment_type).sensor_names
    return [{"recorded_at": r.timestamp.isoformat(), "operating_mode": r.operating_mode,
             "operating_hours": float(r.operating_hours), "values": {s: float(getattr(r, s)) for s in names}}
            for r in seg.itertuples()]
