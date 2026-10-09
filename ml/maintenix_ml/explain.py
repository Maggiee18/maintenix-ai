"""Per-prediction explanations for the failure-risk model.

* XGBoost: exact TreeSHAP via the booster (``pred_contribs=True``).
* Random Forest: ``shap.TreeExplainer``.
* Logistic Regression: linear SHAP, ``coef * (x - mean) / scale``.

Contributions are in the model's raw output space (log-odds for XGBoost and
logistic regression, probability for Random Forest) of the *uncalibrated*
estimator. They show which features pushed this score up or down relative to
the training average. They are associations learned from data, not proof of
cause.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .failure import FailureBundle
from .features import sensor_of

LIMITATIONS = (
    "Contributions describe the uncalibrated model's raw output, relative to the "
    "training average. They show association, not causation, and correlated sensors "
    "can share or swap credit."
)


def _contributions(bundle: FailureBundle, x: np.ndarray) -> tuple[np.ndarray, float, str]:
    est = bundle.estimator
    if bundle.algorithm == "xgboost":
        import xgboost as xgb

        contrib = est.get_booster().predict(xgb.DMatrix(x.reshape(1, -1)), pred_contribs=True)[0]
        return contrib[:-1], float(contrib[-1]), "log-odds"
    if bundle.algorithm == "random_forest":
        import shap

        explainer = shap.TreeExplainer(est)
        sv = explainer.shap_values(x.reshape(1, -1))
        arr = np.asarray(sv)
        # shap returns (n, features, classes) or list per class depending on version
        values = arr[0, :, 1] if arr.ndim == 3 else np.asarray(sv[1])[0]
        base = explainer.expected_value
        base_val = float(np.asarray(base).ravel()[-1])
        return values, base_val, "probability"
    if bundle.algorithm == "logistic_regression":
        scaler, clf = est.named_steps["scale"], est.named_steps["clf"]
        z = (x - scaler.mean_) / scaler.scale_
        return clf.coef_[0] * z, float(clf.intercept_[0]), "log-odds"
    raise ValueError(f"No explainer for {bundle.algorithm}")


def explain_failure(bundle: FailureBundle, x: np.ndarray, top_k: int = 8) -> dict[str, Any]:
    values, base, space = _contributions(bundle, np.asarray(x, dtype=float))
    order = np.argsort(-np.abs(values))
    features = [
        {"feature": bundle.feature_names[i], "sensor": sensor_of(bundle.feature_names[i]),
         "value": float(x[i]), "contribution": float(values[i]),
         "direction": "increases_risk" if values[i] > 0 else "decreases_risk"}
        for i in order[:top_k]
    ]
    by_sensor: dict[str, float] = {}
    for name, v in zip(bundle.feature_names, values, strict=True):
        s = sensor_of(name)
        by_sensor[s] = by_sensor.get(s, 0.0) + float(v)
    sensors = sorted(({"sensor": k, "contribution": v} for k, v in by_sensor.items()), key=lambda d: -abs(d["contribution"]))
    return {"method": "tree_shap" if bundle.algorithm != "logistic_regression" else "linear_shap",
            "output_space": space, "base_value": base, "top_features": features,
            "sensor_contributions": sensors, "limitations": LIMITATIONS}
