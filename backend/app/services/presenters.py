"""ORM -> response schema mapping, so routers never return ORM objects directly."""

from __future__ import annotations

from datetime import date

from ..api.deps import CurrentUser
from ..models import entities as m
from ..schemas.equipment import EquipmentOut, LatestPredictionBrief
from ..schemas.maintenance import MaintenanceRecordOut, WorkOrderDetail, WorkOrderEventOut, WorkOrderOut
from ..schemas.predictions import AlertOut, ModelVersionDetail, ModelVersionOut, PredictionDetail, PredictionOut
from ..schemas.users import UserBrief
from . import workorders
from .inference import health_state, recommendation


def equipment_out(e: m.Equipment, open_alerts: int = 0) -> EquipmentOut:
    p = e.latest_prediction
    return EquipmentOut(
        id=e.id, code=e.code, name=e.name, equipment_type=e.equipment_type.key,
        equipment_type_name=e.equipment_type.display_name, location=e.location, manufacturer=e.manufacturer,
        model_number=e.model_number, serial_number=e.serial_number, install_date=e.install_date, status=e.status,  # type: ignore[arg-type]
        criticality=e.criticality, data_source=e.data_source, health_state=health_state(p),  # type: ignore[arg-type]
        last_maintenance_at=e.last_maintenance_at, open_alerts=open_alerts, created_at=e.created_at, updated_at=e.updated_at,
        latest_prediction=LatestPredictionBrief(
            id=p.id, as_of=p.as_of, status=p.status, failure_probability=p.failure_probability, risk_level=p.risk_level,
            is_anomaly=p.is_anomaly, rul_hours=p.rul_hours, rul_status=p.rul_status) if p else None,
    )


def prediction_out(p: m.PredictionResult, code: str | None = None, detail: bool = False) -> PredictionOut:
    cls = PredictionDetail if detail else PredictionOut
    obj = cls.model_validate(p, from_attributes=True)
    obj.equipment_code = code
    obj.recommendation = recommendation(p)
    return obj


def model_out(mv: m.ModelVersion, detail: bool = False) -> ModelVersionOut:
    base = dict(id=mv.id, equipment_type=mv.equipment_type.key, task=mv.task, name=mv.name, version=mv.version,
                algorithm=mv.algorithm, dataset_id=mv.dataset_id, feature_version=mv.feature_version,
                feature_count=len(mv.feature_names), status=mv.status, trained_at=mv.trained_at,
                registered_at=mv.registered_at, promoted_at=mv.promoted_at)
    if not detail:
        return ModelVersionOut(**base)
    return ModelVersionDetail(**base, feature_names=mv.feature_names, params=mv.params, metrics=mv.metrics,
                              dataset_info=mv.dataset_info, artifact_sha256=mv.artifact_sha256)


def alert_out(a: m.Alert, work_order_id: int | None = None) -> AlertOut:
    return AlertOut(id=a.id, equipment_id=a.equipment_id, equipment_code=a.equipment.code, equipment_name=a.equipment.name,
                    kind=a.kind, severity=a.severity, status=a.status, title=a.title, message=a.message,
                    prediction_id=a.prediction_id, first_seen_at=a.first_seen_at, last_seen_at=a.last_seen_at,
                    occurrence_count=a.occurrence_count, acknowledged_at=a.acknowledged_at, resolved_at=a.resolved_at,
                    work_order_id=work_order_id)


def _brief(u: m.User | None) -> UserBrief | None:
    return UserBrief(id=u.id, full_name=u.full_name, role=u.role.name) if u else None  # type: ignore[arg-type]


def record_out(r: m.MaintenanceRecord, wo: m.WorkOrder) -> MaintenanceRecordOut:
    return MaintenanceRecordOut(id=r.id, work_order_id=wo.id, work_order_code=wo.code, equipment_id=r.equipment_id,
                                equipment_code=wo.equipment.code, performed_by=r.performed_by.full_name if r.performed_by else None,
                                completed_at=r.completed_at, action_taken=r.action_taken, summary=r.summary,
                                parts_replaced=r.parts_replaced, downtime_hours=float(r.downtime_hours),
                                restores_health=r.restores_health)


def work_order_out(wo: m.WorkOrder, user: CurrentUser, detail: bool = False) -> WorkOrderOut:
    base = dict(
        id=wo.id, code=wo.code, equipment_id=wo.equipment_id, equipment_code=wo.equipment.code,
        equipment_name=wo.equipment.name, alert_id=wo.alert_id, prediction_id=wo.prediction_id, title=wo.title,
        description=wo.description, priority=wo.priority, status=wo.status, assigned_to=_brief(wo.assigned_to),
        created_by=_brief(wo.created_by), due_date=wo.due_date,
        overdue=bool(wo.due_date and wo.due_date < date.today() and wo.status not in ("completed", "cancelled")),
        created_at=wo.created_at, updated_at=wo.updated_at, started_at=wo.started_at, completed_at=wo.completed_at,
        cancelled_at=wo.cancelled_at, cancel_reason=wo.cancel_reason, allowed_transitions=workorders.allowed_actions(wo, user),
    )
    if not detail:
        return WorkOrderOut(**base)
    events = [WorkOrderEventOut(id=e.id, from_status=e.from_status, to_status=e.to_status,
                                actor=e.actor.full_name if e.actor else None, note=e.note, created_at=e.created_at)
              for e in wo.events]
    return WorkOrderDetail(**base, events=events, record=record_out(wo.record, wo) if wo.record else None)
