"""Row-level validation of sensor data frames.

Used by training data preparation, CSV upload and batch ingestion so that the
same rules apply everywhere. Validation never silently fixes values: invalid
rows are reported and excluded, and the caller decides what to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from .equipment_types import OPERATING_MODES, EquipmentTypeSpec

META_COLUMNS = {"operating_hours", "operating_mode", "data_source"}


@dataclass
class Issue:
    row: int | None  # positional row index in the input frame, None for frame-level
    column: str | None
    code: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"row": self.row, "column": self.column, "code": self.code, "message": self.message}


@dataclass
class ValidationReport:
    valid: pd.DataFrame
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    total_rows: int = 0
    rejected_rows: int = 0
    duplicate_rows: int = 0
    sampling: dict[str, float | int | None] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(e.row is None for e in self.errors)

    def summary(self) -> dict[str, object]:
        return {
            "total_rows": self.total_rows,
            "accepted_rows": len(self.valid),
            "rejected_rows": self.rejected_rows,
            "duplicate_rows": self.duplicate_rows,
            "sampling": self.sampling,
            "errors": [e.as_dict() for e in self.errors[:200]],
            "warnings": [w.as_dict() for w in self.warnings[:200]],
            "truncated": len(self.errors) > 200 or len(self.warnings) > 200,
        }


def validate_readings(
    df: pd.DataFrame,
    spec: EquipmentTypeSpec,
    *,
    id_column: str = "unit_id",
    assume_utc: bool = True,
    allow_extra: tuple[str, ...] = (),
    now: datetime | None = None,
    future_tolerance: timedelta = timedelta(minutes=5),
) -> ValidationReport:
    """Validate a frame of readings for one equipment type.

    Expected columns: ``id_column``, ``timestamp``, every required sensor of the
    spec, and optionally ``operating_hours``, ``operating_mode``.
    """
    now = now or datetime.now(UTC)
    report = ValidationReport(valid=df.iloc[0:0].copy(), total_rows=len(df))
    df = df.reset_index(drop=True).copy()

    # ---- frame level: columns ----------------------------------------------------
    sensor_names = spec.sensor_names
    expected = {id_column, "timestamp", *sensor_names, *META_COLUMNS, *allow_extra}
    unexpected = [c for c in df.columns if c not in expected and not str(c).startswith("gt_")]
    if unexpected:
        report.errors.append(
            Issue(None, None, "unexpected_columns", f"Unexpected columns: {sorted(map(str, unexpected))}")
        )
    missing = [c for c in [id_column, "timestamp", *[s.name for s in spec.sensors if s.required]] if c not in df]
    if missing:
        report.errors.append(Issue(None, None, "missing_columns", f"Missing required columns: {missing}"))
    if not report.ok:
        report.rejected_rows = len(df)
        return report

    bad = np.zeros(len(df), dtype=bool)

    def flag(mask: np.ndarray, column: str | None, code: str, msg: str) -> None:
        for i in np.flatnonzero(mask & ~bad):
            report.errors.append(Issue(int(i), column, code, msg))
        bad[:] = bad | mask

    # ---- timestamps --------------------------------------------------------------
    ts, naive = _parse_timestamps(df["timestamp"])
    flag(ts.isna().to_numpy(), "timestamp", "invalid_timestamp", "Timestamp could not be parsed")
    if naive.any():
        if not assume_utc:
            flag(naive, "timestamp", "naive_timestamp", "Timestamp must include a timezone")
        else:
            report.warnings.append(Issue(None, "timestamp", "assumed_utc", "Timestamps without timezone treated as UTC"))
    df["timestamp"] = ts
    future = (ts > pd.Timestamp(now + future_tolerance)).fillna(False).to_numpy()
    flag(future, "timestamp", "future_timestamp", "Timestamp is in the future")

    # ---- identifiers -------------------------------------------------------------
    ids = df[id_column]
    flag(ids.isna().to_numpy() | (ids.astype(str).str.strip() == "").to_numpy(), id_column, "missing_id", "Missing equipment identifier")

    # ---- sensor values -----------------------------------------------------------
    for s in spec.sensors:
        if s.name not in df:
            continue
        original = df[s.name]
        numeric = pd.to_numeric(original, errors="coerce")
        wrong_type = (numeric.isna() & original.notna()).to_numpy()
        flag(wrong_type, s.name, "invalid_type", f"{s.name} must be numeric")
        if s.required:
            flag(original.isna().to_numpy(), s.name, "missing_value", f"{s.name} is required")
        infinite = ~np.isfinite(numeric.fillna(0).to_numpy(dtype=float))
        flag(infinite, s.name, "invalid_value", f"{s.name} must be finite")
        out = ((numeric < s.valid_min) | (numeric > s.valid_max)).fillna(False).to_numpy()
        flag(out, s.name, "out_of_range", f"{s.name} outside plausible range [{s.valid_min}, {s.valid_max}] {s.unit}")
        df[s.name] = numeric.astype(float)

    if "operating_hours" in df:
        oh = pd.to_numeric(df["operating_hours"], errors="coerce")
        bad_hours = ((oh < 0) | (oh.isna() & df["operating_hours"].notna())).to_numpy()
        flag(bad_hours, "operating_hours", "invalid_value", "operating_hours must be a non-negative number")
        df["operating_hours"] = oh.astype(float)
    if "operating_mode" in df:
        modes = df["operating_mode"].fillna("normal").astype(str).str.strip().str.lower()
        flag(~modes.isin(OPERATING_MODES).to_numpy(), "operating_mode", "invalid_mode", f"operating_mode must be one of {list(OPERATING_MODES)}")
        df["operating_mode"] = modes
    else:
        df["operating_mode"] = "normal"
        report.warnings.append(Issue(None, "operating_mode", "defaulted", "operating_mode missing; defaulted to 'normal'"))

    # ---- duplicates (after timestamp normalisation) --------------------------------
    dup = df.duplicated(subset=[id_column, "timestamp"], keep="first").to_numpy() & ~bad
    report.duplicate_rows = int(dup.sum())
    flag(dup, "timestamp", "duplicate", "Duplicate reading for the same equipment and timestamp")

    valid = df[~bad].sort_values([id_column, "timestamp"]).reset_index(drop=True)
    report.valid = valid
    report.rejected_rows = int(bad.sum())
    report.sampling = sampling_summary(valid, spec, id_column)
    if report.sampling.get("irregular_intervals"):
        report.warnings.append(
            Issue(None, "timestamp", "irregular_sampling",
                  f"{report.sampling['irregular_intervals']} intervals deviate from the expected "
                  f"{spec.sampling_interval_seconds}s sampling interval")
        )
    return report


def _parse_timestamps(raw: pd.Series) -> tuple[pd.Series, np.ndarray]:
    """Parse to UTC. Returns (timestamps with NaT for unparseable, mask of values that had no timezone).

    Element-wise so a column mixing aware and naive values is handled row by row.
    """
    out: list[pd.Timestamp | None] = []
    naive = np.zeros(len(raw), dtype=bool)
    for i, v in enumerate(raw.tolist()):
        try:
            t = pd.Timestamp(v)
        except (ValueError, TypeError):
            out.append(None)
            continue
        if t is pd.NaT or pd.isna(t):
            out.append(None)
            continue
        if t.tzinfo is None:
            naive[i] = True
            t = t.tz_localize("UTC")
        out.append(t.tz_convert("UTC"))
    return pd.Series(pd.to_datetime(out, utc=True), index=raw.index), naive


def sampling_summary(df: pd.DataFrame, spec: EquipmentTypeSpec, id_column: str = "unit_id") -> dict[str, float | int | None]:
    if len(df) < 2:
        return {"expected_seconds": spec.sampling_interval_seconds, "median_seconds": None, "irregular_intervals": 0, "gaps": 0}
    d = df.groupby(id_column)["timestamp"].diff().dt.total_seconds().dropna()
    if d.empty:
        return {"expected_seconds": spec.sampling_interval_seconds, "median_seconds": None, "irregular_intervals": 0, "gaps": 0}
    exp = spec.sampling_interval_seconds
    gaps = int((d > 1.5 * exp).sum())
    too_fast = int((d < 0.5 * exp).sum())
    return {
        "expected_seconds": exp,
        "median_seconds": float(d.median()),
        "irregular_intervals": gaps + too_fast,
        "gaps": gaps,
    }
