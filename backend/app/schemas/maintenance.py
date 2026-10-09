from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .users import UserBrief

Priority = Literal["low", "medium", "high", "critical"]
WOStatus = Literal["open", "assigned", "in_progress", "completed", "cancelled"]
Action = Literal["inspection", "repair", "replacement", "adjustment", "lubrication", "calibration", "other"]


class WorkOrderCreate(BaseModel):
    equipment_id: int
    title: str = Field(min_length=3, max_length=200)
    description: str = Field("", max_length=5000)
    priority: Priority = "medium"
    due_date: date | None = None
    alert_id: int | None = None
    prediction_id: int | None = None
    assigned_to_id: int | None = None


class WorkOrderUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=5000)
    priority: Priority | None = None
    due_date: date | None = None


class AssignRequest(BaseModel):
    assignee_id: int
    note: str = Field("", max_length=1000)


class TransitionRequest(BaseModel):
    to_status: Literal["open", "in_progress", "cancelled"]
    note: str = Field("", max_length=1000)


class CompletionRequest(BaseModel):
    action_taken: Action
    summary: str = Field(min_length=5, max_length=5000)
    parts_replaced: str = Field("", max_length=1000)
    downtime_hours: float = Field(0, ge=0, le=10000)
    restores_health: bool = False
    completed_at: datetime | None = None


class WorkOrderEventOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    actor: str | None
    note: str | None
    created_at: datetime


class MaintenanceRecordOut(BaseModel):
    id: int
    work_order_id: int
    work_order_code: str
    equipment_id: int
    equipment_code: str
    performed_by: str | None
    completed_at: datetime
    action_taken: str
    summary: str
    parts_replaced: str
    downtime_hours: float
    restores_health: bool


class WorkOrderOut(BaseModel):
    id: int
    code: str
    equipment_id: int
    equipment_code: str
    equipment_name: str
    alert_id: int | None
    prediction_id: int | None
    title: str
    description: str
    priority: Priority
    status: WOStatus
    assigned_to: UserBrief | None
    created_by: UserBrief | None
    due_date: date | None
    overdue: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    allowed_transitions: list[str]


class WorkOrderDetail(WorkOrderOut):
    events: list[WorkOrderEventOut]
    record: MaintenanceRecordOut | None
