from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import case, func, or_, select

from ...core.errors import Conflict
from ...models import entities as m
from ...schemas.common import Page
from ...schemas.maintenance import (
    AssignRequest,
    CompletionRequest,
    MaintenanceRecordOut,
    TransitionRequest,
    WorkOrderCreate,
    WorkOrderDetail,
    WorkOrderOut,
    WorkOrderUpdate,
)
from ...schemas.users import UserBrief
from ...services import audit, workorders
from ...services.presenters import record_out, work_order_out
from ..deps import DB, Current, EngineerUser, StaffUser, client_ip

router = APIRouter(tags=["maintenance"])


@router.get("/work-orders", response_model=Page[WorkOrderOut])
def list_work_orders(
    db: DB, user: Current, search: str | None = Query(None, max_length=100),
    status_: list[Literal["open", "assigned", "in_progress", "completed", "cancelled"]] | None = Query(None, alias="status"),
    priority: Literal["low", "medium", "high", "critical"] | None = None, equipment_id: int | None = None,
    assigned_to_me: bool = False, overdue: bool = False,
    sort: Literal["created", "due", "priority"] = "created",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
) -> Page[WorkOrderOut]:
    q = select(m.WorkOrder).join(m.Equipment, m.Equipment.id == m.WorkOrder.equipment_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(m.WorkOrder.code.ilike(like), m.WorkOrder.title.ilike(like), m.Equipment.code.ilike(like)))
    if status_:
        q = q.where(m.WorkOrder.status.in_(status_))
    if priority:
        q = q.where(m.WorkOrder.priority == priority)
    if equipment_id is not None:
        q = q.where(m.WorkOrder.equipment_id == equipment_id)
    if assigned_to_me:
        q = q.where(m.WorkOrder.assigned_to_id == user.id)
    if overdue:
        q = q.where(m.WorkOrder.due_date < date.today(), m.WorkOrder.status.in_(("open", "assigned", "in_progress")))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    prio = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=m.WorkOrder.priority)
    order: Any = {"created": m.WorkOrder.created_at.desc(), "due": m.WorkOrder.due_date.asc().nulls_last(), "priority": prio}[sort]
    rows = db.scalars(q.order_by(order, m.WorkOrder.id.desc()).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return Page(items=[work_order_out(w, user) for w in rows], total=total, page=page, page_size=page_size)


@router.post("/work-orders", response_model=WorkOrderDetail, status_code=status.HTTP_201_CREATED)
def create_work_order(body: WorkOrderCreate, request: Request, db: DB, user: EngineerUser) -> WorkOrderOut:
    return work_order_out(workorders.create(db, body, user, client_ip(request)), user, detail=True)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderDetail)
def get_work_order(wo_id: int, db: DB, user: Current) -> WorkOrderOut:
    return work_order_out(workorders.get(db, wo_id), user, detail=True)


@router.patch("/work-orders/{wo_id}", response_model=WorkOrderDetail)
def update_work_order(wo_id: int, body: WorkOrderUpdate, request: Request, db: DB, user: EngineerUser) -> WorkOrderOut:
    wo = workorders.get(db, wo_id, lock=True)
    if wo.status in ("completed", "cancelled"):
        raise Conflict("Closed work orders cannot be edited")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(wo, k, v)
    audit.record(db, user.id, "work_order.update", "work_order", wo.id, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return work_order_out(wo, user, detail=True)


@router.post("/work-orders/{wo_id}/assign", response_model=WorkOrderDetail)
def assign_work_order(wo_id: int, body: AssignRequest, request: Request, db: DB, user: EngineerUser) -> WorkOrderOut:
    return work_order_out(workorders.assign(db, wo_id, body.assignee_id, user, body.note, client_ip(request)), user, detail=True)


@router.post("/work-orders/{wo_id}/transition", response_model=WorkOrderDetail,
             summary="Start (in_progress), unassign (open) or cancel a work order")
def transition_work_order(wo_id: int, body: TransitionRequest, request: Request, db: DB, user: StaffUser) -> WorkOrderOut:
    return work_order_out(workorders.transition(db, wo_id, body.to_status, user, body.note, client_ip(request)), user, detail=True)


@router.post("/work-orders/{wo_id}/complete", response_model=WorkOrderDetail, summary="Record maintenance and complete")
def complete_work_order(wo_id: int, body: CompletionRequest, request: Request, db: DB, user: StaffUser) -> WorkOrderOut:
    return work_order_out(workorders.complete(db, wo_id, body, user, client_ip(request)), user, detail=True)


@router.get("/maintenance/records", response_model=Page[MaintenanceRecordOut])
def maintenance_history(db: DB, _: Current, equipment_id: int | None = None,
                        page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)) -> Page[MaintenanceRecordOut]:
    q = select(m.MaintenanceRecord)
    if equipment_id is not None:
        q = q.where(m.MaintenanceRecord.equipment_id == equipment_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.MaintenanceRecord.completed_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[record_out(r, r.work_order) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/users/assignable", response_model=list[UserBrief], summary="Active users who can receive work orders")
def assignable_users(db: DB, _: Current) -> list[UserBrief]:
    rows = db.scalars(select(m.User).join(m.Role).where(m.User.is_active.is_(True), m.Role.name.in_(workorders.ASSIGNABLE_ROLES))
                      .order_by(m.User.full_name)).all()
    return [UserBrief.model_validate(u) for u in rows]
