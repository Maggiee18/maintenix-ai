"""Failure-risk classification: will this unit fail within the horizon?

Candidates (all imbalance-aware):
* Logistic Regression with standardisation and balanced class weights
* Random Forest with balanced_subsample class weights
* XGBoost with ``scale_pos_weight`` = negatives / positives

Selection uses validation PR-AUC (robust to class imbalance, unlike accuracy).
Raw scores are then calibrated with isotonic regression on the validation set
so the displayed risk behaves like a probability, and the alert threshold is
chosen on validation data by maximising F2. The test split is used once, for
reporting only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from .evaluation import choose_threshold, classification_metrics


def candidate_models(pos_weight: float, seed: int) -> dict[str, Any]:
    return {
        "logistic_regression": Pipeline(
            [("scale", StandardScaler()),
             ("clf", LogisticRegression(class_weight="balanced", max_iter=3000, C=0.5, random_state=seed))]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200, max_depth=12, min_samples_leaf=5, class_weight="balanced_subsample",
            n_jobs=-1, random_state=seed,
        ),
        "xgboost": XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=pos_weight, eval_metric="aucpr", n_jobs=2, random_state=seed, verbosity=0,
        ),
    }


@dataclass
class FailureBundle:
    """Everything needed to score a feature vector. Persisted with joblib."""

    algorithm: str
    estimator: Any
    calibrator: IsotonicRegression
    threshold: float
    feature_names: list[str]

    def raw_score(self, X: np.ndarray) -> np.ndarray:
        return self.estimator.predict_proba(X)[:, 1]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.calibrator.predict(self.raw_score(X)), 0.0, 1.0)


def train_failure_model(
    X_train: np.ndarray, y_train: np.ndarray, X_val: np.ndarray, y_val: np.ndarray,
    feature_names: list[str], seed: int,
) -> tuple[FailureBundle, dict[str, Any]]:
    pos = max(int(y_train.sum()), 1)
    pos_weight = float((len(y_train) - pos) / pos)
    comparison: dict[str, Any] = {}
    fitted: dict[str, Any] = {}
    for name, model in candidate_models(pos_weight, seed).items():
        model.fit(X_train, y_train)
        s = model.predict_proba(X_val)[:, 1]
        comparison[name] = {
            "validation_pr_auc": float(average_precision_score(y_val, s)),
            "validation_roc_auc": float(roc_auc_score(y_val, s)),
        }
        fitted[name] = model
    best = max(comparison, key=lambda k: comparison[k]["validation_pr_auc"])
    est = fitted[best]
    raw_val = est.predict_proba(X_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_val, y_val)
    cal_val = np.clip(calibrator.predict(raw_val), 0, 1)
    threshold = choose_threshold(y_val, cal_val, beta=2.0)
    bundle = FailureBundle(best, est, calibrator, threshold, feature_names)
    info = {
        "selected_algorithm": best,
        "selection_metric": "validation_pr_auc",
        "threshold_rule": "maximise F2 on calibrated validation scores",
        "comparison": comparison,
        "validation": classification_metrics(y_val, cal_val, threshold),
        "fitted_candidates": fitted,
    }
    return bundle, info


def evaluate_candidates_on_test(
    fitted: dict[str, Any], X_val: np.ndarray, y_val: np.ndarray, X_test: np.ndarray, y_test: np.ndarray
) -> dict[str, Any]:
    """Test metrics for every candidate (each with its own validation-chosen threshold)."""
    out: dict[str, Any] = {}
    for name, model in fitted.items():
        raw_val = model.predict_proba(X_val)[:, 1]
        cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_val, y_val)
        thr = choose_threshold(y_val, np.clip(cal.predict(raw_val), 0, 1))
        p = np.clip(cal.predict(model.predict_proba(X_test)[:, 1]), 0, 1)
        m = classification_metrics(y_test, p, thr)
        out[name] = {k: m[k] for k in ("precision", "recall", "f1", "f2", "roc_auc", "pr_auc", "brier", "threshold")}
    return out
