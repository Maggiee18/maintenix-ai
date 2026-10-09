"""Fleet-level aggregates. Every number here is computed from database rows; see docs/api-guide.md for definitions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import Float, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased

from ...models import entities as m
from ...services.presenters import alert_out, equipment_out
from ..deps import DB, Current

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
P = aliased(m.PredictionResult)


def _health_case() -> Any:
    return case(
        (or_(P.id.is_(None), P.status != "ok"), "unknown"),
        (P.risk_level == "high", "critical"),
        (P.risk_level == "elevated", "at_risk"),
        (P.is_anomaly.is_(True), "watch"),
        else_="healthy",
    )


def _active_equipment() -> Any:
    return select(m.Equipment.id).where(m.Equipment.status != "decommissioned")


@router.get("/summary", summary="Headline fleet KPIs")
def summary(db: DB, _: Current) -> dict[str, Any]:
    health = _health_case()
    row = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(m.Equipment.status == "operational").label("operational"),
            func.count().filter(m.Equipment.status == "under_maintenance").label("under_maintenance"),
            func.count().filter(health.in_(("watch", "at_risk", "critical"))).label("attention"),
            func.count().filter(health == "critical").label("high_risk"),
            func.count().filter(m.Equipment.data_source == "simulated").label("simulated"),
        ).select_from(m.Equipment).outerjoin(P, P.id == m.Equipment.latest_prediction_id)
        .where(m.Equipment.status != "decommissioned")
    ).one()
    open_wo = db.scalar(select(func.count()).select_from(m.WorkOrder).where(m.WorkOrder.status.in_(("open", "assigned", "in_progress"))))
    active_alerts = db.scalar(select(func.count()).select_from(m.Alert).where(m.Alert.status.in_(("open", "acknowledged"))))
    recent = db.scalars(select(m.Alert).where(m.Alert.status.in_(("open", "acknowledged")))
                        .order_by(m.Alert.last_seen_at.desc()).limit(8)).all()
    last_pred = db.scalar(select(func.max(m.PredictionResult.created_at)))
    return {
        "total_equipment": row.total, "operational": row.operational, "under_maintenance": row.under_maintenance,
        "requiring_attention": row.attention, "high_risk": row.high_risk, "open_work_orders": open_wo,
        "active_alerts": active_alerts, "simulated_equipment": row.simulated, "last_prediction_at": last_pred,
        "recent_alerts": [alert_out(a).model_dump() for a in recent],
        "definitions": {
            "requiring_attention": "latest prediction is watch (anomaly), at_risk (elevated risk) or critical (high risk)",
            "high_risk": "latest failure probability is at or above the type's critical threshold",
        },
    }


@router.get("/health-distribution")
def health_distribution(db: DB, _: Current) -> dict[str, Any]:
    health = _health_case().label("health")
    rows = db.execute(select(m.EquipmentType.display_name, health, func.count())
                      .select_from(m.Equipment).join(m.EquipmentType)
                      .outerjoin(P, P.id == m.Equipment.latest_prediction_id)
                      .where(m.Equipment.status != "decommissioned").group_by(m.EquipmentType.display_name, health)).all()
    states = ["healthy", "watch", "at_risk", "critical", "unknown"]
    overall = {s: 0 for s in states}
    by_type: dict[str, dict[str, int]] = {}
    for t, h, n in rows:
        overall[h] += n
        by_type.setdefault(t, {s: 0 for s in states})[h] = n
    return {"overall": overall, "by_type": by_type}


@router.get("/high-risk")
def high_risk(db: DB, _: Current, limit: int = Query(10, ge=1, le=50)) -> list[dict[str, Any]]:
    rows = db.scalars(select(m.Equipment).join(P, P.id == m.Equipment.latest_prediction_id)
                      .where(m.Equipment.status != "decommissioned", P.status == "ok",
                             or_(P.risk_level.in_(("elevated", "high")), P.is_anomaly.is_(True)))
                      .order_by(P.failure_probability.desc().nulls_last()).limit(limit)).unique().all()
    return [equipment_out(e).model_dump() for e in rows]


@router.get("/prediction-trends", summary="Daily mean failure probability and counts of elevated/high predictions")
def prediction_trends(db: DB, _: Current, days: int = Query(14, ge=1, le=180)) -> list[dict[str, Any]]:
    end = db.scalar(select(func.max(m.PredictionResult.as_of))) or datetime.now(UTC)
    start = end - timedelta(days=days)
    day = func.date_trunc("day", m.PredictionResult.as_of).label("day")
    rows = db.execute(select(day, func.avg(m.PredictionResult.failure_probability),
                             func.count().filter(m.PredictionResult.risk_level == "elevated"),
                             func.count().filter(m.PredictionResult.risk_level == "high"),
                             func.count().filter(m.PredictionResult.is_anomaly.is_(True)), func.count())
                      .where(m.PredictionResult.as_of >= start, m.PredictionResult.status == "ok")
                      .group_by(day).order_by(day)).all()
    return [{"day": d, "mean_failure_probability": float(a) if a is not None else None, "elevated": e, "high": h,
             "anomalies": an, "predictions": n} for d, a, e, h, an, n in rows]


@router.get("/sensor-trends", summary="Hourly mean of one sensor across all equipment of a type")
def sensor_trends(db: DB, _: Current, equipment_type: str = "centrifugal_pump", sensor: str = "vibration",
                  days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    et = db.scalar(select(m.EquipmentType).where(m.EquipmentType.key == equipment_type))
    if et is None:
        return {"equipment_type": equipment_type, "sensor": sensor, "points": []}
    sd = next((s for s in et.sensors if s.name == sensor), None)
    if sd is None:
        return {"equipment_type": equipment_type, "sensor": sensor, "points": []}
    end = db.scalar(select(func.max(m.SensorReading.recorded_at)).join(m.Equipment)
                    .where(m.Equipment.equipment_type_id == et.id)) or datetime.now(UTC)
    hour = func.date_trunc("hour", m.SensorReading.recorded_at).label("t")
    rows = db.execute(select(m.Equipment.code, hour, func.avg(m.SensorValue.value))
                      .join(m.SensorReading, m.SensorReading.equipment_id == m.Equipment.id)
                      .join(m.SensorValue, and_(m.SensorValue.reading_id == m.SensorReading.id, m.SensorValue.sensor_id == sd.id))
                      .where(m.Equipment.equipment_type_id == et.id, m.Equipment.status != "decommissioned",
                             m.SensorReading.recorded_at >= end - timedelta(days=days))
                      .group_by(m.Equipment.code, hour).order_by(hour)).all()
    series: dict[datetime, dict[str, float]] = {}
    codes: set[str] = set()
    for code, t, v in rows:
        series.setdefault(t, {})[code] = round(float(v), 3)
        codes.add(code)
    return {"equipment_type": equipment_type, "sensor": sensor, "unit": sd.unit, "normal_min": sd.normal_min,
            "normal_max": sd.normal_max, "equipment": sorted(codes),
            "points": [{"t": t, **vals} for t, vals in sorted(series.items())]}


@router.get("/maintenance-backlog")
def maintenance_backlog(db: DB, _: Current) -> dict[str, Any]:
    active = m.WorkOrder.status.in_(("open", "assigned", "in_progress"))
    by_status: dict[str, int] = dict(db.execute(select(m.WorkOrder.status, func.count()).where(active).group_by(m.WorkOrder.status)).tuples().all())
    by_priority: dict[str, int] = dict(
        db.execute(select(m.WorkOrder.priority, func.count()).where(active).group_by(m.WorkOrder.priority)).tuples().all())
    overdue = db.scalar(select(func.count()).select_from(m.WorkOrder).where(active, m.WorkOrder.due_date < date.today()))
    since = datetime.now(UTC) - timedelta(days=30)
    done = db.execute(select(func.count(), func.avg(cast(func.extract("epoch", m.WorkOrder.completed_at - m.WorkOrder.created_at), Float) / 3600))
                      .where(m.WorkOrder.status == "completed", m.WorkOrder.completed_at >= since)).one()
    return {"by_status": {s: by_status.get(s, 0) for s in ("open", "assigned", "in_progress")},
            "by_priority": {p: by_priority.get(p, 0) for p in ("critical", "high", "medium", "low")},
            "overdue": overdue, "completed_last_30_days": done[0],
            "mean_hours_to_complete_last_30_days": round(done[1], 1) if done[1] is not None else None}
