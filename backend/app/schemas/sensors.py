from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from .equipment import OperatingMode


class ReadingIn(BaseModel):
    """One observation. Sensor names must match the equipment type's sensor definitions."""

    recorded_at: AwareDatetime
    operating_hours: float | None = Field(None, ge=0)
    operating_mode: OperatingMode = "normal"
    values: dict[str, float] = Field(min_length=1, max_length=64)


class SingleIngest(ReadingIn):
    equipment_id: int
    run_inference: bool = True


class BatchIngest(BaseModel):
    equipment_id: int
    readings: list[ReadingIn] = Field(min_length=1)
    run_inference: bool = True
    data_source: Literal["api", "imported", "simulated"] = "api"


class IngestIssue(BaseModel):
    row: int | None
    column: str | None
    code: str
    message: str


class IngestReport(BaseModel):
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    already_stored: int = 0
    sampling: dict[str, Any] = {}
    errors: list[IngestIssue] = []
    warnings: list[IngestIssue] = []
    truncated: bool = False
    equipment_ids: list[int] = []
    predictions: list[dict[str, Any]] = []


class ReadingOut(BaseModel):
    id: int
    equipment_id: int
    recorded_at: datetime
    operating_hours: float | None
    operating_mode: str
    data_source: str
    values: dict[str, float]


class SeriesPoint(BaseModel):
    t: datetime
    values: dict[str, float | None]


class SeriesOut(BaseModel):
    equipment_id: int
    bucket: str
    sensors: list[str]
    points: list[SeriesPoint]
