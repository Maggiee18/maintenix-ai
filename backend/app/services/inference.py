"""Run the production models on an equipment's latest window and persist the result."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from maintenix_ml.equipment_types import get_spec
from maintenix_ml.inference import predict_window
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import entities as m
from . import alerting, telemetry
from .models_registry import model_cache

log = logging.getLogger("maintenix.inference")


def risk_level(p: float | None, th: m.AlertThreshold | None) -> str | None:
    if p is None:
        return None
    warning, critical = (th.risk_warning, th.risk_critical) if th else (0.3, 0.7)
    return "high" if p >= critical else "elevated" if p >= warning else "low"


def health_state(pred: m.PredictionResult | None) -> str:
    if pred is None or pred.status != "ok":
        return "unknown"
    if pred.risk_level == "high":
        return "critical"
    if pred.risk_level == "elevated":
        return "at_risk"
    if pred.is_anomaly:
        return "watch"
    return "healthy"


def recommendation(pred: m.PredictionResult) -> str | None:
    """Advisory text for operators. Never an instruction to a machine."""
    if pred.status != "ok":
        return "Not enough recent readings to assess this equipment. Check data collection."
    drivers = []
    if pred.explanation:
        drivers = [s["sensor"] for s in pred.explanation.get("sensor_contributions", [])
                   if s["contribution"] > 0 and s["sensor"] != "operating_mode"][:2]
    drv = f" Main contributing signals: {', '.join(drivers)}." if drivers else ""
    rul = ""
    if pred.rul_status == "ok" and pred.rul_hours is not None and pred.rul_typical_error_hours:
        at_cap = bool(pred.rul_cap_hours and pred.rul_hours >= pred.rul_cap_hours - 0.5)
        rul = (f" Estimated remaining useful life about {pred.rul_hours:.0f} h{' or more' if at_cap else ''}"
               f" (typical error ±{pred.rul_typical_error_hours:.0f} h).")
    if pred.risk_level == "high":
        return f"High failure risk. Plan an inspection as soon as safely possible and consider a work order.{drv}{rul}"
    if pred.risk_level == "elevated":
        return f"Elevated failure risk. Schedule an inspection at the next planned stop.{drv}{rul}"
    if pred.is_anomaly:
        dev = [d["sensor"] for d in (pred.sensor_deviations or []) if d.get("outside_limits")][:2]
        where = f" Check {', '.join(dev)}." if dev else ""
        return f"Unusual behaviour detected but failure risk is low. Verify sensor health and recent operating changes.{where}"
    return f"No action needed. Continue routine monitoring.{rul}"


def thresholds_for(db: Session, equipment_type_id: int) -> m.AlertThreshold | None:
    return db.scalar(select(m.AlertThreshold).where(m.AlertThreshold.equipment_type_id == equipment_type_id))


def run_for_equipment(
    db: Session, equipment: m.Equipment, *, as_of: datetime | None = None, triggered_by: str = "manual",
    raise_alerts: bool = True, commit: bool = True, stats: dict[str, int] | None = None,
) -> m.PredictionResult | None:
    """Returns None when the equipment has no readings at all."""
    window = telemetry.load_window(db, equipment, get_settings().prediction_window, as_of)
    if window.empty:
        return None
    spec = get_spec(equipment.equipment_type.key)
    models = model_cache.production(db, equipment.equipment_type_id)
    th = thresholds_for(db, equipment.equipment_type_id)

    def loaded(task: str) -> Any:
        entry = models[task]
        return entry[1] if entry else None

    def mv_id(task: str) -> int | None:
        entry = models[task]
        return entry[0].id if entry else None

    result = predict_window(window, spec, loaded("failure"), loaded("anomaly"), loaded("rul"),
                            anomaly_threshold_override=th.anomaly_score_override if th else None)
    status = result.status
    if status == "ok" and models["failure"] is None and models["anomaly"] is None:
        status = "no_model"
    pred = m.PredictionResult(
        equipment_id=equipment.id, as_of=window["timestamp"].iloc[-1].to_pydatetime(), status=status,
        readings_used=result.readings_used, failure_probability=result.failure_probability,
        failure_threshold=th.risk_warning if th and result.failure_probability is not None else None,
        risk_level=risk_level(result.failure_probability, th), anomaly_score=result.anomaly_score,
        anomaly_threshold=result.anomaly_threshold, is_anomaly=result.is_anomaly, rul_hours=result.rul_hours,
        rul_cap_hours=result.rul_cap_hours, rul_typical_error_hours=result.rul_typical_error_hours,
        rul_status=result.rul_status, failure_model_id=mv_id("failure"), anomaly_model_id=mv_id("anomaly"),
        rul_model_id=mv_id("rul"), explanation=result.explanation, sensor_deviations=result.sensor_deviations,
        triggered_by=triggered_by,
    )
    db.add(pred)
    db.flush()
    already = pred.is_anomaly and db.scalar(select(m.AnomalyEvent.id).where(
        m.AnomalyEvent.equipment_id == equipment.id, m.AnomalyEvent.detected_at == pred.as_of))
    if pred.is_anomaly and not already:  # re-running on the same window does not duplicate the event
        db.add(m.AnomalyEvent(equipment_id=equipment.id, prediction_id=pred.id, detected_at=pred.as_of,
                              score=pred.anomaly_score or 0.0, threshold=pred.anomaly_threshold or 0.0,
                              sensors=[d for d in (result.sensor_deviations or [])][:8]))
    current = equipment.latest_prediction
    if current is None or current.as_of <= pred.as_of:
        equipment.latest_prediction_id = pred.id
    if raise_alerts and th is not None:
        touched = alerting.evaluate(db, equipment, pred, th)
        if stats is not None:
            stats["alerts_raised_or_updated"] = stats.get("alerts_raised_or_updated", 0) + len(touched)
    if commit:
        db.commit()
    return pred


def run_fleet(db: Session, triggered_by: str = "manual") -> dict[str, int]:
    stats = {"equipment_evaluated": 0, "predictions_created": 0, "insufficient_data": 0, "alerts_raised_or_updated": 0}
    for eq in db.scalars(select(m.Equipment).where(m.Equipment.status != "decommissioned")).all():
        stats["equipment_evaluated"] += 1
        pred = run_for_equipment(db, eq, triggered_by=triggered_by, stats=stats)
        if pred is None:
            continue
        stats["predictions_created"] += 1
        stats["insufficient_data"] += pred.status == "insufficient_data"
    return stats
