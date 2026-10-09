from types import SimpleNamespace

import pytest

from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token, decode_token, hash_password, password_problems, verify_password
from app.services.inference import health_state, risk_level
from app.services.reports import csv_stream, sanitize_cell
from app.services.workorders import TRANSITIONS, can_transition


@pytest.mark.parametrize("src,dst,ok", [
    ("open", "assigned", True), ("open", "cancelled", True), ("open", "in_progress", False), ("open", "completed", False),
    ("assigned", "in_progress", True), ("assigned", "open", True), ("assigned", "completed", False),
    ("in_progress", "completed", True), ("in_progress", "cancelled", True), ("in_progress", "open", False),
    ("completed", "open", False), ("completed", "cancelled", False), ("cancelled", "open", False),
])
def test_work_order_state_machine(src, dst, ok):
    assert can_transition(src, dst) is ok


def test_terminal_states_have_no_exits():
    assert TRANSITIONS["completed"] == set() and TRANSITIONS["cancelled"] == set()


def test_risk_levels_use_thresholds():
    th = SimpleNamespace(risk_warning=0.3, risk_critical=0.7)
    assert risk_level(None, th) is None
    assert risk_level(0.1, th) == "low"
    assert risk_level(0.3, th) == "elevated"
    assert risk_level(0.69, th) == "elevated"
    assert risk_level(0.7, th) == "high"


@pytest.mark.parametrize("pred,state", [
    (None, "unknown"),
    (SimpleNamespace(status="insufficient_data", risk_level=None, is_anomaly=None), "unknown"),
    (SimpleNamespace(status="ok", risk_level="high", is_anomaly=False), "critical"),
    (SimpleNamespace(status="ok", risk_level="elevated", is_anomaly=True), "at_risk"),
    (SimpleNamespace(status="ok", risk_level="low", is_anomaly=True), "watch"),
    (SimpleNamespace(status="ok", risk_level="low", is_anomaly=False), "healthy"),
])
def test_health_state(pred, state):
    assert health_state(pred) == state


@pytest.mark.parametrize("value,expected", [
    ("=SUM(A1:A2)", "'=SUM(A1:A2)"), ("+1", "'+1"), ("-cmd", "'-cmd"), ("@x", "'@x"), ("\tx", "'\tx"),
    ("normal text", "normal text"), (-3.5, -3.5), (None, ""), (True, "true"),
])
def test_csv_injection_protection(value, expected):
    assert sanitize_cell(value) == expected


def test_csv_stream_quotes_and_sanitises():
    out = "".join(csv_stream(["a", "b"], [["=HYPERLINK(\"x\")", 1], ["x,y", -2]]))
    assert out.splitlines()[1].startswith("\"'=HYPERLINK")
    assert '"x,y",-2' in out


def test_password_hashing_and_policy():
    h = hash_password("Correct-horse-1")
    assert verify_password("Correct-horse-1", h) and not verify_password("wrong", h)
    assert password_problems("short") and not password_problems("Long-enough-1")
    assert "at least one digit" in password_problems("NoDigitsHereAtAll")


def test_jwt_round_trip():
    token, jti, _ = create_access_token(5, "engineer")
    payload = decode_token(token)
    assert payload["sub"] == "5" and payload["role"] == "engineer" and payload["jti"] == jti


def test_rate_limiter():
    rl = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert rl.hit("k") and rl.hit("k") and not rl.hit("k")
    assert rl.hit("other")
    rl.reset("k")
    assert rl.hit("k")


def test_rul_time_unit_per_type():
    from app.models.entities import time_unit

    assert time_unit("turbofan_engine") == "cycles"
    assert time_unit("centrifugal_pump") == "h"
