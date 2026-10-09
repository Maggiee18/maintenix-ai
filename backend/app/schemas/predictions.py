from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import ORMModel


class PredictionOut(ORMModel):
    id: int
    equipment_id: int
    equipment_code: str | None = None
    as_of: datetime
    created_at: datetime
    status: str
    readings_used: int
    failure_probability: float | None
    failure_threshold: float | None
    risk_level: str | None
    anomaly_score: float | None
    anomaly_threshold: float | None
    is_anomaly: bool | None
    rul_hours: float | None
    rul_cap_hours: float | None
    rul_typical_error_hours: float | None
    rul_status: str
    failure_model_id: int | None
    anomaly_model_id: int | None
    rul_model_id: int | None
    triggered_by: str
    recommendation: str | None = None


class PredictionDetail(PredictionOut):
    explanation: dict[str, Any] | None
    sensor_deviations: list[dict[str, Any]] | None


class AnomalyEventOut(BaseModel):
    id: int
    equipment_id: int
    equipment_code: str
    prediction_id: int
    detected_at: datetime
    score: float
    threshold: float
    sensors: list[dict[str, Any]]


class FleetRunResult(BaseModel):
    equipment_evaluated: int
    predictions_created: int
    insufficient_data: int
    alerts_raised_or_updated: int


class ModelVersionOut(ORMModel):
    id: int
    equipment_type: str
    task: str
    name: str
    version: str
    algorithm: str
    dataset_id: str
    feature_version: str
    feature_count: int
    status: str
    trained_at: datetime
    registered_at: datetime
    promoted_at: datetime | None


class ModelVersionDetail(ModelVersionOut):
    feature_names: list[str]
    params: dict[str, Any]
    metrics: dict[str, Any]
    dataset_info: dict[str, Any]
    artifact_sha256: str


class AlertOut(BaseModel):
    id: int
    equipment_id: int
    equipment_code: str
    equipment_name: str
    kind: str
    severity: str
    status: str
    title: str
    message: str
    prediction_id: int | None
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    work_order_id: int | None = None


class AlertAction(BaseModel):
    note: str = Field("", max_length=1000)


class ThresholdOut(BaseModel):
    equipment_type: str
    equipment_type_name: str
    risk_warning: float
    risk_critical: float
    anomaly_alerts_enabled: bool
    anomaly_score_override: float | None
    cooldown_minutes: int
    model_threshold: float | None
    updated_at: datetime | None


class ThresholdUpdate(BaseModel):
    risk_warning: float = Field(gt=0, lt=1)
    risk_critical: float = Field(gt=0, le=1)
    anomaly_alerts_enabled: bool = True
    anomaly_score_override: float | None = Field(None, gt=0, lt=2)
    cooldown_minutes: int = Field(360, ge=0, le=10080)


RiskLevel = Literal["low", "elevated", "high"]
