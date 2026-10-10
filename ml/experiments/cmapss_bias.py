"""Round 2: reduce optimistic (late) RUL estimates on C-MAPSS FD001.

Same rule as cmapss_cv.py: 5-fold engine-grouped CV on the 100 TRAINING engines
only; the official test set is not read. Metrics on readings with true RUL < 125:
RMSE, bias (pred - true), share of over-estimates, and the asymmetric NASA score
per prediction (late predictions cost more than early ones).
Run: python ml/experiments/cmapss_bias.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

from maintenix_ml.adapters.cmapss import load_cmapss_train
from maintenix_ml.equipment_types import get_spec
from maintenix_ml.evaluation import nasa_score
from maintenix_ml.features import build_feature_frame, feature_names

CAP = 125.0
DATA = Path(__file__).resolve().parents[2] / "datasets" / "raw" / "cmapss"
BASE = dict(n_estimators=500, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            n_jobs=2, random_state=42, verbosity=0)


def run(X: np.ndarray, y: np.ndarray, g: np.ndarray, params: dict, shift: float = 0.0) -> dict[str, float]:
    ys, ps = [], []
    for tr, te in GroupKFold(5).split(X, y, g):
        m = XGBRegressor(**{**BASE, **params}).fit(X[tr], y[tr])
        p = np.clip(m.predict(X[te]) - shift, 0, CAP)
        near = y[te] < CAP
        ys.append(y[te][near])
        ps.append(p[near])
    yt, pt = np.concatenate(ys), np.concatenate(ps)
    e = pt - yt
    return {"rmse": float(np.sqrt((e**2).mean())), "mae": float(np.abs(e).mean()), "bias": float(e.mean()),
            "over_rate": float((e > 0).mean()), "nasa_per_pred": nasa_score(yt, pt) / len(yt),
            "late_by_10_plus": float((e > 10).mean())}


def main() -> int:
    spec = get_spec("turbofan_engine")
    df = load_cmapss_train(DATA, "FD001")
    fr = build_feature_frame(df, spec)
    names = feature_names(spec)
    ok = fr[names].notna().all(axis=1).to_numpy()
    X = fr.loc[ok, names].to_numpy(float)
    y = np.minimum(fr.loc[ok, "gt_rul_hours"].to_numpy(float), CAP)
    g = fr.loc[ok, "unit_id"].to_numpy()
    configs = {
        "squared_error (current)": ({}, 0.0),
        "squared_error shift -2": ({}, 2.0),
        "squared_error shift -4": ({}, 4.0),
        "quantile 0.45": ({"objective": "reg:quantileerror", "quantile_alpha": 0.45}, 0.0),
        "quantile 0.40": ({"objective": "reg:quantileerror", "quantile_alpha": 0.40}, 0.0),
        "quantile 0.35": ({"objective": "reg:quantileerror", "quantile_alpha": 0.35}, 0.0),
        "pseudo_huber": ({"objective": "reg:pseudohubererror", "huber_slope": 10.0}, 0.0),
    }
    res = {}
    for name, (params, shift) in configs.items():
        res[name] = run(X, y, g, params, shift)
        print(f"{name:26s}", {k: round(v, 3) for k, v in res[name].items()}, flush=True)
    Path(__file__).with_suffix(".json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
