from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from maintenix_ml.equipment_types import get_spec
from maintenix_ml.evaluation import choose_threshold, regression_metrics, unit_split
from maintenix_ml.features import MIN_HISTORY, build_feature_frame, build_window_features, feature_names
from maintenix_ml.simulator import demo_segment, failure_labels, generate_fleet, simulate_unit
from maintenix_ml.validation import validate_readings

PUMP = get_spec("centrifugal_pump")


def _frame(n: int = 5) -> pd.DataFrame:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    return pd.DataFrame({
        "unit_id": ["P1"] * n,
        "timestamp": [(t0 + timedelta(hours=i)).isoformat() for i in range(n)],
        "operating_mode": ["normal"] * n,
        "temperature": [55.0] * n, "vibration": [2.0] * n, "pressure": [8.0] * n,
        "rotational_speed": [2950.0] * n, "power": [38.0] * n,
    })


# ---------------- simulator ----------------

def test_simulator_is_deterministic_and_flagged():
    a = simulate_unit("centrifugal_pump", 7, "U")
    b = simulate_unit("centrifugal_pump", 7, "U")
    pd.testing.assert_frame_equal(a, b)
    assert (a["data_source"] == "simulated").all()
    assert a["gt_failure_event"].sum() == 1 and a["gt_failure_event"].iloc[-1]
    assert a["gt_rul_hours"].iloc[-1] == 0


def test_compressor_has_no_rul_and_censored_labels():
    df = simulate_unit("air_compressor", 3, "C")
    assert df["gt_rul_hours"].isna().all()
    labels = failure_labels(df, 48)
    assert labels.isna().any()  # tail after last trip is censored
    assert set(labels.dropna().unique()) <= {0.0, 1.0}


def test_demo_segment_ends_at_requested_time():
    end = datetime(2026, 1, 1, tzinfo=UTC)
    seg, idx = demo_segment("electric_motor", 11, "critical", end, history_hours=100)
    assert len(seg) == 100 and seg["timestamp"].iloc[-1] == end and idx > 0


# ---------------- validation ----------------

def test_valid_frame_passes():
    r = validate_readings(_frame(), PUMP)
    assert r.ok and len(r.valid) == 5 and r.rejected_rows == 0


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda d: d.assign(temperature=[55, None, 55, 55, 55]), "missing_value"),
        (lambda d: d.assign(timestamp=["bad", *d.timestamp[1:]]), "invalid_timestamp"),
        (lambda d: d.assign(vibration=[2, 2, 999, 2, 2]), "out_of_range"),
        (lambda d: d.assign(pressure=["8", "x", "8", "8", "8"]), "invalid_type"),
        (lambda d: d.assign(operating_mode=["normal", "turbo", "normal", "normal", "normal"]), "invalid_mode"),
        (lambda d: d.assign(timestamp=[d.timestamp[0], d.timestamp[0], *d.timestamp[2:]]), "duplicate"),
    ],
)
def test_row_level_errors(mutate, code):
    r = validate_readings(mutate(_frame()), PUMP)
    assert r.ok  # frame-level ok, row rejected
    assert r.rejected_rows == 1 and len(r.valid) == 4
    assert r.errors[0].code == code


def test_unexpected_and_missing_columns_reject_frame():
    r = validate_readings(_frame().assign(humidity=1.0), PUMP)
    assert not r.ok and r.errors[0].code == "unexpected_columns"
    r = validate_readings(_frame().drop(columns=["vibration"]), PUMP)
    assert not r.ok and r.errors[0].code == "missing_columns"


def test_future_timestamp_rejected_and_sampling_gap_reported():
    df = _frame()
    df.loc[4, "timestamp"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    df.loc[3, "timestamp"] = (datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=10)).isoformat()
    r = validate_readings(df, PUMP)
    assert any(e.code == "future_timestamp" for e in r.errors)
    assert r.sampling["gaps"] == 1
    assert any(w.code == "irregular_sampling" for w in r.warnings)


def test_naive_timestamps_rejected_when_not_assuming_utc():
    df = _frame()
    df["timestamp"] = [t[:19] for t in df["timestamp"]]
    assert validate_readings(df, PUMP, assume_utc=False).rejected_rows == 5
    assert validate_readings(df, PUMP, assume_utc=True).rejected_rows == 0


# ---------------- features ----------------

def test_features_do_not_use_future_readings():
    df = simulate_unit("centrifugal_pump", 1, "U").iloc[:200]
    full = build_feature_frame(df, PUMP)
    truncated = build_feature_frame(df.iloc[:120], PUMP)
    names = feature_names(PUMP)
    np.testing.assert_allclose(full[names].iloc[:120].to_numpy(), truncated[names].to_numpy(), equal_nan=True)


def test_window_features_match_frame_and_need_history():
    df = simulate_unit("electric_motor", 2, "U").iloc[:150]
    spec = get_spec("electric_motor")
    frame = build_feature_frame(df, spec)
    vec = build_window_features(df, spec)
    np.testing.assert_allclose(vec.to_numpy(), frame[feature_names(spec)].iloc[-1].to_numpy(), rtol=1e-9)
    assert build_window_features(df.iloc[: MIN_HISTORY - 1], spec) is None


def test_slope_feature_recovers_linear_trend():
    df = _frame(60)
    df["temperature"] = 50 + 0.5 * np.arange(60)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    vec = build_window_features(df, PUMP)
    assert vec["temperature__slope_48"] == pytest.approx(0.5)


# ---------------- splitting and metrics ----------------

def test_unit_split_is_disjoint_and_reproducible():
    fleet = generate_fleet("centrifugal_pump", 10, seed=1)
    s1 = unit_split(fleet["unit_id"].unique(), 5)
    s2 = unit_split(fleet["unit_id"].unique(), 5)
    assert s1 == s2
    assert not set(s1["train"]) & set(s1["test"]) and not set(s1["train"]) & set(s1["validation"])
    assert sum(len(v) for v in s1.values()) == 10


def test_threshold_and_regression_metrics():
    y = np.array([0, 0, 0, 1, 1])
    s = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    assert 0.3 < choose_threshold(y, s) <= 0.8
    m = regression_metrics(np.array([10, 20]), np.array([12, 16]))
    assert m["mae"] == 3 and m["rmse"] == pytest.approx(np.sqrt(10))
