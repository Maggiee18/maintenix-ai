"""Reproducible training CLI.

Examples::

    python -m maintenix_ml.train simulated --type centrifugal_pump --units 60 --seed 42
    python -m maintenix_ml.train simulated --all
    python -m maintenix_ml.train cmapss --data-dir datasets/raw/cmapss --subset FD001

Each run writes versioned artifacts and metadata to ``--models-dir`` (default
``models/``) and prints a metrics summary. Same arguments + same library
versions = same data, splits and models (all randomness is seeded).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import anomaly as anomaly_mod
from . import failure as failure_mod
from . import rul as rul_mod
from .equipment_types import SIMULATED_TYPES, EquipmentTypeSpec, get_spec
from .evaluation import classification_metrics, event_metrics, unit_split
from .features import anomaly_feature_names, build_feature_frame, feature_names
from .registry import save_bundle
from .simulator import failure_labels, generate_fleet
from .validation import validate_readings

log = logging.getLogger("maintenix_ml.train")

DEFAULT_UNITS = {"centrifugal_pump": 60, "electric_motor": 60, "air_compressor": 40}
RUL_CAP = {"centrifugal_pump": 200.0, "electric_motor": 200.0, "turbofan_engine": 125.0}
#: XGBoost RUL settings chosen by 5-fold engine-grouped cross validation on the C-MAPSS
#: training engines (ml/experiments/cmapss_cv.py); other types keep the defaults.
RUL_XGB_PARAMS: dict[str, dict[str, Any]] = {"turbofan_engine": {"max_depth": 3}}


def dataset_fingerprint(df: pd.DataFrame) -> str:
    cols = [c for c in df.columns if not c.startswith("_")]
    return format(int(pd.util.hash_pandas_object(df[cols], index=False).sum()) & 0xFFFFFFFFFFFF, "012x")


def baseline_mask(frame: pd.DataFrame, max_rows: int = 150, frac: float = 0.2) -> np.ndarray:
    """Early-life rows of each unit, used as the 'healthy baseline' for anomaly detection.

    Mirrors using commissioning data in practice: we take the first
    min(20 % of history, 150) readings of each unit.
    """
    pos = frame.groupby("unit_id").cumcount()
    size = frame.groupby("unit_id")["unit_id"].transform("size")
    limit = np.minimum(size * frac, max_rows)
    return (pos < limit).to_numpy()


def train_equipment_type(
    raw: pd.DataFrame, spec: EquipmentTypeSpec, dataset_id: str, seed: int, models_dir: Path,
    dataset_info: dict[str, Any],
) -> dict[str, Any]:
    report = validate_readings(raw, spec, allow_extra=("_censor_end",))
    if not report.ok:
        raise RuntimeError(f"Training data failed validation: {report.summary()['errors'][:3]}")
    data = report.valid
    log.info("%s: %d rows valid, %d rejected", spec.key, len(data), report.rejected_rows)

    frame = build_feature_frame(data, spec)
    names = feature_names(spec)
    frame["label"] = failure_labels(frame, spec.failure_horizon_hours)
    has_feat = frame[names].notna().all(axis=1)

    splits = unit_split(frame["unit_id"].unique(), seed)
    in_split = {k: frame["unit_id"].isin(v).to_numpy() for k, v in splits.items()}
    common = {"dataset_id": dataset_id, "dataset": dataset_info, "seed": seed,
              "split": {k: len(v) for k, v in splits.items()}, "split_strategy": "by unit (trajectory), 60/20/20",
              "data_validation": {k: report.summary()[k] for k in ("total_rows", "accepted_rows", "rejected_rows", "sampling")}}
    results: dict[str, Any] = {}

    # ---------------- failure risk ----------------
    lab = has_feat & frame["label"].notna()
    tr, va, te = (lab & in_split[k] for k in ("train", "validation", "test"))
    X = frame[names].to_numpy(dtype=float)
    y = frame["label"].to_numpy()
    bundle, info = failure_mod.train_failure_model(X[tr], y[tr].astype(int), X[va], y[va].astype(int), names, seed)
    p_test = bundle.predict_proba(X[te])
    test = classification_metrics(y[te].astype(int), p_test, bundle.threshold)
    test["event_level"] = event_metrics(frame[te], p_test, bundle.threshold, spec.failure_horizon_hours)
    cand = failure_mod.evaluate_candidates_on_test(info.pop("fitted_candidates"), X[va], y[va].astype(int), X[te], y[te].astype(int))
    for k, v in cand.items():
        info["comparison"][k]["test"] = v
    meta = {**common, "algorithm": bundle.algorithm,
            "params": bundle.estimator.get_params() if bundle.algorithm != "logistic_regression" else {"C": 0.5, "class_weight": "balanced"},
            "target": f"failure within {spec.failure_horizon_hours} h of the reading",
            "metrics": {"test": test, **info}, "threshold": bundle.threshold}
    meta["params"] = {k: v for k, v in meta["params"].items() if isinstance(v, (int, float, str, bool, type(None)))}
    path = save_bundle(models_dir, spec.key, "failure", bundle, meta)
    headline = {k: test[k] for k in ("precision", "recall", "f1", "pr_auc", "roc_auc")}
    results["failure"] = {"version": path.name, "algorithm": bundle.algorithm, "test": headline, "event_level": test["event_level"]}

    # ---------------- anomaly ----------------
    a_names = anomaly_feature_names(spec)
    base = baseline_mask(frame) & has_feat.to_numpy()
    raw_sorted = data.sort_values(["unit_id", "timestamp"]).reset_index(drop=True)
    an = anomaly_mod.train_anomaly_model(
        frame.loc[base & in_split["train"], a_names].to_numpy(float),
        frame.loc[base & in_split["validation"], a_names].to_numpy(float),
        raw_sorted.loc[base & in_split["train"]], a_names, spec.sensor_names, seed)
    te_a = has_feat.to_numpy() & in_split["test"]
    a_eval = anomaly_mod.evaluate_anomaly(an, frame.loc[te_a, a_names].to_numpy(float), frame.loc[te_a], spec.failure_horizon_hours)
    path = save_bundle(models_dir, spec.key, "anomaly", an, {
        **common, "algorithm": "isolation_forest+control_limits",
        "params": {"n_estimators": 300, "threshold_quantile": an.threshold_quantile, "control_limit_sigma": an.sigma,
                   "decision": "isolation_forest_score >= threshold OR any sensor outside control limits"},
        "target": "unsupervised; trained on early-life baseline readings", "metrics": {"test": a_eval},
        "threshold": an.threshold})
    results["anomaly"] = {"version": path.name, "test": a_eval}

    # ---------------- RUL ----------------
    if spec.rul_supported:
        cap = RUL_CAP[spec.key]
        r = has_feat.to_numpy() & frame["gt_rul_hours"].notna().to_numpy()
        yr = frame["gt_rul_hours"].to_numpy(float)
        tr, va, te = (r & in_split[k] for k in ("train", "validation", "test"))
        rb, rinfo = rul_mod.train_rul_model(X[tr], yr[tr], X[va], yr[va], names, cap, seed,
                                            xgb_params=RUL_XGB_PARAMS.get(spec.key), refit_on_validation=True)
        r_eval = rul_mod.evaluate_rul(rb, rinfo.pop("fitted_candidates"), X[te], yr[te])
        for k, v in r_eval.pop("candidates").items():
            rinfo["comparison"][k]["test"] = v
        rb.test_mae = r_eval["within_cap"]["mae"] if r_eval["within_cap"] else r_eval["overall"]["mae"]
        path = save_bundle(models_dir, spec.key, "rul", rb, {
            **common, "algorithm": rb.algorithm, "target": f"hours to failure, clipped at {cap:.0f} h",
            "params": {"cap_hours": cap}, "metrics": {"test": r_eval, **rinfo}})
        results["rul"] = {"version": path.name, "algorithm": rb.algorithm, "test": r_eval}
    else:
        results["rul"] = {"status": "unavailable", "reason": spec.data_note}
    return results


def run_simulated(types: list[str], units: int | None, seed: int, models_dir: Path) -> dict[str, Any]:
    out = {}
    for t in types:
        spec = get_spec(t)
        n = units or DEFAULT_UNITS[t]
        raw = generate_fleet(t, n, seed)
        fp = dataset_fingerprint(raw)
        info = {"source": "simulated", "generator": "maintenix_ml.simulator", "units": n, "rows": len(raw), "seed": seed}
        out[t] = train_equipment_type(raw, spec, f"simulated:{t}:n{n}:seed{seed}:{fp}", seed, models_dir, info)
    return out


def run_cmapss(data_dir: Path, subset: str, seed: int, models_dir: Path) -> dict[str, Any]:
    from .adapters.cmapss import evaluate_on_official_test, load_cmapss_train

    spec = get_spec("turbofan_engine")
    raw = load_cmapss_train(data_dir, subset)
    fp = dataset_fingerprint(raw)
    info = {"source": "NASA C-MAPSS", "subset": subset, "units": int(raw["unit_id"].nunique()), "rows": len(raw)}
    results = train_equipment_type(raw, spec, f"cmapss:{subset}:{fp}", seed, models_dir, info)
    results["official_test"] = evaluate_on_official_test(data_dir, subset, models_dir)
    return results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="maintenix_ml.train", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models-dir", type=Path, default=Path("models"))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, help="write the summary JSON here")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulated", help="train on the built-in SIMULATED fleet")
    s.add_argument("--type", choices=SIMULATED_TYPES, action="append")
    s.add_argument("--all", action="store_true")
    s.add_argument("--units", type=int)
    c = sub.add_parser("cmapss", help="train on NASA C-MAPSS (must be downloaded first)")
    c.add_argument("--data-dir", type=Path, default=Path("datasets/raw/cmapss"))
    c.add_argument("--subset", default="FD001", choices=["FD001"])
    a = p.parse_args(argv)

    if a.cmd == "simulated":
        types = list(SIMULATED_TYPES) if a.all or not a.type else a.type
        summary = run_simulated(types, a.units, a.seed, a.models_dir)
    else:
        summary = run_cmapss(a.data_dir, a.subset, a.seed, a.models_dir)
    text = json.dumps(summary, indent=2, default=str)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
