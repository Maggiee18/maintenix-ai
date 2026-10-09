from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import Forbidden, Unauthorized
from ..core.security import decode_token
from ..db.session import get_db
from ..models import entities as m

_bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


class CurrentUser:
    def __init__(self, user: m.User, jti: str, exp: int) -> None:
        self.user = user
        self.jti = jti
        self.exp = exp

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def role(self) -> str:
        return self.user.role.name


def get_current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized("Not authenticated")
    try:
        payload = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token") from exc
    if db.get(m.RevokedToken, payload["jti"]) is not None:
        raise Unauthorized("Token revoked")
    user = db.execute(select(m.User).where(m.User.id == int(payload["sub"]))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise Unauthorized("User inactive or not found")
    return CurrentUser(user, payload["jti"], int(payload["exp"]))


Current = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    def checker(current: Current) -> CurrentUser:
        if current.role not in roles:
            raise Forbidden(f"Requires role: {', '.join(roles)}")
        return current

    return checker


AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]
EngineerUser = Annotated[CurrentUser, Depends(require_roles("admin", "engineer"))]
StaffUser = Annotated[CurrentUser, Depends(require_roles("admin", "engineer", "technician"))]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
