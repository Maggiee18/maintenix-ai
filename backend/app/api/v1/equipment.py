from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from ...core.errors import Conflict, NotFound, ValidationFailed
from ...models import entities as m
from ...schemas.common import Page
from ...schemas.equipment import (
    EquipmentCreate,
    EquipmentDetail,
    EquipmentOut,
    EquipmentTypeOut,
    EquipmentUpdate,
    HealthHistoryOut,
    HealthHistoryPoint,
    SimulationInfo,
    StatusChange,
)
from ...services import audit, telemetry
from ...services.presenters import equipment_out
from ..deps import DB, Current, EngineerUser, client_ip

router = APIRouter(tags=["equipment"])


def get_equipment(db: DB, equipment_id: int) -> m.Equipment:
    eq = db.get(m.Equipment, equipment_id)
    if eq is None:
        raise NotFound("Equipment not found")
    return eq


def open_alert_counts(db: DB, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.execute(select(m.Alert.equipment_id, func.count()).where(
        m.Alert.equipment_id.in_(ids), m.Alert.status.in_(("open", "acknowledged"))).group_by(m.Alert.equipment_id)).all()
    return dict(rows)  # type: ignore[arg-type]


@router.get("/equipment-types", response_model=list[EquipmentTypeOut])
def list_types(db: DB, _: Current) -> list[EquipmentTypeOut]:
    return [EquipmentTypeOut.model_validate(t) for t in db.scalars(select(m.EquipmentType).order_by(m.EquipmentType.display_name))]




@router.get("/equipment", response_model=Page[EquipmentOut])
def list_equipment(
    db: DB, _: Current,
    search: str | None = Query(None, max_length=100),
    equipment_type: str | None = None,
    status_: str | None = Query(None, alias="status"),
    health: Literal["healthy", "watch", "at_risk", "critical", "unknown"] | None = None,
    sort: Literal["code", "name", "risk", "updated"] = "code",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
) -> Page[EquipmentOut]:
    P = aliased(m.PredictionResult)
    q = select(m.Equipment).join(m.EquipmentType).outerjoin(P, P.id == m.Equipment.latest_prediction_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(m.Equipment.code.ilike(like), m.Equipment.name.ilike(like), m.Equipment.location.ilike(like)))
    if equipment_type:
        q = q.where(m.EquipmentType.key == equipment_type)
    if status_:
        q = q.where(m.Equipment.status == status_)
    if health == "critical":
        q = q.where(P.risk_level == "high")
    elif health == "at_risk":
        q = q.where(P.risk_level == "elevated")
    elif health == "watch":
        q = q.where(P.risk_level == "low", P.is_anomaly.is_(True))
    elif health == "healthy":
        q = q.where(P.status == "ok", P.risk_level == "low", P.is_anomaly.is_not(True))
    elif health == "unknown":
        q = q.where(or_(P.id.is_(None), P.status != "ok"))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    order = {"code": m.Equipment.code, "name": m.Equipment.name, "updated": m.Equipment.updated_at.desc(),
             "risk": P.failure_probability.desc().nulls_last()}[sort]
    rows = db.scalars(q.order_by(order, m.Equipment.id).offset((page - 1) * page_size).limit(page_size)).unique().all()
    counts = open_alert_counts(db, [e.id for e in rows])
    return Page(items=[equipment_out(e, counts.get(e.id, 0)) for e in rows], total=total, page=page, page_size=page_size)


@router.post("/equipment", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
def create_equipment(body: EquipmentCreate, request: Request, db: DB, user: EngineerUser) -> EquipmentOut:
    et = db.scalar(select(m.EquipmentType).where(m.EquipmentType.key == body.equipment_type))
    if et is None:
        raise ValidationFailed(f"Unknown equipment type '{body.equipment_type}'")
    eq = m.Equipment(**body.model_dump(exclude={"equipment_type"}), equipment_type_id=et.id, data_source="api",
                     created_by_id=user.id)
    db.add(eq)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Equipment code '{body.code}' already exists") from exc
    audit.record(db, user.id, "equipment.create", "equipment", eq.id, {"code": eq.code}, client_ip(request))
    db.commit()
    db.refresh(eq)
    return equipment_out(eq)


@router.get("/equipment/{equipment_id}", response_model=EquipmentDetail)
def equipment_detail(equipment_id: int, db: DB, _: Current) -> EquipmentDetail:
    from ...schemas.equipment import EquipmentTypeOut as ETO

    eq = get_equipment(db, equipment_id)
    base = equipment_out(eq, open_alert_counts(db, [eq.id]).get(eq.id, 0))
    sim = None
    if eq.data_source == "simulated" and eq.simulation_seed is not None and eq.simulation_offset is not None:
        sim = SimulationInfo(seed=eq.simulation_seed, first_reading_index=eq.simulation_offset)
    return EquipmentDetail(**base.model_dump(), type_info=ETO.model_validate(eq.equipment_type), simulation=sim,
                           latest_reading=telemetry.latest_reading(db, eq), reading_count=telemetry.reading_count(db, eq.id))


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
def update_equipment(equipment_id: int, body: EquipmentUpdate, request: Request, db: DB, user: EngineerUser) -> EquipmentOut:
    eq = get_equipment(db, equipment_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(eq, k, v)
    audit.record(db, user.id, "equipment.update", "equipment", eq.id, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return equipment_out(eq)


@router.post("/equipment/{equipment_id}/status", response_model=EquipmentOut)
def change_status(equipment_id: int, body: StatusChange, request: Request, db: DB, user: EngineerUser) -> EquipmentOut:
    eq = get_equipment(db, equipment_id)
    if eq.status == "decommissioned":
        raise Conflict("Decommissioned equipment cannot change status")
    if body.status == "decommissioned":
        active = db.scalar(select(func.count()).select_from(m.WorkOrder).where(
            m.WorkOrder.equipment_id == eq.id, m.WorkOrder.status.in_(("open", "assigned", "in_progress"))))
        if active:
            raise Conflict("Close or cancel active work orders before decommissioning")
    old = eq.status
    eq.status = body.status
    audit.record(db, user.id, "equipment.status", "equipment", eq.id, {"from": old, "to": body.status, "reason": body.reason},
                 client_ip(request))
    db.commit()
    return equipment_out(eq)


@router.get("/equipment/{equipment_id}/health-history", response_model=HealthHistoryOut)
def health_history(equipment_id: int, db: DB, _: Current, limit: int = Query(500, ge=1, le=5000)) -> HealthHistoryOut:
    eq = get_equipment(db, equipment_id)
    preds = db.scalars(select(m.PredictionResult).where(m.PredictionResult.equipment_id == eq.id,
                                                        m.PredictionResult.status == "ok")
                       .order_by(m.PredictionResult.as_of.desc()).limit(limit)).all()
    recs = db.scalars(select(m.MaintenanceRecord).where(m.MaintenanceRecord.equipment_id == eq.id)
                      .order_by(m.MaintenanceRecord.completed_at.desc())).all()
    return HealthHistoryOut(
        equipment_id=eq.id,
        points=[HealthHistoryPoint(as_of=p.as_of, failure_probability=p.failure_probability, risk_level=p.risk_level,
                                   anomaly_score=p.anomaly_score, is_anomaly=p.is_anomaly, rul_hours=p.rul_hours)
                for p in reversed(preds)],
        maintenance=[{"completed_at": r.completed_at, "action_taken": r.action_taken, "summary": r.summary,
                      "restores_health": r.restores_health, "work_order_id": r.work_order_id} for r in recs],
    )
