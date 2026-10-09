"""SQLAlchemy ORM entities. See docs/database-design.md for the ER diagram."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, in_check

# ---------------------------------------------------------------------------- enums
EQUIPMENT_STATUSES = ("operational", "under_maintenance", "offline", "decommissioned")
CRITICALITIES = ("low", "medium", "high")
DATA_SOURCES = ("simulated", "imported", "api")
OPERATING_MODES = ("normal", "high_load", "idle")
RISK_LEVELS = ("low", "elevated", "high")
RUL_STATUSES = ("ok", "unavailable", "no_model", "insufficient_data")
PREDICTION_STATUSES = ("ok", "insufficient_data", "no_model")
MODEL_TASKS = ("failure", "anomaly", "rul")
MODEL_STATUSES = ("staging", "production", "archived")
ALERT_KINDS = ("failure_risk", "anomaly")
ALERT_SEVERITIES = ("warning", "critical")
ALERT_STATUSES = ("open", "acknowledged", "resolved")
WO_PRIORITIES = ("low", "medium", "high", "critical")
WO_STATUSES = ("open", "assigned", "in_progress", "completed", "cancelled")
MAINTENANCE_ACTIONS = ("inspection", "repair", "replacement", "adjustment", "lubrication", "calibration", "other")


# ---------------------------------------------------------------------------- auth
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role: Mapped[Role] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    @property
    def role_name(self) -> str:
        return self.role.name


class RevokedToken(Base):
    """Denylist of logged-out JWT ids, kept until the token would have expired anyway."""

    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------- catalog
class EquipmentType(Base):
    __tablename__ = "equipment_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rul_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sampling_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    data_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sensors: Mapped[list[SensorDefinition]] = relationship(
        back_populates="equipment_type", order_by="SensorDefinition.position", lazy="selectin"
    )


class SensorDefinition(Base):
    __tablename__ = "sensor_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_types.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    valid_min: Mapped[float] = mapped_column(Float, nullable=False)
    valid_max: Mapped[float] = mapped_column(Float, nullable=False)
    normal_min: Mapped[float] = mapped_column(Float, nullable=False)
    normal_max: Mapped[float] = mapped_column(Float, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equipment_type: Mapped[EquipmentType] = relationship(back_populates="sensors")

    __table_args__ = (
        UniqueConstraint("equipment_type_id", "name", name="uq_sensor_definitions_type_name"),
        CheckConstraint("valid_min < valid_max", name="valid_range"),
    )


class AlertThreshold(Base):
    __tablename__ = "alert_thresholds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_types.id", ondelete="CASCADE"), unique=True, nullable=False)
    risk_warning: Mapped[float] = mapped_column(Float, nullable=False)
    risk_critical: Mapped[float] = mapped_column(Float, nullable=False)
    anomaly_alerts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    anomaly_score_override: Mapped[float | None] = mapped_column(Float)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("risk_warning > 0 AND risk_warning < risk_critical AND risk_critical <= 1", name="risk_order"),
        CheckConstraint("cooldown_minutes BETWEEN 0 AND 10080", name="cooldown_range"),
    )


# ---------------------------------------------------------------------------- equipment
class Equipment(TimestampMixin, Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    manufacturer: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    model_number: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    serial_number: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    install_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="operational", index=True)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    data_source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    # Only used by the demo stream simulator to continue a SIMULATED trajectory:
    # simulation_offset is the trajectory index of the first stored reading.
    simulation_seed: Mapped[int | None] = mapped_column(BigInteger)
    simulation_offset: Mapped[int | None] = mapped_column(Integer)
    last_maintenance_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_prediction_id: Mapped[int | None] = mapped_column(
        ForeignKey("prediction_results.id", ondelete="SET NULL", use_alter=True, name="fk_equipment_latest_prediction")
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")
    latest_prediction: Mapped[PredictionResult | None] = relationship(foreign_keys=[latest_prediction_id], lazy="joined", post_update=True)

    __table_args__ = (
        CheckConstraint(in_check("status", EQUIPMENT_STATUSES), name="status"),
        CheckConstraint(in_check("criticality", CRITICALITIES), name="criticality"),
        CheckConstraint(in_check("data_source", DATA_SOURCES), name="data_source"),
    )


# ---------------------------------------------------------------------------- telemetry
class SensorReading(Base):
    """One timestamped observation of a piece of equipment (values in sensor_values)."""

    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    operating_hours: Mapped[float | None] = mapped_column(Numeric(12, 2))
    operating_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    data_source: Mapped[str] = mapped_column(String(16), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    values: Mapped[list[SensorValue]] = relationship(back_populates="reading", lazy="selectin", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("equipment_id", "recorded_at", name="uq_sensor_readings_equipment_time"),
        Index("ix_sensor_readings_equipment_time_desc", "equipment_id", text("recorded_at DESC")),
        CheckConstraint(in_check("operating_mode", OPERATING_MODES), name="operating_mode"),
        CheckConstraint(in_check("data_source", DATA_SOURCES), name="data_source"),
        CheckConstraint("operating_hours IS NULL OR operating_hours >= 0", name="operating_hours"),
    )


class SensorValue(Base):
    __tablename__ = "sensor_values"
    reading_id: Mapped[int] = mapped_column(ForeignKey("sensor_readings.id", ondelete="CASCADE"), primary_key=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensor_definitions.id", ondelete="RESTRICT"), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    reading: Mapped[SensorReading] = relationship(back_populates="values")
    sensor: Mapped[SensorDefinition] = relationship(lazy="joined")


# ---------------------------------------------------------------------------- ML
class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_type_id: Mapped[int] = mapped_column(ForeignKey("equipment_types.id", ondelete="RESTRICT"), nullable=False)
    task: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dataset_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="staging")
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    equipment_type: Mapped[EquipmentType] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("equipment_type_id", "task", "version", name="uq_model_versions_type_task_version"),
        CheckConstraint(in_check("task", MODEL_TASKS), name="task"),
        CheckConstraint(in_check("status", MODEL_STATUSES), name="status"),
        # at most one production model per (type, task)
        Index("uq_model_versions_one_production", "equipment_type_id", "task", unique=True,
              postgresql_where=text("status = 'production'")),
    )


class PredictionResult(Base):
    __tablename__ = "prediction_results"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # timestamp of latest reading used
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    readings_used: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_probability: Mapped[float | None] = mapped_column(Float)
    failure_threshold: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    anomaly_threshold: Mapped[float | None] = mapped_column(Float)
    is_anomaly: Mapped[bool | None] = mapped_column(Boolean)
    rul_hours: Mapped[float | None] = mapped_column(Float)
    rul_cap_hours: Mapped[float | None] = mapped_column(Float)
    rul_typical_error_hours: Mapped[float | None] = mapped_column(Float)
    rul_status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))
    anomaly_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))
    rul_model_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))
    # bounded: top-8 features, per-sensor sums, deviations for each sensor of the type
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sensor_deviations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")

    __table_args__ = (
        Index("ix_prediction_results_equipment_asof", "equipment_id", text("as_of DESC")),
        Index("ix_prediction_results_created_at", "created_at"),
        CheckConstraint(in_check("status", PREDICTION_STATUSES), name="status"),
        CheckConstraint(in_check("rul_status", RUL_STATUSES), name="rul_status"),
        CheckConstraint("risk_level IS NULL OR " + in_check("risk_level", RISK_LEVELS), name="risk_level"),
        CheckConstraint("failure_probability IS NULL OR (failure_probability >= 0 AND failure_probability <= 1)", name="prob_range"),
    )


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("prediction_results.id", ondelete="CASCADE"), nullable=False, unique=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    sensors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    equipment: Mapped[Equipment] = relationship(lazy="joined")

    __table_args__ = (Index("ix_anomaly_events_equipment_time", "equipment_id", text("detected_at DESC")),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_results.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[Equipment] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(in_check("kind", ALERT_KINDS), name="kind"),
        CheckConstraint(in_check("severity", ALERT_SEVERITIES), name="severity"),
        CheckConstraint(in_check("status", ALERT_STATUSES), name="status"),
        # deduplication guarantee: one active alert per equipment and kind
        Index("uq_alerts_one_active", "equipment_id", "kind", unique=True,
              postgresql_where=text("status IN ('open', 'acknowledged')")),
        Index("ix_alerts_status_last_seen", "status", text("last_seen_at DESC")),
    )


# ---------------------------------------------------------------------------- maintenance
class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False, index=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("prediction_results.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    equipment: Mapped[Equipment] = relationship(lazy="joined")
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id], lazy="joined")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="joined")
    events: Mapped[list[WorkOrderEvent]] = relationship(back_populates="work_order", order_by="WorkOrderEvent.id", lazy="selectin")
    record: Mapped[MaintenanceRecord | None] = relationship(back_populates="work_order", lazy="selectin", uselist=False)

    __table_args__ = (
        CheckConstraint(in_check("priority", WO_PRIORITIES), name="priority"),
        CheckConstraint(in_check("status", WO_STATUSES), name="status"),
        CheckConstraint("status <> 'completed' OR completed_at IS NOT NULL", name="completed_has_time"),
        CheckConstraint("status NOT IN ('assigned', 'in_progress') OR assigned_to_id IS NOT NULL", name="assigned_has_user"),
    )


class WorkOrderEvent(Base):
    __tablename__ = "work_order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    work_order: Mapped[WorkOrder] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship(lazy="joined")


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), unique=True, nullable=False)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    performed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action_taken: Mapped[str] = mapped_column(String(24), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    parts_replaced: Mapped[str] = mapped_column(Text, nullable=False, default="")
    downtime_hours: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    restores_health: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    work_order: Mapped[WorkOrder] = relationship(back_populates="record")
    performed_by: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(in_check("action_taken", MAINTENANCE_ACTIONS), name="action_taken"),
        CheckConstraint("downtime_hours >= 0", name="downtime_nonnegative"),
        Index("ix_maintenance_records_equipment_time", "equipment_id", text("completed_at DESC")),
    )


# ---------------------------------------------------------------------------- audit
class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    actor: Mapped[User | None] = relationship(lazy="joined")
