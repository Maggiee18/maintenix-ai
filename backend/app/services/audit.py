from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import entities as m

_SENSITIVE = {"password", "password_hash", "token", "access_token"}


def record(
    db: Session, actor_id: int | None, action: str, entity_type: str, entity_id: object = None,
    details: dict[str, Any] | None = None, ip: str | None = None,
) -> None:
    """Add an audit event to the current transaction (committed with the change it describes)."""
    safe = {k: v for k, v in (details or {}).items() if k.lower() not in _SENSITIVE}
    db.add(m.AuditEvent(actor_id=actor_id, action=action, entity_type=entity_type,
                        entity_id=None if entity_id is None else str(entity_id), details=safe, ip_address=ip))
