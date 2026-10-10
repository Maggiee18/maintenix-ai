"""Model improvement experiments on NASA C-MAPSS FD001, using ONLY the 100 training engines.

5-fold GroupKFold by engine. The official test set is never read here, so these
numbers can be used to choose features and hyperparameters without leaking test
information. Run: python ml/experiments/cmapss_cv.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

from maintenix_ml.adapters.cmapss import load_cmapss_train
from maintenix_ml.equipment_types import get_spec

CAP = 125.0
DATA = Path(__file__).resolve().parents[2] / "datasets" / "raw" / "cmapss"


def features(df: pd.DataFrame, sensors: list[str], short: int, long: int, min_hist: int, age: bool, ewm: tuple[int, ...]) -> pd.DataFrame:
    g = df.groupby("unit_id")
    out = {}
    idx = g.cumcount().astype(float)
    for s in sensors:
        y = df[s]
        gs = y.groupby(df["unit_id"])
        def r(w: int, fn: str, mp: int, gs=gs) -> pd.Series:
            return gs.transform(lambda x: getattr(x.rolling(w, min_periods=mp), fn)())
        out[f"{s}__last"] = y
        out[f"{s}__mean_s"] = r(short, "mean", min(short, min_hist))
        out[f"{s}__std_s"] = r(short, "std", min(short, min_hist))
        out[f"{s}__mean_l"] = r(long, "mean", min_hist)
        out[f"{s}__std_l"] = r(long, "std", min_hist)
        out[f"{s}__min_l"] = r(long, "min", min_hist)
        out[f"{s}__max_l"] = r(long, "max", min_hist)
        iy = (idx * y).groupby(df["unit_id"]).transform(lambda x: x.rolling(long, min_periods=min_hist).mean())
        mi = idx.groupby(df["unit_id"]).transform(lambda x: x.rolling(long, min_periods=min_hist).mean())
        n = y.groupby(df["unit_id"]).transform(lambda x: x.rolling(long, min_periods=min_hist).count())
        out[f"{s}__slope_l"] = (iy - mi * out[f"{s}__mean_l"]) / ((n**2 - 1) / 12)
        out[f"{s}__delta"] = out[f"{s}__mean_s"] - out[f"{s}__mean_l"]
        for span in ewm:
            out[f"{s}__ewm{span}"] = gs.transform(lambda x, span=span: x.ewm(span=span, adjust=True).mean())
    if age:
        out["age"] = idx + 1
    return pd.DataFrame(out)


def cv_rmse(X: np.ndarray, y: np.ndarray, groups: np.ndarray, make, folds: int = 5) -> dict[str, float]:
    errs, near = [], []
    for tr, te in GroupKFold(folds).split(X, y, groups):
        m = make()
        m.fit(X[tr], y[tr])
        p = np.clip(m.predict(X[te]), 0, CAP)
        e = p - y[te]
        errs.append(e)
        near.append(e[y[te] < CAP])
    e, n = np.concatenate(errs), np.concatenate(near)
    return {"rmse": float(np.sqrt((e**2).mean())), "mae": float(np.abs(e).mean()), "rmse_near": float(np.sqrt((n**2).mean()))}


def xgb(**kw):  # noqa: ANN003, ANN201
    base = dict(n_estimators=500, max_depth=5, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, n_jobs=2, random_state=42, verbosity=0)
    base.update(kw)
    return lambda: XGBRegressor(**base)


def main() -> int:
    spec = get_spec("turbofan_engine")
    df = load_cmapss_train(DATA, "FD001").sort_values(["unit_id", "timestamp"]).reset_index(drop=True)
    y_all = np.minimum(df["gt_rul_hours"].to_numpy(float), CAP)
    results = {}

    configs = {
        "baseline_w12_48_min48": dict(short=12, long=48, min_hist=48, age=False, ewm=()),
        "w10_30_min30": dict(short=10, long=30, min_hist=30, age=False, ewm=()),
        "w12_48_min30": dict(short=12, long=48, min_hist=30, age=False, ewm=()),
        "w12_48_min30_age": dict(short=12, long=48, min_hist=30, age=True, ewm=()),
        "w12_48_min30_age_ewm": dict(short=12, long=48, min_hist=30, age=True, ewm=(10, 30)),
        "w10_30_min30_age_ewm": dict(short=10, long=30, min_hist=30, age=True, ewm=(10, 30)),
    }
    for name, cfg in configs.items():
        t = time.time()
        F = features(df, spec.sensor_names, **cfg)
        ok = F.notna().all(axis=1).to_numpy()
        r = cv_rmse(F[ok].to_numpy(float), y_all[ok], df.loc[ok, "unit_id"].to_numpy(), xgb())
        results[name] = {**r, "rows": int(ok.sum()), "features": F.shape[1]}
        print(name, {k: round(v, 2) if isinstance(v, float) else v for k, v in results[name].items()}, f"{time.time()-t:.0f}s", flush=True)

    print(json.dumps(results, indent=1))
    Path(__file__).with_suffix(".features.json").write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
