from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import AwareDatetime
from sqlalchemy import func, select

from maintenix_ml.adapters.canonical_csv import CanonicalCsvAdapter
from maintenix_ml.equipment_types import get_spec

from ...core.config import get_settings
from ...core.errors import AppError, ValidationFailed
from ...models import entities as m
from ...schemas.common import Page
from ...schemas.sensors import BatchIngest, IngestIssue, IngestReport, ReadingOut, SeriesOut, SeriesPoint, SingleIngest
from ...services import inference, telemetry
from ..deps import DB, Current, EngineerUser
from .equipment import get_equipment

router = APIRouter(prefix="/sensors", tags=["sensors"])


def _prediction_summary(pred: m.PredictionResult | None) -> list[dict[str, Any]]:
    if pred is None:
        return []
    return [{"prediction_id": pred.id, "equipment_id": pred.equipment_id, "status": pred.status,
             "failure_probability": pred.failure_probability, "risk_level": pred.risk_level,
             "is_anomaly": pred.is_anomaly, "rul_hours": pred.rul_hours, "rul_status": pred.rul_status}]


def _ingest(db: DB, eq: m.Equipment, readings: list[dict[str, Any]], source: str, run: bool) -> IngestReport:
    report = telemetry.ingest_frame(db, eq, telemetry.readings_to_frame(eq, readings), source, assume_utc=False)
    preds = []
    if run and report["accepted_rows"]:
        preds = _prediction_summary(inference.run_for_equipment(db, eq, triggered_by="ingestion"))
    return IngestReport(**report, equipment_ids=[eq.id], predictions=preds)


@router.post("/readings", response_model=IngestReport, status_code=status.HTTP_201_CREATED,
             summary="Ingest one reading, then run inference on the latest window")
def ingest_one(body: SingleIngest, db: DB, _: EngineerUser) -> IngestReport:
    eq = get_equipment(db, body.equipment_id)
    source = "simulated" if eq.data_source == "simulated" else "api"
    return _ingest(db, eq, [body.model_dump(exclude={"equipment_id", "run_inference"})], source, body.run_inference)


@router.post("/readings/batch", response_model=IngestReport, status_code=status.HTTP_201_CREATED,
             summary="Ingest many readings for one equipment (inference runs once, on the latest window)")
def ingest_batch(body: BatchIngest, db: DB, _: EngineerUser) -> IngestReport:
    if len(body.readings) > get_settings().max_batch_rows:
        raise ValidationFailed(f"At most {get_settings().max_batch_rows} readings per batch")
    eq = get_equipment(db, body.equipment_id)
    return _ingest(db, eq, [r.model_dump() for r in body.readings], body.data_source, body.run_inference)


@router.post("/readings/validate", response_model=IngestReport, summary="Dry-run validation, nothing is stored")
def validate_batch(body: BatchIngest, db: DB, _: Current) -> IngestReport:
    from maintenix_ml.validation import validate_readings

    eq = get_equipment(db, body.equipment_id)
    rep = validate_readings(telemetry.readings_to_frame(eq, [r.model_dump() for r in body.readings]),
                            get_spec(eq.equipment_type.key), assume_utc=False).summary()
    return IngestReport(**rep, equipment_ids=[eq.id])


@router.post("/readings/upload", response_model=IngestReport, status_code=status.HTTP_201_CREATED,
             summary="Upload a CSV (columns: equipment_code, timestamp, operating_mode, operating_hours, <sensors>)")
async def upload_csv(
    db: DB, _: EngineerUser, file: UploadFile = File(...),
    run_inference: bool = Form(True), data_source: Literal["imported", "api"] = Form("imported"),
) -> IngestReport:
    s = get_settings()
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationFailed("Only .csv files are accepted")
    if file.content_type not in ("text/csv", "application/vnd.ms-excel", "application/octet-stream", "text/plain"):
        raise ValidationFailed(f"Unsupported content type {file.content_type}")
    raw = await file.read(s.max_upload_bytes + 1)
    if len(raw) > s.max_upload_bytes:
        raise ValidationFailed(f"File larger than {s.max_upload_bytes // (1024 * 1024)} MB")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("File must be UTF-8 encoded text") from exc
    try:
        df = CanonicalCsvAdapter(raw, get_spec("centrifugal_pump"), equipment_column="equipment_code").load()
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValidationFailed("Could not parse CSV") from exc
    if "unit_id" not in df:
        raise ValidationFailed("CSV must have an 'equipment_code' column")
    if len(df) > s.max_batch_rows * 10:
        raise ValidationFailed("Too many rows in one upload")

    total = IngestReport(total_rows=len(df), accepted_rows=0, rejected_rows=0, duplicate_rows=0)
    df["_row"] = range(len(df))
    codes = df["unit_id"].fillna("").astype(str).str.strip().str.upper()
    known = {e.code: e for e in db.scalars(select(m.Equipment).where(m.Equipment.code.in_(codes.unique().tolist())))}
    for code, group in df.groupby(codes, sort=False):
        eq = known.get(code)
        if eq is None:
            total.rejected_rows += len(group)
            total.errors += [IngestIssue(row=int(r), column="equipment_code", code="unknown_equipment",
                                         message=f"Unknown equipment code '{code}'") for r in group["_row"][:50]]
            continue
        spec = get_spec(eq.equipment_type.key)
        cols = ["unit_id", "timestamp", "operating_mode", "operating_hours", *spec.sensor_names]
        extra = [c for c in group.columns if c not in cols and c != "_row" and group[c].notna().any()]
        part = group[[c for c in group.columns if c in cols or c in extra]].reset_index(drop=True)
        source = "simulated" if eq.data_source == "simulated" else data_source
        try:
            rep = telemetry.ingest_frame(db, eq, part, source, assume_utc=True, row_offset=0)
        except AppError as exc:
            db.rollback()
            total.rejected_rows += len(group)
            for e in (exc.details or {}).get("errors", [{"row": None, "column": None, "code": exc.code, "message": exc.message}]):
                e = dict(e)
                if e.get("row") is not None:
                    e["row"] = int(group["_row"].iloc[e["row"]])
                total.errors.append(IngestIssue(**e))
            continue
        total.accepted_rows += rep["accepted_rows"]
        total.rejected_rows += rep["rejected_rows"]
        total.duplicate_rows += rep["duplicate_rows"]
        total.already_stored += rep["already_stored"]
        for key in ("errors", "warnings"):
            for e in rep[key]:
                if e.get("row") is not None:
                    e["row"] = int(group["_row"].iloc[e["row"]])
                getattr(total, key).append(IngestIssue(**e))
        total.equipment_ids.append(eq.id)
        if run_inference and rep["accepted_rows"]:
            total.predictions += _prediction_summary(inference.run_for_equipment(db, eq, triggered_by="ingestion"))
    total.errors = total.errors[:200]
    total.warnings = total.warnings[:200]
    return total


@router.get("/readings", response_model=Page[ReadingOut])
def query_readings(
    db: DB, _: Current, equipment_id: int, start: AwareDatetime | None = None, end: AwareDatetime | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=1000),
) -> Page[ReadingOut]:
    eq = get_equipment(db, equipment_id)
    q = select(m.SensorReading).where(m.SensorReading.equipment_id == eq.id)
    if start:
        q = q.where(m.SensorReading.recorded_at >= start)
    if end:
        q = q.where(m.SensorReading.recorded_at <= end)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.SensorReading.recorded_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [ReadingOut(id=r.id, equipment_id=r.equipment_id, recorded_at=r.recorded_at,
                        operating_hours=float(r.operating_hours) if r.operating_hours is not None else None,
                        operating_mode=r.operating_mode, data_source=r.data_source,
                        values={v.sensor.name: v.value for v in r.values}) for r in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/latest", response_model=list[dict[str, Any]], summary="Latest reading for each equipment (or one)")
def latest(db: DB, _: Current, equipment_id: int | None = None) -> list[dict[str, Any]]:
    q = select(m.Equipment).where(m.Equipment.status != "decommissioned")
    if equipment_id is not None:
        q = q.where(m.Equipment.id == equipment_id)
    out = []
    for eq in db.scalars(q.order_by(m.Equipment.code)).all():
        r = telemetry.latest_reading(db, eq)
        out.append({"equipment_id": eq.id, "equipment_code": eq.code, "equipment_type": eq.equipment_type.key,
                    "data_source": eq.data_source, "reading": r})
    return out


@router.get("/equipment/{equipment_id}/series", response_model=SeriesOut,
            summary="Sensor time series for charts, optionally averaged per hour or day")
def series(
    equipment_id: int, db: DB, _: Current, sensors: list[str] | None = Query(None),
    start: AwareDatetime | None = None, end: AwareDatetime | None = None,
    bucket: Literal["raw", "hour", "day"] = "hour", days: int = Query(7, ge=1, le=365),
) -> SeriesOut:
    eq = get_equipment(db, equipment_id)
    defs = {s.name: s.id for s in eq.equipment_type.sensors}
    names = sensors or list(defs)
    unknown = [n for n in names if n not in defs]
    if unknown:
        raise ValidationFailed(f"Unknown sensors for this equipment: {unknown}")
    if end is None:
        end = db.scalar(select(func.max(m.SensorReading.recorded_at)).where(m.SensorReading.equipment_id == eq.id))
        if end is None:
            return SeriesOut(equipment_id=eq.id, bucket=bucket, sensors=names, points=[])
    start = start or (end - timedelta(days=days))
    t = m.SensorReading.recorded_at if bucket == "raw" else func.date_trunc(bucket, m.SensorReading.recorded_at)
    q = (select(t.label("t"), m.SensorDefinition.name, func.avg(m.SensorValue.value))
         .join(m.SensorValue, m.SensorValue.reading_id == m.SensorReading.id)
         .join(m.SensorDefinition, m.SensorDefinition.id == m.SensorValue.sensor_id)
         .where(m.SensorReading.equipment_id == eq.id, m.SensorReading.recorded_at >= start,
                m.SensorReading.recorded_at <= end, m.SensorDefinition.name.in_(names))
         .group_by("t", m.SensorDefinition.name).order_by("t").limit(20000))
    points: dict[datetime, dict[str, float | None]] = {}
    for ts, name, val in db.execute(q).all():
        points.setdefault(ts, {n: None for n in names})[name] = float(val) if val is not None else None
    return SeriesOut(equipment_id=eq.id, bucket=bucket, sensors=names,
                     points=[SeriesPoint(t=k, values=v) for k, v in sorted(points.items())])
