"""Remaining Useful Life regression (only for run-to-failure data).

Target: hours until failure, clipped at ``cap`` (piecewise-linear target, the
standard C-MAPSS convention). Early in life the degradation signal carries
almost no information about the exact remaining life, so asking a model to
distinguish 900 h from 700 h only adds noise. A prediction equal to the cap
therefore means "at least ``cap`` hours", not exactly ``cap``.

Candidates: mean baseline, Ridge, Random Forest, XGBoost. Selection uses
validation RMSE; reporting uses MAE / RMSE on the untouched test units, overall
and inside the last ``cap`` hours where the estimate matters most.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from .evaluation import regression_metrics


@dataclass
class RulBundle:
    algorithm: str
    estimator: Any
    cap: float
    feature_names: list[str]
    test_mae: float | None = None
    #: subtracted from raw predictions; the mean validation residual near failure (see train_rul_model)
    bias_correction: float = 0.0

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.estimator.predict(X) - getattr(self, "bias_correction", 0.0), 0, self.cap)


def candidate_regressors(seed: int, xgb_params: dict[str, Any] | None = None) -> dict[str, Any]:
    xgb = dict(n_estimators=500, max_depth=5, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8)
    xgb.update(xgb_params or {})
    return {
        "mean_baseline": DummyRegressor(strategy="mean"),
        "ridge": Pipeline([("scale", StandardScaler()), ("reg", Ridge(alpha=1.0))]),
        "random_forest": RandomForestRegressor(n_estimators=150, max_depth=14, min_samples_leaf=5,
                                               n_jobs=-1, random_state=seed),
        "xgboost": XGBRegressor(**xgb, n_jobs=2, random_state=seed, verbosity=0),
    }


def train_rul_model(
    X_train: np.ndarray, y_train: np.ndarray, X_val: np.ndarray, y_val: np.ndarray,
    feature_names: list[str], cap: float, seed: int, xgb_params: dict[str, Any] | None = None,
    refit_on_validation: bool = False, correct_bias: bool = True,
) -> tuple[RulBundle, dict[str, Any]]:
    """Fit candidates on train, select on validation.

    ``correct_bias``: tree models trained on a clipped target tend to be
    optimistic near failure, the risky direction. The mean residual
    (prediction minus truth) of the selected model on validation readings with
    true RUL below the cap is stored and subtracted from future predictions.
    It is measured on validation data only, before any refit.

    With ``refit_on_validation`` the selected configuration is fitted again on
    train + validation (more data, same settings); selection already happened, so
    the test split stays untouched.
    """
    yt, yv = np.minimum(y_train, cap), np.minimum(y_val, cap)
    comparison: dict[str, Any] = {}
    fitted: dict[str, Any] = {}
    for name, model in candidate_regressors(seed, xgb_params).items():
        model.fit(X_train, yt)
        comparison[name] = {"validation": regression_metrics(yv, np.clip(model.predict(X_val), 0, cap))}
        fitted[name] = model
    best = min((k for k in comparison if k != "mean_baseline"), key=lambda k: comparison[k]["validation"]["rmse"])
    final = fitted[best]
    bias = 0.0
    near = yv < cap
    if correct_bias and near.any():
        bias = float((np.clip(final.predict(X_val[near]), 0, cap) - yv[near]).mean())
    if refit_on_validation:
        final = clone(final).fit(np.vstack([X_train, X_val]), np.concatenate([yt, yv]))
    return RulBundle(best, final, cap, feature_names, bias_correction=bias), {
        "selected_algorithm": best, "selection_metric": "validation_rmse", "cap_hours": cap,
        "bias_correction": bias, "bias_correction_rule": "mean validation residual where true RUL < cap",
        "refit_on_train_and_validation": refit_on_validation, "xgb_params": xgb_params or {},
        "comparison": comparison, "fitted_candidates": fitted,
    }


def evaluate_rul(bundle: RulBundle, fitted: dict[str, Any], X_test: np.ndarray, y_test: np.ndarray) -> dict[str, Any]:
    yc = np.minimum(y_test, bundle.cap)
    near = y_test <= bundle.cap
    pred = bundle.predict(X_test)
    out: dict[str, Any] = {
        "overall": regression_metrics(yc, pred),
        "within_cap": regression_metrics(yc[near], pred[near]) if near.any() else None,
        "candidates": {},
    }
    for name, m in fitted.items():
        p = np.clip(m.predict(X_test), 0, bundle.cap)
        out["candidates"][name] = {"overall": regression_metrics(yc, p),
                                   "within_cap": regression_metrics(yc[near], p[near]) if near.any() else None}
    return out
