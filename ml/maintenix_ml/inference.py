"""Online inference over a single equipment window.

Training code is not imported here; the API depends only on this module,
``features`` and ``registry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .anomaly import AnomalyBundle
from .equipment_types import EquipmentTypeSpec
from .explain import explain_failure
from .failure import FailureBundle
from .features import anomaly_feature_names, build_window_features
from .rul import RulBundle


@dataclass
class LoadedModel:
    bundle: Any
    version: str
    metadata: dict[str, Any]


@dataclass
class WindowPrediction:
    status: str  # "ok" | "insufficient_data"
    readings_used: int
    failure_probability: float | None = None
    failure_threshold: float | None = None
    failure_model_version: str | None = None
    anomaly_score: float | None = None
    anomaly_threshold: float | None = None
    is_anomaly: bool | None = None
    anomaly_model_version: str | None = None
    sensor_deviations: list[dict[str, Any]] | None = None
    rul_hours: float | None = None
    rul_cap_hours: float | None = None
    rul_typical_error_hours: float | None = None
    rul_model_version: str | None = None
    rul_status: str = "unavailable"
    explanation: dict[str, Any] | None = None
    features: dict[str, float] | None = None


def predict_window(
    window: pd.DataFrame,
    spec: EquipmentTypeSpec,
    failure: LoadedModel | None,
    anomaly: LoadedModel | None,
    rul: LoadedModel | None,
    explain: bool = True,
    anomaly_threshold_override: float | None = None,
    age_offset: int = 0,
) -> WindowPrediction:
    """``window`` holds one unit's readings ordered by time (latest last)."""
    vec = build_window_features(window, spec, age_offset=age_offset)
    if vec is None:
        return WindowPrediction(status="insufficient_data", readings_used=len(window),
                                rul_status="insufficient_data" if spec.rul_supported else "unavailable")
    out = WindowPrediction(status="ok", readings_used=min(len(window), spec.features.long_window))
    x = vec.to_numpy(dtype=float)

    if failure is not None:
        fb: FailureBundle = failure.bundle
        out.failure_probability = float(fb.predict_proba(x.reshape(1, -1))[0])
        out.failure_threshold = fb.threshold
        out.failure_model_version = failure.version
        if explain:
            out.explanation = explain_failure(fb, x)

    if anomaly is not None:
        ab: AnomalyBundle = anomaly.bundle
        xa = vec[anomaly_feature_names(spec)].to_numpy(dtype=float).reshape(1, -1)
        out.anomaly_score = float(ab.score(xa)[0])
        out.anomaly_threshold = float(anomaly_threshold_override or ab.threshold)
        out.anomaly_model_version = anomaly.version
        last = window.iloc[-1]
        out.sensor_deviations = ab.sensor_deviations({s: float(last[s]) for s in spec.sensor_names}, str(last["operating_mode"]))
        out.is_anomaly = bool(out.anomaly_score >= out.anomaly_threshold
                              or any(d["outside_limits"] for d in out.sensor_deviations))

    if not spec.rul_supported:
        out.rul_status = "unavailable"
    elif rul is None:
        out.rul_status = "no_model"
    else:
        rb: RulBundle = rul.bundle
        out.rul_hours = float(rb.predict(x.reshape(1, -1))[0])
        out.rul_cap_hours = rb.cap
        out.rul_typical_error_hours = rb.test_mae
        out.rul_model_version = rul.version
        out.rul_status = "ok"

    out.features = {k: float(v) for k, v in vec.items() if np.isfinite(v)}
    return out
