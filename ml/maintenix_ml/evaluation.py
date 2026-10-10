"""Splitting and evaluation utilities.

Classification and regression are evaluated differently on purpose: failure
prediction uses threshold-dependent and ranking metrics suited to rare
positives; RUL uses absolute error metrics in hours.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    fbeta_score,
    mean_absolute_error,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    root_mean_squared_error,
)


def unit_split(
    units: list[str] | np.ndarray, seed: int, fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)
) -> dict[str, list[str]]:
    """Split whole units (trajectories) into train/validation/test.

    Rows from one unit never appear in two splits, so the model cannot learn a
    unit's idiosyncrasies in training and be rewarded for them at test time.
    """
    u = np.array(sorted(set(map(str, units))))
    rng = np.random.default_rng(seed)
    rng.shuffle(u)
    n = len(u)
    n_train = max(1, int(round(fractions[0] * n)))
    n_val = max(1, int(round(fractions[1] * n)))
    return {
        "train": sorted(u[:n_train].tolist()),
        "validation": sorted(u[n_train : n_train + n_val].tolist()),
        "test": sorted(u[n_train + n_val :].tolist()),
    }


def choose_threshold(y_true: np.ndarray, scores: np.ndarray, beta: float = 2.0) -> float:
    """Threshold maximising F-beta on validation data.

    beta = 2 weights recall twice as much as precision because a missed failure
    (unplanned downtime) usually costs far more than an extra inspection.
    """
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    p, r = precision[:-1], recall[:-1]
    denom = beta**2 * p + r
    fb = np.where(denom > 0, (1 + beta**2) * p * r / np.where(denom > 0, denom, 1), 0)
    return float(thresholds[int(np.argmax(fb))]) if len(thresholds) else 0.5


def calibration_bins(y_true: np.ndarray, prob: np.ndarray, n_bins: int = 10) -> list[dict[str, float]]:
    edges = np.linspace(0, 1, n_bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (prob >= lo) & ((prob < hi) if hi < 1 else (prob <= hi))
        if m.sum():
            out.append({"bin_low": float(lo), "bin_high": float(hi), "mean_predicted": float(prob[m].mean()),
                        "observed_rate": float(y_true[m].mean()), "count": int(m.sum())})
    return out


def classification_metrics(y_true: np.ndarray, prob: np.ndarray, threshold: float) -> dict[str, Any]:
    y_true = np.asarray(y_true).astype(int)
    pred = (prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    both = len(np.unique(y_true)) == 2
    return {
        "threshold": float(threshold),
        "n_samples": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "f2": float(fbeta_score(y_true, pred, beta=2, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, prob)) if both else None,
        "pr_auc": float(average_precision_score(y_true, prob)) if both else None,
        "brier": float(brier_score_loss(y_true, prob)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "calibration": calibration_bins(y_true, prob),
    }


def event_metrics(frame: pd.DataFrame, prob: np.ndarray, threshold: float, horizon: int, id_column: str = "unit_id") -> dict[str, Any]:
    """Operational view: how many failure events were warned about in advance,
    with what lead time, and how often healthy operation raised a warning.
    """
    df = frame[[id_column, "gt_hours_to_failure", "gt_failure_event"]].copy()
    df["alarm"] = prob >= threshold
    caught, lead_times, events = 0, [], 0
    for _, g in df.groupby(id_column):
        htf = g["gt_hours_to_failure"].to_numpy()
        alarm = g["alarm"].to_numpy()
        for idx in np.flatnonzero(g["gt_failure_event"].to_numpy()):
            events += 1
            # readings in the horizon before this event belong to this event
            window = (htf >= 0) & (htf < horizon) & (np.arange(len(g)) <= idx) & (np.arange(len(g)) > idx - horizon - 1)
            hits = np.flatnonzero(window & alarm)
            if len(hits):
                caught += 1
                lead_times.append(float(htf[hits[0]]))
    healthy = ~(df["gt_hours_to_failure"] < horizon)
    false_alarms = int((df["alarm"] & healthy).sum())
    return {
        "failure_events": events,
        "events_warned": caught,
        "event_recall": float(caught / events) if events else None,
        "median_lead_time_hours": float(np.median(lead_times)) if lead_times else None,
        "false_alarms_per_1000_healthy_hours": float(1000 * false_alarms / max(int(healthy.sum()), 1)),
    }


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true
    return {
        "n_samples": int(len(y_true)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "bias": float(err.mean()),
        "overestimate_rate": float((err > 0).mean()),
        "late_by_10_plus_rate": float((err > 10).mean()),
    }


def nasa_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Asymmetric C-MAPSS scoring function (late predictions penalised more)."""
    d = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return float(np.sum(np.where(d < 0, np.exp(-d / 13) - 1, np.exp(d / 10) - 1)))
