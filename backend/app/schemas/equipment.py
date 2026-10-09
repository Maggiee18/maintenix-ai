from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from .common import ORMModel

EquipmentStatus = Literal["operational", "under_maintenance", "offline", "decommissioned"]
Criticality = Literal["low", "medium", "high"]
HealthState = Literal["healthy", "watch", "at_risk", "critical", "unknown"]
OperatingMode = Literal["normal", "high_load", "idle"]


class SensorDefinitionOut(ORMModel):
    id: int
    name: str
    unit: str
    description: str
    valid_min: float
    valid_max: float
    normal_min: float
    normal_max: float
    required: bool


class EquipmentTypeOut(ORMModel):
    id: int
    key: str
    display_name: str
    description: str
    rul_supported: bool
    sampling_interval_seconds: int
    failure_horizon_hours: int
    data_note: str
    sensors: list[SensorDefinitionOut]


class EquipmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=2, max_length=120)
    equipment_type: str = Field(description="Equipment type key, e.g. centrifugal_pump")
    location: str = Field("", max_length=120)
    manufacturer: str = Field("", max_length=120)
    model_number: str = Field("", max_length=64)
    serial_number: str = Field("", max_length=64)
    install_date: date | None = None
    criticality: Criticality = "medium"

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class EquipmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    location: str | None = Field(None, max_length=120)
    manufacturer: str | None = Field(None, max_length=120)
    model_number: str | None = Field(None, max_length=64)
    serial_number: str | None = Field(None, max_length=64)
    install_date: date | None = None
    criticality: Criticality | None = None


class StatusChange(BaseModel):
    status: EquipmentStatus
    reason: str = Field("", max_length=500)


class LatestPredictionBrief(BaseModel):
    id: int
    as_of: datetime
    status: str
    failure_probability: float | None
    risk_level: str | None
    is_anomaly: bool | None
    rul_hours: float | None
    rul_status: str
    rul_unit: str = "h"


class EquipmentOut(BaseModel):
    id: int
    code: str
    name: str
    equipment_type: str
    equipment_type_name: str
    location: str
    manufacturer: str
    model_number: str
    serial_number: str
    install_date: date | None
    status: EquipmentStatus
    criticality: Criticality
    data_source: str
    health_state: HealthState
    last_maintenance_at: datetime | None
    latest_prediction: LatestPredictionBrief | None
    open_alerts: int = 0
    created_at: datetime
    updated_at: datetime


class SimulationInfo(BaseModel):
    """Present only for SIMULATED equipment; lets the demo stream simulator continue the trajectory."""

    seed: int
    first_reading_index: int


class EquipmentDetail(EquipmentOut):
    type_info: EquipmentTypeOut
    simulation: SimulationInfo | None = None
    latest_reading: dict[str, Any] | None
    reading_count: int


class HealthHistoryPoint(BaseModel):
    as_of: datetime
    failure_probability: float | None
    risk_level: str | None
    anomaly_score: float | None
    is_anomaly: bool | None
    rul_hours: float | None


class HealthHistoryOut(BaseModel):
    equipment_id: int
    points: list[HealthHistoryPoint]
    maintenance: list[dict[str, Any]]


class _AwareRange(BaseModel):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
