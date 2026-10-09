"""Re-evaluate registered models and check that stored metrics reproduce.

For every model trained on SIMULATED data, the dataset is regenerated from the
seed and unit count recorded in its metadata, split with the same seed, and
the saved artifact is scored on the test units again. The recomputed headline
metrics are compared with the ones written at training time.

    python -m maintenix_ml.evaluate --models-dir models
Exit code 0 when every metric matches (within 1e-6).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .anomaly import evaluate_anomaly
from .equipment_types import get_spec
from .evaluation import classification_metrics, unit_split
from .features import anomaly_feature_names, build_feature_frame, feature_names
from .registry import list_metadata, load_bundle
from .simulator import failure_labels, generate_fleet
from .validation import validate_readings

TOL = 1e-6


def _frame(meta: dict[str, Any]) -> tuple[Any, dict[str, np.ndarray]]:
    spec = get_spec(meta["equipment_type"])
    ds = meta["dataset"]
    raw = generate_fleet(spec.key, int(ds["units"]), int(meta["seed"]))
    data = validate_readings(raw, spec, allow_extra=("_censor_end",)).valid
    frame = build_feature_frame(data, spec)
    frame["label"] = failure_labels(frame, spec.failure_horizon_hours)
    splits = unit_split(frame["unit_id"].unique(), int(meta["seed"]))
    return frame, {k: frame["unit_id"].isin(v).to_numpy() for k, v in splits.items()}


def evaluate_model(models_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    spec = get_spec(meta["equipment_type"])
    bundle, _ = load_bundle(models_dir, spec.key, meta["task"], meta["version"])
    frame, split = _frame(meta)
    names = feature_names(spec)
    has = frame[names].notna().all(axis=1).to_numpy()
    stored = meta["metrics"]["test"]
    if meta["task"] == "failure":
        m = has & frame["label"].notna().to_numpy() & split["test"]
        p = bundle.predict_proba(frame.loc[m, names].to_numpy(float))
        got = classification_metrics(frame.loc[m, "label"].to_numpy().astype(int), p, bundle.threshold)
        keys = ["precision", "recall", "f1", "pr_auc", "roc_auc", "brier"]
        pairs = {k: (stored[k], got[k]) for k in keys}
    elif meta["task"] == "anomaly":
        m = has & split["test"]
        a_names = anomaly_feature_names(spec)
        got = evaluate_anomaly(bundle, frame.loc[m, a_names].to_numpy(float), frame.loc[m], spec.failure_horizon_hours)
        keys = ["injected_spike_detection_rate", "flag_rate_healthy", "flag_rate_pre_failure_window"]
        pairs = {k: (stored[k], got[k]) for k in keys}
    else:
        m = has & frame["gt_rul_hours"].notna().to_numpy() & split["test"]
        y = np.minimum(frame.loc[m, "gt_rul_hours"].to_numpy(float), bundle.cap)
        pred = bundle.predict(frame.loc[m, names].to_numpy(float))
        err = pred - y
        pairs = {"overall.mae": (stored["overall"]["mae"], float(np.abs(err).mean())),
                 "overall.rmse": (stored["overall"]["rmse"], float(np.sqrt((err**2).mean())))}
    mism = {k: v for k, v in pairs.items() if v[0] is not None and abs(v[0] - v[1]) > TOL}
    return {"model": f"{meta['name']}:{meta['version']}", "reproduced": not mism,
            "metrics": {k: round(v[1], 6) for k, v in pairs.items()}, "mismatches": mism}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="maintenix_ml.evaluate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--equipment-type")
    a = p.parse_args(argv)
    results = []
    for meta in list_metadata(a.models_dir):
        if meta.get("dataset", {}).get("source") != "simulated":
            continue  # C-MAPSS models are re-evaluated by re-running training (needs the dataset files)
        if a.equipment_type and meta["equipment_type"] != a.equipment_type:
            continue
        results.append(evaluate_model(a.models_dir, meta))
    print(json.dumps(results, indent=2))
    return 0 if results and all(r["reproduced"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
