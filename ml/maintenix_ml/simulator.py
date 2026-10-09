"""Synthetic sensor data generator.

EVERYTHING produced by this module is SIMULATED. It is not data from real
equipment. Rows carry ``data_source = "simulated"`` and ground-truth columns
prefixed with ``gt_`` that exist only because the data is synthetic. The
``gt_`` columns are used for labels and evaluation and are never model inputs.

Physics, in brief:
* Run-to-failure types (pump, motor): each unit has a lifetime ``L``. It is
  healthy until a random onset, then a degradation index ``d`` grows as a power
  curve to 1.0 at failure. Sensors drift as ``base + amp * d**exp`` with noise
  that also grows with ``d``.
* Intermittent-fault type (compressor): units run for a long period and suffer
  fault episodes. Each episode ramps a severity index from 0 to 1 over 1-4 days
  and ends in a trip (the failure event), followed by a downtime gap with no
  readings, then a repaired healthy state.
* Operating mode (normal / high_load / idle) switches in Markov segments and
  shifts load-dependent sensors, so models must separate load from wear.
* Rare transient spikes are injected (``gt_injected_anomaly``) to evaluate the
  anomaly detector. They are not failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from .equipment_types import OPERATING_MODES, EquipmentTypeSpec, get_spec

GT_COLUMNS = (
    "gt_degradation",
    "gt_rul_hours",
    "gt_hours_to_failure",
    "gt_failure_event",
    "gt_injected_anomaly",
)


@dataclass(frozen=True)
class SensorModel:
    base: float
    noise: float
    amp: float  # change at full degradation / fault severity
    exp: float
    mode_shift: dict[str, float]


_MODELS: dict[str, dict[str, SensorModel]] = {
    "centrifugal_pump": {
        "temperature": SensorModel(55.0, 1.5, 35.0, 2.0, {"high_load": 6.0, "idle": -6.0}),
        "vibration": SensorModel(2.2, 0.25, 9.0, 2.5, {"high_load": 0.4, "idle": -0.5}),
        "pressure": SensorModel(8.0, 0.2, -2.5, 1.5, {"high_load": 0.8, "idle": -1.5}),
        "rotational_speed": SensorModel(2950.0, 6.0, -60.0, 2.0, {"high_load": -10.0}),
        "power": SensorModel(38.0, 1.2, 10.0, 2.0, {"high_load": 9.0, "idle": -14.0}),
    },
    "electric_motor": {
        "temperature": SensorModel(72.0, 2.0, 45.0, 2.0, {"high_load": 10.0, "idle": -12.0}),
        "vibration": SensorModel(1.8, 0.2, 8.0, 2.5, {"high_load": 0.3, "idle": -0.3}),
        "rotational_speed": SensorModel(1475.0, 3.0, -25.0, 2.0, {"high_load": -6.0, "idle": 8.0}),
        "current": SensorModel(88.0, 2.5, 20.0, 1.8, {"high_load": 18.0, "idle": -35.0}),
    },
    "air_compressor": {
        "temperature": SensorModel(85.0, 2.0, 40.0, 1.5, {"high_load": 8.0, "idle": -15.0}),
        "vibration": SensorModel(2.5, 0.3, 3.0, 2.0, {"high_load": 0.3, "idle": -0.6}),
        "pressure": SensorModel(7.8, 0.15, -1.6, 1.2, {"high_load": -0.3, "idle": 0.4}),
        "power": SensorModel(60.0, 2.0, 18.0, 1.5, {"high_load": 12.0, "idle": -25.0}),
    },
}

_MODE_P = np.array([0.7, 0.2, 0.1])
_ANOMALY_RATE = 0.004


def _mode_sequence(rng: np.random.Generator, n: int) -> np.ndarray:
    modes = np.empty(n, dtype=object)
    i = 0
    while i < n:
        seg = int(rng.geometric(1 / 24))
        modes[i : i + seg] = OPERATING_MODES[rng.choice(3, p=_MODE_P)]
        i += seg
    return modes


def _sensor_values(
    spec: EquipmentTypeSpec,
    rng: np.random.Generator,
    level: np.ndarray,
    modes: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    models = _MODELS[spec.key]
    n = len(level)
    out: dict[str, np.ndarray] = {}
    for name in spec.sensor_names:
        m = models[name]
        unit_base = m.base * (1 + rng.normal(0, 0.02))
        shift = np.array([m.mode_shift.get(md, 0.0) for md in modes])
        noise = rng.normal(0, m.noise, n) * (1 + 1.5 * level)
        out[name] = unit_base + shift + m.amp * np.power(level, m.exp) + noise

    injected = rng.random(n) < _ANOMALY_RATE
    for idx in np.flatnonzero(injected):
        name = spec.sensor_names[rng.integers(len(spec.sensor_names))]
        m = models[name]
        out[name][idx] += rng.choice([-1, 1]) * rng.uniform(6, 10) * m.noise
    for name in spec.sensor_names:
        s = spec.sensor(name)
        out[name] = np.clip(out[name], s.valid_min, s.valid_max)
    return out, injected


def simulate_run_to_failure(
    spec: EquipmentTypeSpec, rng: np.random.Generator, unit_id: str, start: datetime
) -> pd.DataFrame:
    lifetime = int(rng.uniform(350, 1000) if spec.key == "centrifugal_pump" else rng.uniform(400, 1200))
    onset = rng.uniform(0.2, 0.5) * lifetime
    a = rng.uniform(1.0, 2.0)
    t = np.arange(lifetime, dtype=float)
    deg = np.clip((t - onset) / (lifetime - 1 - onset), 0, 1) ** a
    modes = _mode_sequence(rng, lifetime)
    values, injected = _sensor_values(spec, rng, deg, modes)
    rul = (lifetime - 1 - t).astype(float)
    df = pd.DataFrame(
        {
            "unit_id": unit_id,
            "timestamp": [start + timedelta(hours=float(h)) for h in t],
            "operating_hours": rng.uniform(1000, 20000) + t,
            "operating_mode": modes,
            **values,
            "gt_degradation": deg,
            "gt_rul_hours": rul,
            "gt_hours_to_failure": rul,
            "gt_failure_event": rul == 0,
            "gt_injected_anomaly": injected,
        }
    )
    df["data_source"] = "simulated"
    return df


def simulate_intermittent_faults(
    spec: EquipmentTypeSpec, rng: np.random.Generator, unit_id: str, start: datetime
) -> pd.DataFrame:
    duration = int(rng.uniform(1500, 2500))
    severity = np.zeros(duration)
    failure = np.zeros(duration, dtype=bool)
    keep = np.ones(duration, dtype=bool)
    i = int(rng.uniform(150, 500))
    while i < duration:
        dev = int(rng.uniform(24, 96))
        end = min(i + dev, duration - 1)
        span = max(end - i, 1)
        severity[i : end + 1] = (np.arange(end - i + 1) / span) ** 1.5
        if end + dev <= duration and end < duration - 1:
            failure[end] = True
            downtime = int(rng.uniform(4, 12))
            keep[end + 1 : end + 1 + downtime] = False
            i = end + 1 + downtime + int(rng.uniform(200, 700))
        else:
            break

    t = np.arange(duration, dtype=float)
    # hours to the next trip, NaN when no further trip is observed (censored)
    htf = np.full(duration, np.nan)
    nxt = np.nan
    for k in range(duration - 1, -1, -1):
        if failure[k]:
            nxt = t[k]
        htf[k] = nxt - t[k] if not np.isnan(nxt) else np.nan

    modes = _mode_sequence(rng, duration)
    values, injected = _sensor_values(spec, rng, severity, modes)
    df = pd.DataFrame(
        {
            "unit_id": unit_id,
            "timestamp": [start + timedelta(hours=float(h)) for h in t],
            "operating_hours": rng.uniform(1000, 20000) + t,
            "operating_mode": modes,
            **values,
            "gt_degradation": severity,
            "gt_rul_hours": np.nan,
            "gt_hours_to_failure": htf,
            "gt_failure_event": failure,
            "gt_injected_anomaly": injected,
            "_censor_end": float(duration - 1) - t,
        }
    )
    df = df[keep].reset_index(drop=True)
    df["data_source"] = "simulated"
    return df


def simulate_unit(
    equipment_type: str, seed: int, unit_id: str, start: datetime | None = None
) -> pd.DataFrame:
    """Simulate one full trajectory for a unit, deterministically from ``seed``."""
    spec = get_spec(equipment_type)
    if spec.key not in _MODELS:
        raise ValueError(f"The simulator does not support '{equipment_type}'")
    rng = np.random.default_rng(seed)
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    if spec.rul_supported:
        return simulate_run_to_failure(spec, rng, unit_id, start)
    return simulate_intermittent_faults(spec, rng, unit_id, start)


def generate_fleet(equipment_type: str, n_units: int, seed: int = 42) -> pd.DataFrame:
    """Simulate ``n_units`` independent trajectories. Unit seeds derive from ``seed``."""
    seeds = np.random.default_rng(seed).integers(0, 2**31 - 1, n_units)
    frames = [
        simulate_unit(equipment_type, int(s), f"{equipment_type[:4].upper()}-{i:03d}")
        for i, s in enumerate(seeds)
    ]
    return pd.concat(frames, ignore_index=True)


def failure_labels(df: pd.DataFrame, horizon_hours: int) -> pd.Series:
    """Binary label: a failure event occurs within ``horizon_hours`` after this reading.

    Returns a float series with NaN where the label is unknown (censored: the
    data ends before the horizon and no failure was observed).
    """
    htf = df["gt_hours_to_failure"]
    label = (htf < horizon_hours).astype(float)
    if "_censor_end" in df:
        unknown = htf.isna() & (df["_censor_end"] < horizon_hours)
        label[unknown] = np.nan
    return label


def demo_segment(
    equipment_type: str,
    seed: int,
    stage: str,
    end_time: datetime,
    history_hours: int = 24 * 14,
) -> tuple[pd.DataFrame, int]:
    """Cut a slice of a simulated trajectory ending at ``end_time``.

    ``stage`` picks where in the life cycle the slice ends: ``healthy``,
    ``degrading`` (drifting, still far from failure), ``elevated`` (a little
    over two days before failure) or ``critical`` (less than a day before). Returns the slice and the index (in the full
    trajectory) of its last row so a streaming simulator can continue from it.
    """
    full = simulate_unit(equipment_type, seed, "demo")
    n = len(full)
    spec = get_spec(equipment_type)
    if spec.rul_supported:
        frac = {"healthy": 0.30, "degrading": 0.80}.get(stage)
        end_idx = int(frac * n) if frac is not None else n - 1 - (55 if stage == "elevated" else 20)
    else:
        events = np.flatnonzero(full["gt_failure_event"].to_numpy())
        if stage == "healthy" or len(events) == 0:
            end_idx = int(0.08 * n) + history_hours
        elif stage == "degrading":
            end_idx = int(events[0]) - 40
        elif stage == "elevated":
            end_idx = int(events[0]) - 30
        else:
            end_idx = int(events[0]) - 12
    end_idx = int(np.clip(end_idx, min(history_hours, n - 1), n - 1))
    seg = full.iloc[max(0, end_idx - history_hours + 1) : end_idx + 1].copy()
    shift = end_time - seg["timestamp"].iloc[-1]
    seg["timestamp"] = seg["timestamp"] + shift
    return seg.reset_index(drop=True), end_idx
