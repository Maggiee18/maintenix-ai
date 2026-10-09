"""Feature engineering shared by training and online inference.

Every feature for the reading at time *t* is computed only from readings at or
before *t* for the same unit (backward-looking rolling windows). This removes
temporal leakage by construction. Windows are count-based and assume the
type's nominal sampling interval; ``validation.sampling_summary`` reports
deviations.

Bump ``FEATURE_VERSION`` whenever the feature definitions change. The model
registry refuses to load artifacts trained with a different version.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .equipment_types import OPERATING_MODES, EquipmentTypeSpec

FEATURE_VERSION = "1.0.0"
SHORT_WINDOW = 12
LONG_WINDOW = 48
#: readings needed before a full feature vector exists
MIN_HISTORY = LONG_WINDOW


def feature_names(spec: EquipmentTypeSpec) -> list[str]:
    names: list[str] = []
    for s in spec.sensor_names:
        names += [
            f"{s}__last",
            f"{s}__mean_{SHORT_WINDOW}",
            f"{s}__std_{SHORT_WINDOW}",
            f"{s}__mean_{LONG_WINDOW}",
            f"{s}__std_{LONG_WINDOW}",
            f"{s}__min_{LONG_WINDOW}",
            f"{s}__max_{LONG_WINDOW}",
            f"{s}__slope_{LONG_WINDOW}",
            f"{s}__delta_short_long",
        ]
    names += [f"mode__{m}" for m in OPERATING_MODES]
    names += [f"mode_share_high_load_{LONG_WINDOW}"]
    return names


def anomaly_feature_names(spec: EquipmentTypeSpec) -> list[str]:
    """Short-horizon subset used by the anomaly detector."""
    names: list[str] = []
    for s in spec.sensor_names:
        names += [f"{s}__last", f"{s}__mean_{SHORT_WINDOW}", f"{s}__std_{SHORT_WINDOW}"]
    names += [f"mode__{m}" for m in OPERATING_MODES]
    return names


def sensor_of(feature: str) -> str:
    """Map a feature name back to its sensor (or 'operating_mode')."""
    return feature.split("__", 1)[0] if "__" in feature and not feature.startswith("mode") else "operating_mode"


def _rolling_slope(y: pd.Series, groups: pd.Series, window: int) -> pd.Series:
    # slope of y against reading index within each window: cov(i, y) / var(i)
    i = groups.groupby(groups).cumcount().astype(float)
    g = y.groupby(groups)
    mean_y = g.transform(lambda s: s.rolling(window, min_periods=window).mean())
    iy = (i * y).groupby(groups).transform(lambda s: s.rolling(window, min_periods=window).mean())
    mean_i = i.groupby(groups).transform(lambda s: s.rolling(window, min_periods=window).mean())
    var_i = (window**2 - 1) / 12.0
    return (iy - mean_i * mean_y) / var_i


def build_feature_frame(
    df: pd.DataFrame, spec: EquipmentTypeSpec, id_column: str = "unit_id"
) -> pd.DataFrame:
    """Return one feature row per input row (NaN until enough history exists).

    ``df`` must contain ``id_column``, ``timestamp``, ``operating_mode`` and the
    spec's sensors. The returned frame keeps the input index order.
    """
    data = df.sort_values([id_column, "timestamp"]).reset_index(drop=True)
    groups = data[id_column]
    feats: dict[str, pd.Series] = {}
    for s in spec.sensor_names:
        y = data[s].astype(float)
        g = y.groupby(groups)

        def roll(w: int, fn: str, g=g) -> pd.Series:
            return g.transform(lambda x: getattr(x.rolling(w, min_periods=w), fn)())

        feats[f"{s}__last"] = y
        feats[f"{s}__mean_{SHORT_WINDOW}"] = roll(SHORT_WINDOW, "mean")
        feats[f"{s}__std_{SHORT_WINDOW}"] = roll(SHORT_WINDOW, "std")
        feats[f"{s}__mean_{LONG_WINDOW}"] = roll(LONG_WINDOW, "mean")
        feats[f"{s}__std_{LONG_WINDOW}"] = roll(LONG_WINDOW, "std")
        feats[f"{s}__min_{LONG_WINDOW}"] = roll(LONG_WINDOW, "min")
        feats[f"{s}__max_{LONG_WINDOW}"] = roll(LONG_WINDOW, "max")
        feats[f"{s}__slope_{LONG_WINDOW}"] = _rolling_slope(y, groups, LONG_WINDOW)
        feats[f"{s}__delta_short_long"] = feats[f"{s}__mean_{SHORT_WINDOW}"] - feats[f"{s}__mean_{LONG_WINDOW}"]

    modes = data["operating_mode"].astype(str)
    for m in OPERATING_MODES:
        feats[f"mode__{m}"] = (modes == m).astype(float)
    hl = (modes == "high_load").astype(float)
    feats[f"mode_share_high_load_{LONG_WINDOW}"] = hl.groupby(groups).transform(
        lambda x: x.rolling(LONG_WINDOW, min_periods=LONG_WINDOW).mean()
    )
    out = pd.DataFrame(feats)[feature_names(spec)]
    out.insert(0, "timestamp", data["timestamp"].to_numpy())
    out.insert(0, id_column, groups.to_numpy())
    # carry through any non-feature columns (labels, ground truth) aligned by order
    for c in data.columns:
        if c not in out.columns and c not in spec.sensor_names and c != "operating_mode":
            out[c] = data[c].to_numpy()
    return out


def build_window_features(window: pd.DataFrame, spec: EquipmentTypeSpec) -> pd.Series | None:
    """Feature vector for the most recent reading of a single unit's window.

    Returns ``None`` when fewer than ``MIN_HISTORY`` readings are available.
    """
    if len(window) < MIN_HISTORY:
        return None
    w = window.copy()
    w["_unit"] = "u"
    frame = build_feature_frame(w.tail(MIN_HISTORY + 5), spec, id_column="_unit")
    row = frame.iloc[-1]
    vec = row[feature_names(spec)].astype(float)
    if vec.isna().any():
        return None
    return vec


def to_matrix(frame: pd.DataFrame, names: list[str]) -> np.ndarray:
    return frame[names].to_numpy(dtype=float)
