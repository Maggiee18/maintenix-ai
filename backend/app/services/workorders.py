"""Work-order lifecycle as an explicit state machine.

    open --assign--> assigned --start--> in_progress --complete--> completed
      |                 |  ^                   |
      |                 |  +--reassign         |
      |                 +--unassign--> open    |
      +----cancel-------+-------cancel---------+--> cancelled

``completed`` and ``cancelled`` are terminal. Every transition writes a
``work_order_events`` row and an audit event in the same transaction.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..api.deps import CurrentUser
from ..core.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from ..models import entities as m
from ..schemas.maintenance import CompletionRequest, WorkOrderCreate
from . import alerting, audit

TRANSITIONS: dict[str, set[str]] = {
    "open": {"assigned", "cancelled"},
    "assigned": {"assigned", "in_progress", "open", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
ASSIGNABLE_ROLES = ("technician", "engineer")


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


def _is_planner(user: CurrentUser) -> bool:
    return user.role in ("admin", "engineer")


def allowed_actions(wo: m.WorkOrder, user: CurrentUser) -> list[str]:
    planner = _is_planner(user)
    mine = wo.assigned_to_id == user.id
    acts = []
    if planner and can_transition(wo.status, "assigned"):
        acts.append("assign")
    if (planner or mine) and wo.status == "assigned":
        acts.append("start")
    if planner and wo.status == "assigned":
        acts.append("unassign")
    if (planner or mine) and wo.status == "in_progress":
        acts.append("complete")
    if planner and can_transition(wo.status, "cancelled"):
        acts.append("cancel")
    return acts


def _event(db: Session, wo: m.WorkOrder, src: str | None, dst: str, actor: CurrentUser, note: str | None, ip: str | None) -> None:
    wo.events.append(m.WorkOrderEvent(from_status=src, to_status=dst, actor_id=actor.id, note=note or None))
    audit.record(db, actor.id, f"work_order.{dst}" if src else "work_order.create", "work_order", wo.id,
                 {"code": wo.code, "from": src, "to": dst}, ip)


def _move(db: Session, wo: m.WorkOrder, dst: str, actor: CurrentUser, note: str | None, ip: str | None) -> None:
    src = wo.status
    if not can_transition(src, dst):
        raise InvalidTransition(f"Cannot move work order from '{src}' to '{dst}'",
                                {"from": src, "to": dst, "allowed": sorted(TRANSITIONS[src])})
    wo.status = dst
    _event(db, wo, src, dst, actor, note, ip)


def get(db: Session, wo_id: int, lock: bool = False) -> m.WorkOrder:
    q = select(m.WorkOrder).where(m.WorkOrder.id == wo_id)
    if lock:
        q = q.with_for_update(of=m.WorkOrder)
    wo = db.scalar(q)
    if wo is None:
        raise NotFound("Work order not found")
    return wo


def _assignee(db: Session, user_id: int) -> m.User:
    u = db.get(m.User, user_id)
    if u is None or not u.is_active:
        raise ValidationFailed("Assignee not found or inactive")
    if u.role.name not in ASSIGNABLE_ROLES:
        raise ValidationFailed(f"Work orders can only be assigned to: {', '.join(ASSIGNABLE_ROLES)}")
    return u


def create(db: Session, data: WorkOrderCreate, actor: CurrentUser, ip: str | None) -> m.WorkOrder:
    eq = db.get(m.Equipment, data.equipment_id)
    if eq is None:
        raise ValidationFailed("Equipment not found")
    if eq.status == "decommissioned":
        raise ValidationFailed("Cannot create work orders for decommissioned equipment")
    if data.due_date and data.due_date < date.today():
        raise ValidationFailed("Due date cannot be in the past")
    if data.alert_id is not None:
        alert = db.get(m.Alert, data.alert_id)
        if alert is None or alert.equipment_id != eq.id:
            raise ValidationFailed("Alert does not belong to this equipment")
    if data.prediction_id is not None:
        pred = db.get(m.PredictionResult, data.prediction_id)
        if pred is None or pred.equipment_id != eq.id:
            raise ValidationFailed("Prediction does not belong to this equipment")
    new_id = db.scalar(text("SELECT nextval('work_orders_id_seq')"))
    wo = m.WorkOrder(id=new_id, code=f"WO-{new_id:06d}", equipment_id=eq.id, alert_id=data.alert_id,
                     prediction_id=data.prediction_id, title=data.title, description=data.description,
                     priority=data.priority, due_date=data.due_date, created_by_id=actor.id, status="open")
    db.add(wo)
    db.flush()
    _event(db, wo, None, "open", actor, None, ip)
    linked = db.get(m.Alert, data.alert_id) if data.alert_id is not None else None
    if linked is not None:
        alerting.acknowledge(linked, actor.id)
    if data.assigned_to_id is not None:
        wo.assigned_to_id = _assignee(db, data.assigned_to_id).id
        _move(db, wo, "assigned", actor, None, ip)
    db.commit()
    return wo


def assign(db: Session, wo_id: int, assignee_id: int, actor: CurrentUser, note: str, ip: str | None) -> m.WorkOrder:
    if not _is_planner(actor):
        raise Forbidden("Only engineers and admins can assign work orders")
    wo = get(db, wo_id, lock=True)
    user = _assignee(db, assignee_id)
    if not can_transition(wo.status, "assigned"):
        raise InvalidTransition(f"Cannot assign a work order that is '{wo.status}'")
    wo.assigned_to_id = user.id
    _move(db, wo, "assigned", actor, note or f"Assigned to {user.full_name}", ip)
    db.commit()
    return wo


def transition(db: Session, wo_id: int, to_status: str, actor: CurrentUser, note: str, ip: str | None) -> m.WorkOrder:
    wo = get(db, wo_id, lock=True)
    planner, mine = _is_planner(actor), wo.assigned_to_id == actor.id
    now = datetime.now(UTC)
    if to_status == "in_progress":
        if not (planner or mine):
            raise Forbidden("Only the assignee or a planner can start this work order")
        _move(db, wo, "in_progress", actor, note, ip)
        wo.started_at = now
        if wo.equipment.status == "operational":
            wo.equipment.status = "under_maintenance"
    elif to_status == "open":
        if not planner:
            raise Forbidden("Only engineers and admins can unassign work orders")
        if wo.status != "assigned":
            raise InvalidTransition("Only assigned work orders can be returned to open")
        _move(db, wo, "open", actor, note or "Unassigned", ip)
        wo.assigned_to_id = None
    elif to_status == "cancelled":
        if not planner:
            raise Forbidden("Only engineers and admins can cancel work orders")
        if not note.strip():
            raise ValidationFailed("A cancellation reason is required")
        was_in_progress = wo.status == "in_progress"
        _move(db, wo, "cancelled", actor, note, ip)
        wo.cancelled_at, wo.cancel_reason = now, note
        if was_in_progress:
            _release_equipment(db, wo)
    else:
        raise InvalidTransition(f"Use the dedicated endpoint to move to '{to_status}'")
    db.commit()
    return wo


def complete(db: Session, wo_id: int, data: CompletionRequest, actor: CurrentUser, ip: str | None) -> m.WorkOrder:
    wo = get(db, wo_id, lock=True)
    if not (_is_planner(actor) or wo.assigned_to_id == actor.id):
        raise Forbidden("Only the assignee or a planner can complete this work order")
    completed_at = data.completed_at or datetime.now(UTC)
    if completed_at.tzinfo is None:
        raise ValidationFailed("completed_at must include a timezone")
    if completed_at > datetime.now(UTC):
        raise ValidationFailed("completed_at cannot be in the future")
    if wo.started_at and completed_at < wo.started_at:
        raise ValidationFailed("completed_at cannot be before the work started")
    _move(db, wo, "completed", actor, data.summary[:200], ip)
    wo.completed_at = completed_at
    wo.record = m.MaintenanceRecord(
        work_order_id=wo.id, equipment_id=wo.equipment_id, performed_by_id=wo.assigned_to_id or actor.id,
        completed_at=completed_at, action_taken=data.action_taken, summary=data.summary,
        parts_replaced=data.parts_replaced, downtime_hours=data.downtime_hours, restores_health=data.restores_health)
    eq = wo.equipment
    if data.restores_health:
        eq.last_maintenance_at = completed_at
    # close the evidence that triggered this work: the linked alert, and every active alert when health is restored
    alerts = []
    if wo.alert_id:
        alerts.append(db.get(m.Alert, wo.alert_id))
    if data.restores_health:
        alerts += db.scalars(select(m.Alert).where(m.Alert.equipment_id == eq.id, m.Alert.status.in_(("open", "acknowledged")))).all()
    for a in {a.id: a for a in alerts if a is not None}.values():
        alerting.resolve(a, f"Resolved by {wo.code}")
    _release_equipment(db, wo)
    db.commit()
    return wo


def _release_equipment(db: Session, wo: m.WorkOrder) -> None:
    eq = wo.equipment
    if eq.status != "under_maintenance":
        return
    db.flush()
    others = db.scalar(select(func.count()).select_from(m.WorkOrder).where(
        m.WorkOrder.equipment_id == eq.id, m.WorkOrder.status == "in_progress", m.WorkOrder.id != wo.id))
    if not others:
        eq.status = "operational"
