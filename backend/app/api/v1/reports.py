from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime
from sqlalchemy import select

from ...models import entities as m
from ...services import audit
from ...services.inference import health_state
from ...services.reports import csv_stream
from ..deps import DB, Current, client_ip

router = APIRouter(prefix="/reports", tags=["reports"])


def _response(name: str, header: list[str], rows: Sequence[Sequence[Any]]) -> StreamingResponse:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return StreamingResponse(csv_stream(header, rows), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="maintenix_{name}_{stamp}.csv"'})


@router.get("/equipment.csv", response_class=StreamingResponse)
def equipment_report(request: Request, db: DB, user: Current, equipment_type: str | None = None,
                     status: str | None = None) -> StreamingResponse:
    q = select(m.Equipment).join(m.EquipmentType)
    if equipment_type:
        q = q.where(m.EquipmentType.key == equipment_type)
    if status:
        q = q.where(m.Equipment.status == status)
    rows = []
    for e in db.scalars(q.order_by(m.Equipment.code)).unique():
        p = e.latest_prediction
        rows.append([e.code, e.name, e.equipment_type.key, e.location, e.status, e.criticality, e.data_source,
                     health_state(p), p.failure_probability if p else None, p.risk_level if p else None,
                     p.is_anomaly if p else None, p.rul_hours if p and p.rul_status == "ok" else None,
                     p.rul_status if p else None, p.as_of if p else None, e.last_maintenance_at])
    audit.record(db, user.id, "report.export", "report", "equipment", {"rows": len(rows)}, client_ip(request))
    db.commit()
    return _response("equipment", ["code", "name", "type", "location", "status", "criticality", "data_source", "health_state",
                                   "failure_probability", "risk_level", "is_anomaly", "rul_hours", "rul_status",
                                   "prediction_as_of", "last_maintenance_at"], rows)


@router.get("/predictions.csv", response_class=StreamingResponse)
def predictions_report(request: Request, db: DB, user: Current, equipment_id: int | None = None,
                       start: AwareDatetime | None = None, end: AwareDatetime | None = None,
                       risk_level: Literal["low", "elevated", "high"] | None = None) -> StreamingResponse:
    q = select(m.PredictionResult, m.Equipment.code).join(m.Equipment, m.Equipment.id == m.PredictionResult.equipment_id)
    if equipment_id is not None:
        q = q.where(m.PredictionResult.equipment_id == equipment_id)
    if start:
        q = q.where(m.PredictionResult.as_of >= start)
    if end:
        q = q.where(m.PredictionResult.as_of <= end)
    if risk_level:
        q = q.where(m.PredictionResult.risk_level == risk_level)
    rows = [[p.id, code, p.as_of, p.status, p.failure_probability, p.risk_level, p.anomaly_score, p.is_anomaly,
             p.rul_hours, p.rul_status, p.failure_model_id, p.triggered_by]
            for p, code in db.execute(q.order_by(m.PredictionResult.as_of.desc()).limit(100_000)).all()]
    audit.record(db, user.id, "report.export", "report", "predictions", {"rows": len(rows)}, client_ip(request))
    db.commit()
    return _response("predictions", ["id", "equipment_code", "as_of", "status", "failure_probability", "risk_level",
                                     "anomaly_score", "is_anomaly", "rul_hours", "rul_status", "failure_model_id",
                                     "triggered_by"], rows)


@router.get("/maintenance.csv", response_class=StreamingResponse)
def maintenance_report(request: Request, db: DB, user: Current, equipment_id: int | None = None,
                       status: str | None = None) -> StreamingResponse:
    q = select(m.WorkOrder)
    if equipment_id is not None:
        q = q.where(m.WorkOrder.equipment_id == equipment_id)
    if status:
        q = q.where(m.WorkOrder.status == status)
    rows = []
    for w in db.scalars(q.order_by(m.WorkOrder.created_at.desc())).unique():
        r = w.record
        rows.append([w.code, w.equipment.code, w.title, w.priority, w.status, w.assigned_to.full_name if w.assigned_to else None,
                     w.due_date, w.created_at, w.started_at, w.completed_at, r.action_taken if r else None,
                     r.summary if r else None, r.parts_replaced if r else None, float(r.downtime_hours) if r else None,
                     w.cancel_reason])
    audit.record(db, user.id, "report.export", "report", "maintenance", {"rows": len(rows)}, client_ip(request))
    db.commit()
    return _response("maintenance", ["work_order", "equipment_code", "title", "priority", "status", "assigned_to",
                                     "due_date", "created_at", "started_at", "completed_at", "action_taken", "summary",
                                     "parts_replaced", "downtime_hours", "cancel_reason"], rows)
