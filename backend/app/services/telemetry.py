"""Sensor ingestion and retrieval.

Validation reuses ``maintenix_ml.validation`` so the API and training apply
identical rules. Storage is idempotent: re-sending a reading for the same
equipment and timestamp is reported as ``already_stored`` and not duplicated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from maintenix_ml.equipment_types import get_spec
from maintenix_ml.validation import validate_readings
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..core.errors import ValidationFailed
from ..models import entities as m

_CHUNK = 1000


def readings_to_frame(equipment: m.Equipment, readings: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for r in readings:
        row = {"unit_id": equipment.code, "timestamp": r["recorded_at"], "operating_hours": r.get("operating_hours"),
               "operating_mode": r.get("operating_mode", "normal")}
        row.update(r["values"])
        rows.append(row)
    return pd.DataFrame(rows)


def ingest_frame(
    db: Session, equipment: m.Equipment, df: pd.DataFrame, data_source: str, *, assume_utc: bool,
    row_offset: int = 0,
) -> dict[str, Any]:
    """Validate and store readings for one equipment. Commits on success."""
    if equipment.status == "decommissioned":
        raise ValidationFailed("Equipment is decommissioned; readings are not accepted")
    if equipment.data_source == "simulated" and data_source != "simulated":
        raise ValidationFailed("This equipment holds SIMULATED data; only simulated readings may be added to it")
    spec = get_spec(equipment.equipment_type.key)
    report = validate_readings(df, spec, assume_utc=assume_utc)
    summary = report.summary()
    for key in ("errors", "warnings"):
        for issue in summary[key]:
            if issue["row"] is not None:
                issue["row"] += row_offset
    if not report.ok:
        raise ValidationFailed("Readings rejected", summary)

    sensors = {s.name: s.id for s in equipment.equipment_type.sensors}
    valid = report.valid
    inserted = 0
    for start in range(0, len(valid), _CHUNK):
        chunk = valid.iloc[start : start + _CHUNK]
        stmt = insert(m.SensorReading).values([
            {"equipment_id": equipment.id, "recorded_at": r.timestamp.to_pydatetime(),
             "operating_hours": None if pd.isna(r.operating_hours) else float(r.operating_hours),
             "operating_mode": r.operating_mode, "data_source": data_source}
            for r in chunk.assign(operating_hours=chunk.get("operating_hours")).itertuples(index=False)
        ]).on_conflict_do_nothing(constraint="uq_sensor_readings_equipment_time").returning(
            m.SensorReading.id, m.SensorReading.recorded_at)
        new = {ts: rid for rid, ts in db.execute(stmt).all()}
        if not new:
            continue
        values = []
        for r in chunk.itertuples(index=False):
            rid = new.get(r.timestamp.to_pydatetime())
            if rid is None:
                continue
            for name, sid in sensors.items():
                v = getattr(r, name, None)
                if v is not None and not pd.isna(v):
                    values.append({"reading_id": rid, "sensor_id": sid, "value": float(v)})
        if values:
            db.execute(insert(m.SensorValue).values(values))
        inserted += len(new)
    db.commit()
    summary["already_stored"] = len(valid) - inserted
    summary["accepted_rows"] = inserted
    return summary


def load_window(db: Session, equipment: m.Equipment, n: int, as_of: datetime | None = None) -> pd.DataFrame:
    """Most recent ``n`` readings (oldest first) as a frame with one column per sensor."""
    q = select(m.SensorReading.id, m.SensorReading.recorded_at, m.SensorReading.operating_mode,
               m.SensorReading.operating_hours).where(m.SensorReading.equipment_id == equipment.id)
    if as_of is not None:
        q = q.where(m.SensorReading.recorded_at <= as_of)
    rows = db.execute(q.order_by(m.SensorReading.recorded_at.desc()).limit(n)).all()
    if not rows:
        return pd.DataFrame()
    ids = [r.id for r in rows]
    vals = db.execute(select(m.SensorValue.reading_id, m.SensorDefinition.name, m.SensorValue.value)
                      .join(m.SensorDefinition, m.SensorDefinition.id == m.SensorValue.sensor_id)
                      .where(m.SensorValue.reading_id.in_(ids))).all()
    frame = pd.DataFrame([{"id": r.id, "timestamp": r.recorded_at, "operating_mode": r.operating_mode,
                           "operating_hours": float(r.operating_hours) if r.operating_hours is not None else None} for r in rows])
    if vals:
        wide = pd.DataFrame(vals, columns=["id", "sensor", "value"]).pivot(index="id", columns="sensor", values="value")
        frame = frame.merge(wide, left_on="id", right_index=True, how="left")
    return frame.sort_values("timestamp").reset_index(drop=True)


def reading_count(db: Session, equipment_id: int) -> int:
    return db.scalar(select(func.count()).select_from(m.SensorReading).where(m.SensorReading.equipment_id == equipment_id)) or 0


def latest_reading(db: Session, equipment: m.Equipment) -> dict[str, Any] | None:
    w = load_window(db, equipment, 1)
    if w.empty:
        return None
    r = w.iloc[-1]
    return {"recorded_at": r["timestamp"], "operating_mode": r["operating_mode"], "operating_hours": r["operating_hours"],
            "values": {s.name: float(r[s.name]) for s in equipment.equipment_type.sensors if s.name in r and pd.notna(r[s.name])}}

