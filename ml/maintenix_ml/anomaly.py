"""Anomaly detection: is the current behaviour unusual compared with a healthy baseline?

Two complementary detectors:
1. Isolation Forest on short-window features, trained only on baseline
   (healthy) operating data. Score = negative ``score_samples`` (higher means
   more anomalous). Threshold = the configured quantile (default 99.5th) of
   scores on held-out baseline data, i.e. an expected false-alarm rate of about
   0.5 % on healthy operation.
2. Per-sensor, per-operating-mode control limits (mean +/- 4 sigma) from the
   same baseline. They catch single-sensor spikes the multivariate model
   dilutes, and they point at the sensors responsible.

A reading is anomalous when the Isolation Forest score is above its threshold
OR any sensor is outside its control limits. Both thresholds are configurable.

An anomaly is a deviation from the baseline. It is not a confirmed failure:
spikes, sensor faults and unusual-but-safe operation all produce anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


@dataclass
class AnomalyBundle:
    model: IsolationForest
    threshold: float
    threshold_quantile: float
    feature_names: list[str]
    sensor_names: list[str]
    control_limits: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)  # mode -> sensor -> {mean, std}
    sigma: float = 4.0

    def score(self, X: np.ndarray) -> np.ndarray:
        return -self.model.score_samples(X)

    def limit_breach(self, readings: dict[str, float], mode: str) -> bool:
        return any(d["outside_limits"] for d in self.sensor_deviations(readings, mode))

    def sensor_deviations(self, readings: dict[str, float], mode: str) -> list[dict[str, Any]]:
        limits = self.control_limits.get(mode) or self.control_limits.get("normal", {})
        out = []
        for s in self.sensor_names:
            if s not in readings or s not in limits:
                continue
            mu, sd = limits[s]["mean"], max(limits[s]["std"], 1e-9)
            z = (readings[s] - mu) / sd
            out.append({
                "sensor": s, "value": float(readings[s]), "baseline_mean": float(mu),
                "lower_limit": float(mu - self.sigma * sd), "upper_limit": float(mu + self.sigma * sd),
                "z_score": float(z), "outside_limits": bool(abs(z) > self.sigma),
            })
        return sorted(out, key=lambda d: -abs(d["z_score"]))


def fit_control_limits(baseline: pd.DataFrame, sensor_names: list[str]) -> dict[str, dict[str, dict[str, float]]]:
    limits: dict[str, dict[str, dict[str, float]]] = {}
    for mode, g in baseline.groupby("operating_mode"):
        limits[str(mode)] = {s: {"mean": float(g[s].mean()), "std": float(g[s].std(ddof=1))} for s in sensor_names}
    return limits


def train_anomaly_model(
    X_base_train: np.ndarray, X_base_val: np.ndarray, baseline_raw: pd.DataFrame,
    feature_names: list[str], sensor_names: list[str], seed: int, quantile: float = 0.995,
) -> AnomalyBundle:
    model = IsolationForest(n_estimators=300, max_samples=min(2048, len(X_base_train)), contamination="auto",
                            random_state=seed, n_jobs=2)
    model.fit(X_base_train)
    val_scores = -model.score_samples(X_base_val)
    threshold = float(np.quantile(val_scores, quantile))
    return AnomalyBundle(model, threshold, quantile, feature_names, sensor_names,
                         fit_control_limits(baseline_raw, sensor_names))


def evaluate_anomaly(bundle: AnomalyBundle, X: np.ndarray, frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """Evaluation on test units using simulator ground truth (only possible because data is simulated)."""
    if_flags = bundle.score(X) >= bundle.threshold
    limit_flags = np.array([
        bundle.limit_breach({s: float(r[f"{s}__last"]) for s in bundle.sensor_names}, _mode_of(r))
        for _, r in frame.iterrows()
    ])
    flags = if_flags | limit_flags
    injected = frame["gt_injected_anomaly"].to_numpy(dtype=bool)
    pre_failure = (frame["gt_hours_to_failure"] < horizon).to_numpy()
    healthy = (frame["gt_degradation"] < 0.05).to_numpy() & ~injected
    return {
        "threshold": bundle.threshold,
        "threshold_rule": f"{bundle.threshold_quantile:.1%} quantile of scores on held-out baseline data",
        "injected_spikes": int(injected.sum()),
        "injected_spike_detection_rate": float(flags[injected].mean()) if injected.any() else None,
        "injected_spike_detection_rate_isolation_forest_only": float(if_flags[injected].mean()) if injected.any() else None,
        "injected_spike_detection_rate_control_limits_only": float(limit_flags[injected].mean()) if injected.any() else None,
        "flag_rate_healthy": float(flags[healthy].mean()) if healthy.any() else None,
        "flag_rate_pre_failure_window": float(flags[pre_failure].mean()) if pre_failure.any() else None,
        "n_samples": int(len(flags)),
    }


def _mode_of(row: pd.Series) -> str:
    """Operating mode of a feature-frame row (one-hot ``mode__*`` columns)."""
    for col in row.index:
        if col.startswith("mode__") and row[col] == 1.0:
            return col.removeprefix("mode__")
    return "normal"
