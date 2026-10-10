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

FEATURE_VERSION = "1.1.0"
#: kept for backwards compatibility: the default windows (pumps, motors, compressors)
SHORT_WINDOW = 12
LONG_WINDOW = 48
MIN_HISTORY = LONG_WINDOW
AGE_FEATURE = "age__readings"


def min_history(spec: EquipmentTypeSpec) -> int:
    """Readings needed before a feature vector exists for this type."""
    return spec.features.min_history


def feature_names(spec: EquipmentTypeSpec) -> list[str]:
    sw, lw = spec.features.short_window, spec.features.long_window
    names: list[str] = []
    for s in spec.sensor_names:
        names += [
            f"{s}__last",
            f"{s}__mean_{sw}",
            f"{s}__std_{sw}",
            f"{s}__mean_{lw}",
            f"{s}__std_{lw}",
            f"{s}__min_{lw}",
            f"{s}__max_{lw}",
            f"{s}__slope_{lw}",
            f"{s}__delta_short_long",
        ]
    names += [f"mode__{m}" for m in OPERATING_MODES]
    names += [f"mode_share_high_load_{lw}"]
    if spec.features.include_age:
        names.append(AGE_FEATURE)
    return names


def anomaly_feature_names(spec: EquipmentTypeSpec) -> list[str]:
    """Short-horizon subset used by the anomaly detector (never includes age)."""
    sw = spec.features.short_window
    names: list[str] = []
    for s in spec.sensor_names:
        names += [f"{s}__last", f"{s}__mean_{sw}", f"{s}__std_{sw}"]
    names += [f"mode__{m}" for m in OPERATING_MODES]
    return names


def sensor_of(feature: str) -> str:
    """Map a feature name back to its sensor (or 'operating_mode' / 'age')."""
    if feature == AGE_FEATURE:
        return "age"
    return feature.split("__", 1)[0] if "__" in feature and not feature.startswith("mode") else "operating_mode"


def _rolling_slope(y: pd.Series, groups: pd.Series, window: int, min_periods: int) -> pd.Series:
    # least-squares slope of y against reading index in each (possibly partial) window: cov(i, y) / var(i)
    i = groups.groupby(groups).cumcount().astype(float)

    def roll_mean(v: pd.Series) -> pd.Series:
        return v.groupby(groups).transform(lambda s: s.rolling(window, min_periods=min_periods).mean())

    n = y.groupby(groups).transform(lambda s: s.rolling(window, min_periods=min_periods).count())
    var_i = (n**2 - 1) / 12.0
    return (roll_mean(i * y) - roll_mean(i) * roll_mean(y)) / var_i


def build_feature_frame(
    df: pd.DataFrame, spec: EquipmentTypeSpec, id_column: str = "unit_id", age_offset: int = 0,
) -> pd.DataFrame:
    """Return one feature row per input row (NaN until enough history exists).

    ``df`` must contain ``id_column``, ``timestamp``, ``operating_mode`` and the
    spec's sensors. ``age_offset`` is the number of earlier readings of the unit
    that are not in ``df`` (used when scoring a window of a longer record).
    """
    cfg = spec.features
    sw, lw, mh = cfg.short_window, cfg.long_window, cfg.min_history
    data = df.sort_values([id_column, "timestamp"]).reset_index(drop=True)
    groups = data[id_column]
    feats: dict[str, pd.Series] = {}
    for s in spec.sensor_names:
        y = data[s].astype(float)
        g = y.groupby(groups)

        def roll(w: int, fn: str, mp: int, g=g) -> pd.Series:
            return g.transform(lambda x: getattr(x.rolling(w, min_periods=mp), fn)())

        feats[f"{s}__last"] = y
        feats[f"{s}__mean_{sw}"] = roll(sw, "mean", min(sw, mh))
        feats[f"{s}__std_{sw}"] = roll(sw, "std", min(sw, mh))
        feats[f"{s}__mean_{lw}"] = roll(lw, "mean", mh)
        feats[f"{s}__std_{lw}"] = roll(lw, "std", mh)
        feats[f"{s}__min_{lw}"] = roll(lw, "min", mh)
        feats[f"{s}__max_{lw}"] = roll(lw, "max", mh)
        feats[f"{s}__slope_{lw}"] = _rolling_slope(y, groups, lw, mh)
        feats[f"{s}__delta_short_long"] = feats[f"{s}__mean_{sw}"] - feats[f"{s}__mean_{lw}"]

    modes = data["operating_mode"].astype(str)
    for m in OPERATING_MODES:
        feats[f"mode__{m}"] = (modes == m).astype(float)
    hl = (modes == "high_load").astype(float)
    feats[f"mode_share_high_load_{lw}"] = hl.groupby(groups).transform(lambda x: x.rolling(lw, min_periods=mh).mean())
    if cfg.include_age:
        age = (groups.groupby(groups).cumcount() + 1 + age_offset).astype(float)
        feats[AGE_FEATURE] = age.where(age >= mh)
    out = pd.DataFrame(feats)[feature_names(spec)]
    out.insert(0, "timestamp", data["timestamp"].to_numpy())
    out.insert(0, id_column, groups.to_numpy())
    # carry through any non-feature columns (labels, ground truth) aligned by order
    for c in data.columns:
        if c not in out.columns and c not in spec.sensor_names and c != "operating_mode":
            out[c] = data[c].to_numpy()
    return out


def build_window_features(window: pd.DataFrame, spec: EquipmentTypeSpec, age_offset: int = 0) -> pd.Series | None:
    """Feature vector for the most recent reading of a single unit's window.

    ``age_offset``: readings of this unit recorded before ``window`` (only used
    by types with ``include_age``). Returns ``None`` when the window holds fewer
    than the type's ``min_history`` readings.
    """
    cfg = spec.features
    if len(window) < cfg.min_history:
        return None
    w = window.copy()
    w["_unit"] = "u"
    keep = cfg.long_window + 5
    dropped = max(len(w) - keep, 0)
    frame = build_feature_frame(w.tail(keep), spec, id_column="_unit", age_offset=age_offset + dropped)
    row = frame.iloc[-1]
    vec = row[feature_names(spec)].astype(float)
    if vec.isna().any():
        return None
    return vec


def to_matrix(frame: pd.DataFrame, names: list[str]) -> np.ndarray:
    return frame[names].to_numpy(dtype=float)
