"""Idempotent reference-data setup: equipment types, sensors, models, thresholds, first admin."""

from __future__ import annotations

import logging

from maintenix_ml.equipment_types import EQUIPMENT_TYPES
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security import hash_password, password_problems
from ..models import entities as m
from . import audit
from .models_registry import production_thresholds, sync_from_disk

log = logging.getLogger("maintenix.bootstrap")


def sync_equipment_types(db: Session) -> int:
    changed = 0
    for spec in EQUIPMENT_TYPES.values():
        et = db.scalar(select(m.EquipmentType).where(m.EquipmentType.key == spec.key))
        if et is None:
            et = m.EquipmentType(key=spec.key)
            db.add(et)
            changed += 1
        et.display_name, et.description = spec.display_name, spec.description
        et.rul_supported, et.data_note = spec.rul_supported, spec.data_note
        et.sampling_interval_seconds, et.failure_horizon_hours = spec.sampling_interval_seconds, spec.failure_horizon_hours
        db.flush()
        existing = {s.name: s for s in db.scalars(select(m.SensorDefinition).where(m.SensorDefinition.equipment_type_id == et.id))}
        for pos, s in enumerate(spec.sensors):
            sd = existing.get(s.name) or m.SensorDefinition(equipment_type_id=et.id, name=s.name)
            if s.name not in existing:
                db.add(sd)
            sd.unit, sd.description, sd.required, sd.position = s.unit, s.description, s.required, pos
            sd.valid_min, sd.valid_max, sd.normal_min, sd.normal_max = s.valid_min, s.valid_max, s.normal_min, s.normal_max
    db.commit()
    return changed


def ensure_thresholds(db: Session) -> None:
    model_thr = production_thresholds(db)
    for et in db.scalars(select(m.EquipmentType)):
        thr = model_thr.get(et.key)
        warning = round(min(max(float(thr), 0.05), 0.8), 2) if thr is not None else 0.3
        critical = round(min(max(0.7, warning + 0.15), 0.98), 2)
        existing = db.scalar(select(m.AlertThreshold).where(m.AlertThreshold.equipment_type_id == et.id))
        if existing is None:
            db.add(m.AlertThreshold(equipment_type_id=et.id, risk_warning=warning, risk_critical=critical,
                                    anomaly_alerts_enabled=True, cooldown_minutes=360))
        elif existing.updated_by_id is None and thr is not None and existing.risk_warning != warning:
            # still on defaults (never edited by an admin): follow the newly available model threshold
            existing.risk_warning, existing.risk_critical = warning, critical
    db.commit()


def ensure_admin(db: Session) -> None:
    s = get_settings()
    if not s.bootstrap_admin_email or not s.bootstrap_admin_password:
        return
    email = s.bootstrap_admin_email.lower()
    if db.scalar(select(m.User.id).where(m.User.email == email)):
        return
    if password_problems(s.bootstrap_admin_password):
        raise ValueError("BOOTSTRAP_ADMIN_PASSWORD does not meet the password policy")
    role = db.scalar(select(m.Role).where(m.Role.name == "admin"))
    user = m.User(email=email, full_name="Administrator", password_hash=hash_password(s.bootstrap_admin_password), role=role)
    db.add(user)
    db.flush()
    audit.record(db, None, "user.bootstrap_admin", "user", user.id, {"email": email})
    db.commit()
    log.info("Bootstrap admin created")


def bootstrap(db: Session) -> dict[str, object]:
    types = sync_equipment_types(db)
    models = sync_from_disk(db)
    ensure_thresholds(db)
    ensure_admin(db)
    return {"equipment_types_added": types, "models": models}
