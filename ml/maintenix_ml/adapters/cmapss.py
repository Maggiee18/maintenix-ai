"""NASA C-MAPSS turbofan degradation dataset adapter (FD001).

Source files (whitespace separated, no header)::

    train_FD001.txt  unit, cycle, op1, op2, op3, s1..s21   (run to failure)
    test_FD001.txt   same columns, truncated before failure
    RUL_FD001.txt    true remaining cycles for each test unit's last row

Target construction: for training units, RUL = max_cycle(unit) - cycle. The
last row of each training unit is the failure event. One cycle is mapped to
one hour of synthetic timestamp (cycles have no wall-clock duration in the
dataset); RUL values therefore read as cycles.

Sensors that are constant in FD001 (s1, s5, s6, s10, s16, s18, s19) are
dropped. FD001 has a single operating condition, so op settings are ignored
and the operating mode is set to ``normal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..equipment_types import TURBOFAN_ENGINE, EquipmentTypeSpec

COLUMNS = ["unit", "cycle", "op1", "op2", "op3"] + [f"s{i}" for i in range(1, 22)]
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", header=None)
    df = df.iloc[:, : len(COLUMNS)]
    df.columns = COLUMNS
    return df


def to_canonical(raw: pd.DataFrame, spec: EquipmentTypeSpec = TURBOFAN_ENGINE, prefix: str = "FD001") -> pd.DataFrame:
    df = pd.DataFrame({
        "unit_id": raw["unit"].map(lambda u: f"{prefix}-{int(u):03d}"),
        "timestamp": [_EPOCH + timedelta(hours=int(c)) for c in raw["cycle"]],
        "operating_hours": raw["cycle"].astype(float),
        "operating_mode": "normal",
    })
    for s in spec.sensor_names:
        df[s] = raw[s].astype(float)
    df["data_source"] = "imported"
    return df


def load_cmapss_train(data_dir: Path, subset: str = "FD001") -> pd.DataFrame:
    path = Path(data_dir) / f"train_{subset}.txt"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. See datasets/README.md for download instructions.")
    raw = read_raw(path)
    df = to_canonical(raw, prefix=subset)
    max_cycle = raw.groupby("unit")["cycle"].transform("max")
    rul = (max_cycle - raw["cycle"]).astype(float).to_numpy()
    df["gt_rul_hours"] = rul
    df["gt_hours_to_failure"] = rul
    df["gt_failure_event"] = rul == 0
    df["gt_degradation"] = np.nan
    df["gt_injected_anomaly"] = False
    return df


def evaluate_on_official_test(data_dir: Path, subset: str, models_dir: Path) -> dict[str, Any]:
    """RMSE / MAE / NASA score on the official test set (last cycle of each engine)."""
    from ..evaluation import nasa_score, regression_metrics
    from ..features import build_window_features
    from ..registry import list_metadata, load_bundle

    test = to_canonical(read_raw(Path(data_dir) / f"test_{subset}.txt"), prefix=subset)
    truth = pd.read_csv(Path(data_dir) / f"RUL_{subset}.txt", header=None, sep=r"\s+").iloc[:, 0].to_numpy(float)
    metas = [m for m in list_metadata(models_dir) if m["equipment_type"] == "turbofan_engine" and m["task"] == "rul"]
    if not metas:
        return {"status": "no RUL model"}
    latest = sorted(metas, key=lambda m: m["version"])[-1]
    bundle, _ = load_bundle(models_dir, "turbofan_engine", "rul", latest["version"])
    y_true, y_pred, skipped = [], [], 0
    for i, (_, g) in enumerate(test.groupby("unit_id", sort=True)):
        vec = build_window_features(g, TURBOFAN_ENGINE)
        if vec is None:
            skipped += 1
            continue
        y_pred.append(float(bundle.predict(vec.to_numpy().reshape(1, -1))[0]))
        y_true.append(min(truth[i], bundle.cap))
    if not y_true:
        return {"status": "no test engine has enough history"}
    return {**regression_metrics(np.array(y_true), np.array(y_pred)),
            "nasa_score": nasa_score(np.array(y_true), np.array(y_pred)),
            "engines_evaluated": len(y_true), "engines_skipped_short_history": skipped,
            "note": "Engines with fewer cycles than the feature window are skipped, not padded."}


@dataclass
class CmapssAdapter:
    data_dir: Path
    subset: str = "FD001"
    spec: EquipmentTypeSpec = TURBOFAN_ENGINE
    name: str = "nasa_cmapss"

    def load(self) -> pd.DataFrame:
        return load_cmapss_train(self.data_dir, self.subset)
