from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ...core.errors import Conflict, NotFound, ValidationFailed
from ...core.security import hash_password
from ...models import entities as m
from ...schemas.common import Message, Page
from ...schemas.predictions import ThresholdOut, ThresholdUpdate
from ...schemas.users import PasswordReset, UserCreate, UserOut, UserUpdate
from ...services import audit
from ...services.models_registry import production_thresholds
from ..deps import DB, AdminUser, Current, client_ip

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=Page[UserOut])
def list_users(db: DB, _: AdminUser, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> Page[UserOut]:
    total = db.scalar(select(func.count()).select_from(m.User)) or 0
    rows = db.scalars(select(m.User).order_by(m.User.email).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, db: DB, admin: AdminUser) -> UserOut:
    role = db.scalar(select(m.Role).where(m.Role.name == body.role))
    user = m.User(email=body.email, full_name=body.full_name, role=role, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("A user with this email already exists") from exc
    audit.record(db, admin.id, "user.create", "user", user.id, {"email": user.email, "role": body.role}, client_ip(request))
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, db: DB, admin: AdminUser) -> UserOut:
    user = db.get(m.User, user_id)
    if user is None:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise ValidationFailed("You cannot deactivate or demote your own account")
    if "role" in changes:
        user.role = db.scalar(select(m.Role).where(m.Role.name == changes["role"]))  # type: ignore[assignment]
    if "full_name" in changes:
        user.full_name = changes["full_name"]
    if "is_active" in changes:
        user.is_active = changes["is_active"]
    audit.record(db, admin.id, "user.update", "user", user.id, changes, client_ip(request))
    db.commit()
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password", response_model=Message)
def reset_password(user_id: int, body: PasswordReset, request: Request, db: DB, admin: AdminUser) -> Message:
    user = db.get(m.User, user_id)
    if user is None:
        raise NotFound("User not found")
    user.password_hash = hash_password(body.password)
    audit.record(db, admin.id, "user.reset_password", "user", user.id, {}, client_ip(request))
    db.commit()
    return Message(message="Password updated")


@router.get("/audit-events")
def audit_events(db: DB, _: AdminUser, action: str | None = None, actor_id: int | None = None,
                 start: AwareDatetime | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200)) -> dict[str, object]:
    q = select(m.AuditEvent)
    if action:
        q = q.where(m.AuditEvent.action.ilike(f"{action}%"))
    if actor_id is not None:
        q = q.where(m.AuditEvent.actor_id == actor_id)
    if start:
        q = q.where(m.AuditEvent.created_at >= start)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": a.id, "created_at": a.created_at, "action": a.action, "entity_type": a.entity_type,
                       "entity_id": a.entity_id, "actor": a.actor.email if a.actor else None, "details": a.details,
                       "ip_address": a.ip_address} for a in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/thresholds", response_model=list[ThresholdOut])
def list_thresholds(db: DB, _: Current) -> list[ThresholdOut]:
    model_thr = production_thresholds(db)
    return [_threshold_out(t, model_thr) for t in db.scalars(select(m.AlertThreshold).join(m.EquipmentType).order_by(m.EquipmentType.key))]


def _threshold_out(t: m.AlertThreshold, model_thr: dict[str, object]) -> ThresholdOut:
    return ThresholdOut(equipment_type=t.equipment_type.key, equipment_type_name=t.equipment_type.display_name,
                        risk_warning=t.risk_warning, risk_critical=t.risk_critical,
                        anomaly_alerts_enabled=t.anomaly_alerts_enabled, anomaly_score_override=t.anomaly_score_override,
                        cooldown_minutes=t.cooldown_minutes, model_threshold=model_thr.get(t.equipment_type.key),  # type: ignore[arg-type]
                        updated_at=t.updated_at)


@router.put("/thresholds/{equipment_type}", response_model=ThresholdOut)
def update_threshold(equipment_type: str, body: ThresholdUpdate, request: Request, db: DB, admin: AdminUser) -> ThresholdOut:
    if body.risk_warning >= body.risk_critical:
        raise ValidationFailed("risk_warning must be lower than risk_critical")
    t = db.scalar(select(m.AlertThreshold).join(m.EquipmentType).where(m.EquipmentType.key == equipment_type))
    if t is None:
        raise NotFound("Equipment type not found")
    before = {"risk_warning": t.risk_warning, "risk_critical": t.risk_critical, "cooldown_minutes": t.cooldown_minutes,
              "anomaly_alerts_enabled": t.anomaly_alerts_enabled, "anomaly_score_override": t.anomaly_score_override}
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    t.updated_by_id = admin.id
    audit.record(db, admin.id, "threshold.update", "alert_threshold", equipment_type,
                 {"before": before, "after": body.model_dump()}, client_ip(request))
    db.commit()
    db.refresh(t)
    return _threshold_out(t, production_thresholds(db))
