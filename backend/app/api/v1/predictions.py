from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import AwareDatetime
from sqlalchemy import func, select

from ...core.errors import NotFound, ValidationFailed
from ...models import entities as m
from ...schemas.common import Page
from ...schemas.predictions import (
    AlertAction,
    AlertOut,
    AnomalyEventOut,
    FleetRunResult,
    ModelVersionDetail,
    ModelVersionOut,
    PredictionDetail,
    PredictionOut,
)
from ...services import alerting, audit, inference
from ...services import models_registry as registry
from ...services.presenters import alert_out, model_out, prediction_out
from ..deps import DB, AdminUser, Current, EngineerUser, client_ip
from .equipment import get_equipment

router = APIRouter(tags=["predictions"])


# ------------------------------------------------------------------ predictions
@router.post("/predictions/equipment/{equipment_id}/run", response_model=PredictionDetail, status_code=status.HTTP_201_CREATED,
             summary="Run failure, anomaly and RUL models on the latest window")
def run_prediction(equipment_id: int, db: DB, _: EngineerUser) -> PredictionOut:
    eq = get_equipment(db, equipment_id)
    pred = inference.run_for_equipment(db, eq, triggered_by="manual")
    if pred is None:
        raise ValidationFailed("No sensor readings stored for this equipment yet")
    return prediction_out(pred, eq.code, detail=True)


@router.post("/predictions/run-fleet", response_model=FleetRunResult, summary="Run predictions for all active equipment")
def run_fleet(request: Request, db: DB, user: EngineerUser) -> FleetRunResult:
    stats = inference.run_fleet(db, triggered_by="manual")
    audit.record(db, user.id, "prediction.run_fleet", "fleet", None, stats, client_ip(request))
    db.commit()
    return FleetRunResult(**stats)


@router.get("/predictions", response_model=Page[PredictionOut])
def list_predictions(
    db: DB, _: Current, equipment_id: int | None = None, risk_level: Literal["low", "elevated", "high"] | None = None,
    anomalies_only: bool = False, start: AwareDatetime | None = None, end: AwareDatetime | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
) -> Page[PredictionOut]:
    q = select(m.PredictionResult, m.Equipment.code).join(m.Equipment, m.Equipment.id == m.PredictionResult.equipment_id)
    if equipment_id is not None:
        q = q.where(m.PredictionResult.equipment_id == equipment_id)
    if risk_level:
        q = q.where(m.PredictionResult.risk_level == risk_level)
    if anomalies_only:
        q = q.where(m.PredictionResult.is_anomaly.is_(True))
    if start:
        q = q.where(m.PredictionResult.as_of >= start)
    if end:
        q = q.where(m.PredictionResult.as_of <= end)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(m.PredictionResult.as_of.desc(), m.PredictionResult.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[prediction_out(p, code) for p, code in rows], total=total, page=page, page_size=page_size)


def _get_prediction(db: DB, prediction_id: int) -> m.PredictionResult:
    p = db.get(m.PredictionResult, prediction_id)
    if p is None:
        raise NotFound("Prediction not found")
    return p


@router.get("/predictions/{prediction_id}", response_model=PredictionDetail)
def get_prediction(prediction_id: int, db: DB, _: Current) -> PredictionOut:
    p = _get_prediction(db, prediction_id)
    return prediction_out(p, db.get(m.Equipment, p.equipment_id).code, detail=True)  # type: ignore[union-attr]


@router.get("/predictions/{prediction_id}/explanation", summary="Feature contributions for one prediction")
def get_explanation(prediction_id: int, db: DB, _: Current) -> dict[str, object]:
    p = _get_prediction(db, prediction_id)
    if not p.explanation:
        return {"available": False, "reason": "No failure model ran for this prediction" if p.status == "ok" else p.status}
    return {"available": True, **p.explanation, "sensor_deviations": p.sensor_deviations}


@router.get("/anomalies", response_model=Page[AnomalyEventOut])
def list_anomalies(db: DB, _: Current, equipment_id: int | None = None, start: AwareDatetime | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)) -> Page[AnomalyEventOut]:
    q = select(m.AnomalyEvent)
    if equipment_id is not None:
        q = q.where(m.AnomalyEvent.equipment_id == equipment_id)
    if start:
        q = q.where(m.AnomalyEvent.detected_at >= start)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.AnomalyEvent.detected_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[AnomalyEventOut(id=a.id, equipment_id=a.equipment_id, equipment_code=a.equipment.code,
                                       prediction_id=a.prediction_id, detected_at=a.detected_at, score=a.score,
                                       threshold=a.threshold, sensors=a.sensors) for a in rows],
                total=total, page=page, page_size=page_size)


# ------------------------------------------------------------------ models
@router.get("/models", response_model=list[ModelVersionOut])
def list_models(db: DB, _: Current, equipment_type: str | None = None, task: str | None = None) -> list[ModelVersionOut]:
    q = select(m.ModelVersion).join(m.EquipmentType)
    if equipment_type:
        q = q.where(m.EquipmentType.key == equipment_type)
    if task:
        q = q.where(m.ModelVersion.task == task)
    return [model_out(mv) for mv in db.scalars(q.order_by(m.EquipmentType.key, m.ModelVersion.task, m.ModelVersion.trained_at.desc()))]


@router.get("/models/{model_id}", response_model=ModelVersionDetail)
def get_model(model_id: int, db: DB, _: Current) -> ModelVersionOut:
    mv = db.get(m.ModelVersion, model_id)
    if mv is None:
        raise NotFound("Model version not found")
    return model_out(mv, detail=True)


@router.post("/models/{model_id}/promote", response_model=ModelVersionOut)
def promote_model(model_id: int, request: Request, db: DB, user: AdminUser) -> ModelVersionOut:
    return model_out(registry.promote(db, model_id, user.id, client_ip(request)))


@router.post("/models/sync", summary="Register model artifacts found in MODELS_DIR")
def sync_models(request: Request, db: DB, user: AdminUser) -> dict[str, int]:
    res = registry.sync_from_disk(db)
    audit.record(db, user.id, "model.sync", "model_version", None, res, client_ip(request))
    db.commit()
    return res


# ------------------------------------------------------------------ alerts
@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    db: DB, _: Current, status_: Literal["open", "acknowledged", "resolved", "active"] | None = Query(None, alias="status"),
    equipment_id: int | None = None, kind: Literal["failure_risk", "anomaly"] | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
) -> Page[AlertOut]:
    q = select(m.Alert)
    if status_ == "active":
        q = q.where(m.Alert.status.in_(("open", "acknowledged")))
    elif status_:
        q = q.where(m.Alert.status == status_)
    if equipment_id is not None:
        q = q.where(m.Alert.equipment_id == equipment_id)
    if kind:
        q = q.where(m.Alert.kind == kind)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.Alert.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    wo: dict[int, int] = dict(db.execute(select(m.WorkOrder.alert_id, func.max(m.WorkOrder.id)).where(
        m.WorkOrder.alert_id.in_([a.id for a in rows])).group_by(m.WorkOrder.alert_id)).tuples().all()) if rows else {}  # type: ignore[arg-type]
    return Page(items=[alert_out(a, wo.get(a.id)) for a in rows], total=total, page=page, page_size=page_size)


def _get_alert(db: DB, alert_id: int) -> m.Alert:
    a = db.get(m.Alert, alert_id)
    if a is None:
        raise NotFound("Alert not found")
    return a


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def ack_alert(alert_id: int, request: Request, db: DB, user: EngineerUser) -> AlertOut:
    a = _get_alert(db, alert_id)
    alerting.acknowledge(a, user.id)
    audit.record(db, user.id, "alert.acknowledge", "alert", a.id, {}, client_ip(request))
    db.commit()
    return alert_out(a)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, body: AlertAction, request: Request, db: DB, user: EngineerUser) -> AlertOut:
    a = _get_alert(db, alert_id)
    alerting.resolve(a, body.note)
    audit.record(db, user.id, "alert.resolve", "alert", a.id, {"note": body.note}, client_ip(request))
    db.commit()
    return alert_out(a)
