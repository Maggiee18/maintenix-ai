import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from maintenix_ml.adapters.cmapss import load_cmapss_train, read_raw
from maintenix_ml.equipment_types import get_spec
from maintenix_ml.inference import LoadedModel, predict_window
from maintenix_ml.registry import ModelCompatibilityError, list_metadata, load_bundle
from maintenix_ml.simulator import simulate_unit
from maintenix_ml.train import run_simulated


@pytest.fixture(scope="module")
def trained(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("models")
    run_simulated(["electric_motor", "air_compressor"], units=10, seed=3, models_dir=d)
    return d


def _load(d: Path, t: str, task: str) -> LoadedModel | None:
    metas = [m for m in list_metadata(d) if m["equipment_type"] == t and m["task"] == task]
    if not metas:
        return None
    b, m = load_bundle(d, t, task, metas[-1]["version"])
    return LoadedModel(b, m["version"], m)


def test_training_writes_metadata_with_metrics(trained):
    metas = list_metadata(trained)
    tasks = {(m["equipment_type"], m["task"]) for m in metas}
    assert ("electric_motor", "rul") in tasks
    assert ("air_compressor", "rul") not in tasks  # unsupported, never invented
    fail = next(m for m in metas if m["task"] == "failure" and m["equipment_type"] == "electric_motor")
    for k in ("precision", "recall", "f1", "pr_auc", "roc_auc", "confusion_matrix"):
        assert k in fail["metrics"]["test"]
    assert set(fail["metrics"]["comparison"]) == {"logistic_regression", "random_forest", "xgboost"}
    assert fail["dataset_id"].startswith("simulated:electric_motor")


def test_inference_on_window(trained):
    spec = get_spec("electric_motor")
    window = simulate_unit("electric_motor", 99, "X").iloc[-60:]
    p = predict_window(window, spec, _load(trained, spec.key, "failure"), _load(trained, spec.key, "anomaly"),
                       _load(trained, spec.key, "rul"))
    assert p.status == "ok" and 0 <= p.failure_probability <= 1
    assert p.rul_status == "ok" and 0 <= p.rul_hours <= 200
    assert p.explanation["top_features"] and p.explanation["sensor_contributions"]
    assert p.sensor_deviations and isinstance(p.is_anomaly, bool)


def test_compressor_reports_rul_unavailable(trained):
    spec = get_spec("air_compressor")
    window = simulate_unit("air_compressor", 5, "X").iloc[:80]
    p = predict_window(window, spec, _load(trained, spec.key, "failure"), _load(trained, spec.key, "anomaly"), None)
    assert p.rul_status == "unavailable" and p.rul_hours is None


def test_insufficient_history(trained):
    spec = get_spec("electric_motor")
    p = predict_window(simulate_unit("electric_motor", 1, "X").iloc[:10], spec, None, None, None)
    assert p.status == "insufficient_data" and p.failure_probability is None


def test_registry_rejects_tampered_artifact_and_schema_change(trained, tmp_path):
    meta = next(m for m in list_metadata(trained) if m["task"] == "failure")
    vdir = trained / meta["equipment_type"] / "failure" / meta["version"]
    # copy to tmp so other tests are unaffected
    dst = tmp_path / meta["equipment_type"] / "failure" / meta["version"]
    dst.mkdir(parents=True)
    for f in vdir.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    with (dst / "model.joblib").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ModelCompatibilityError, match="checksum"):
        load_bundle(tmp_path, meta["equipment_type"], "failure", meta["version"])
    m = json.loads((dst / "metadata.json").read_text())
    m["feature_schema"]["feature_version"] = "0.0.1"
    (dst / "metadata.json").write_text(json.dumps(m))
    with pytest.raises(ModelCompatibilityError, match="Feature version"):
        load_bundle(tmp_path, meta["equipment_type"], "failure", meta["version"])
    with pytest.raises(ModelCompatibilityError):
        load_bundle(tmp_path, "../etc", "failure", meta["version"])


def test_cmapss_adapter_on_format_fixture(tmp_path):
    # Synthetic rows in the C-MAPSS file FORMAT only (not real NASA data).
    rows = []
    for unit in (1, 2):
        for cycle in range(1, 6):
            rows.append(" ".join(map(str, [unit, cycle, 0.0, 0.0, 100.0] + [float(cycle + i) for i in range(21)])))
    (tmp_path / "train_FD001.txt").write_text("\n".join(rows) + "\n")
    raw = read_raw(tmp_path / "train_FD001.txt")
    assert list(raw.columns[:2]) == ["unit", "cycle"]
    df = load_cmapss_train(tmp_path, "FD001")
    assert df.groupby("unit_id")["gt_rul_hours"].max().tolist() == [4.0, 4.0]
    assert df["gt_failure_event"].sum() == 2
    assert "s1" not in df.columns and "s2" in df.columns
    assert (df["data_source"] == "imported").all()
    assert isinstance(df["timestamp"].iloc[0], pd.Timestamp) or df["timestamp"].iloc[0].tzinfo is not None
    assert np.isfinite(df["s2"]).all()


def test_evaluate_reproduces_stored_metrics(trained):
    from maintenix_ml.evaluate import evaluate_model

    for meta in list_metadata(trained):
        result = evaluate_model(trained, meta)
        assert result["reproduced"], result


_REAL = Path(__file__).resolve().parents[2] / "datasets" / "raw" / "cmapss"


@pytest.mark.skipif(not (_REAL / "train_FD001.txt").exists(), reason="real C-MAPSS not downloaded")
def test_real_cmapss_fd001_loads_and_validates():
    from maintenix_ml.validation import validate_readings

    df = load_cmapss_train(_REAL, "FD001")
    assert df["unit_id"].nunique() == 100 and len(df) == 20631
    assert df["gt_failure_event"].sum() == 100
    assert validate_readings(df, get_spec("turbofan_engine")).rejected_rows == 0


def test_rul_bias_correction_is_stored_and_applied(trained):
    from sklearn.dummy import DummyRegressor

    from maintenix_ml.rul import RulBundle

    meta = next(m for m in list_metadata(trained) if m["task"] == "rul")
    assert "bias_correction" in meta["metrics"] and meta["metrics"]["bias_correction_rule"]
    est = DummyRegressor(strategy="constant", constant=50.0).fit(np.zeros((2, 1)), [50.0, 50.0])
    b = RulBundle("dummy", est, cap=125.0, feature_names=["x"], bias_correction=5.0)
    assert b.predict(np.zeros((1, 1)))[0] == 45.0
