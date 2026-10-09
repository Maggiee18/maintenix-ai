"""Turn predictions into alerts without flooding the dashboard.

Deduplication rules (documented in docs/architecture.md and the interview guide):

1. At most one *active* (open or acknowledged) alert per equipment and kind.
   This is enforced by a partial unique index, not only by application code.
   A new breach while an alert is active updates that alert: ``last_seen_at``,
   ``occurrence_count`` and the linked prediction. Severity can only escalate;
   an escalation re-opens an acknowledged alert.
2. Cooldown: after an alert is resolved, a breach of the same kind and the same
   or lower severity within ``cooldown_minutes`` is suppressed. An escalation to
   a higher severity is never suppressed.
3. Alerts are never auto-resolved when risk drops: a person confirms resolution
   (usually by completing a work order).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import entities as m

_RANK = {"warning": 1, "critical": 2}


def _breaches(pred: m.PredictionResult, th: m.AlertThreshold) -> list[tuple[str, str, str, str]]:
    """List of (kind, severity, title, message) for this prediction."""
    out = []
    if pred.status == "ok" and pred.risk_level in ("elevated", "high"):
        sev = "critical" if pred.risk_level == "high" else "warning"
        out.append(("failure_risk", sev, f"{'High' if sev == 'critical' else 'Elevated'} failure risk",
                    f"Predicted probability of failure within the horizon is {pred.failure_probability:.0%} "
                    f"(warning {th.risk_warning:.0%}, critical {th.risk_critical:.0%})."))
    if pred.status == "ok" and pred.is_anomaly and th.anomaly_alerts_enabled:
        sensors = [d["sensor"] for d in (pred.sensor_deviations or []) if d.get("outside_limits")]
        detail = f" Sensors outside control limits: {', '.join(sensors)}." if sensors else ""
        out.append(("anomaly", "warning", "Abnormal sensor behaviour",
                    f"Anomaly score {pred.anomaly_score:.3f} above threshold {pred.anomaly_threshold:.3f}.{detail} "
                    "An anomaly is not a confirmed failure."))
    return out


def evaluate(db: Session, equipment: m.Equipment, pred: m.PredictionResult, th: m.AlertThreshold) -> list[m.Alert]:
    touched = []
    for kind, severity, title, message in _breaches(pred, th):
        alert = _upsert(db, equipment, pred, th, kind, severity, title, message)
        if alert is not None:
            touched.append(alert)
    return touched


def _upsert(db: Session, equipment: m.Equipment, pred: m.PredictionResult, th: m.AlertThreshold,
            kind: str, severity: str, title: str, message: str) -> m.Alert | None:
    active = db.scalar(select(m.Alert).where(m.Alert.equipment_id == equipment.id, m.Alert.kind == kind,
                                             m.Alert.status.in_(("open", "acknowledged"))).with_for_update(of=m.Alert))
    if active is not None:
        active.last_seen_at = max(active.last_seen_at, pred.as_of)
        active.occurrence_count += 1
        active.prediction_id = pred.id
        if _RANK[severity] > _RANK[active.severity]:
            active.severity, active.title, active.message = severity, title, message
            if active.status == "acknowledged":
                active.status, active.acknowledged_at, active.acknowledged_by_id = "open", None, None
        return active

    cutoff = datetime.now(UTC) - timedelta(minutes=th.cooldown_minutes)
    recent = db.scalar(select(m.Alert).where(m.Alert.equipment_id == equipment.id, m.Alert.kind == kind,
                                             m.Alert.status == "resolved", m.Alert.resolved_at >= cutoff)
                       .order_by(m.Alert.resolved_at.desc()).limit(1))
    if recent is not None and _RANK[severity] <= _RANK[recent.severity]:
        return None  # cooldown suppression

    alert = m.Alert(equipment_id=equipment.id, kind=kind, severity=severity, status="open", title=title,
                    message=message, prediction_id=pred.id, first_seen_at=pred.as_of, last_seen_at=pred.as_of)
    try:
        with db.begin_nested():
            db.add(alert)
    except IntegrityError:  # a concurrent request created it first; fall back to update
        return _upsert(db, equipment, pred, th, kind, severity, title, message)
    return alert


def acknowledge(alert: m.Alert, user_id: int) -> None:
    if alert.status == "open":
        alert.status, alert.acknowledged_at, alert.acknowledged_by_id = "acknowledged", datetime.now(UTC), user_id


def resolve(alert: m.Alert, note: str = "") -> None:
    if alert.status != "resolved":
        alert.status, alert.resolved_at, alert.resolution_note = "resolved", datetime.now(UTC), note or None
