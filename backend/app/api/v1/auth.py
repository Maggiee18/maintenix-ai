from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import delete, select

from ...core.config import get_settings
from ...core.errors import RateLimited, Unauthorized
from ...core.rate_limit import SlidingWindowLimiter
from ...core.security import create_access_token, hash_password, verify_password
from ...models import entities as m
from ...schemas.common import Message
from ...schemas.users import LoginRequest, TokenOut, UserOut
from ...services import audit
from ..deps import DB, Current, client_ip

router = APIRouter(prefix="/auth", tags=["auth"])
_s = get_settings()
login_limiter = SlidingWindowLimiter(_s.login_rate_limit, _s.login_rate_window_seconds)
# constant-time-ish path for unknown emails so response time does not reveal which emails exist
_DUMMY_HASH = hash_password("Dummy-password-0")


@router.post("/login", response_model=TokenOut, summary="Exchange email and password for a bearer token")
def login(body: LoginRequest, request: Request, db: DB) -> TokenOut:
    ip = client_ip(request)
    email = body.email.lower()
    if not login_limiter.hit(f"{ip}:{email}"):
        raise RateLimited("Too many login attempts. Try again later.")
    user = db.scalar(select(m.User).where(m.User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(db, user.id if user else None, "auth.login_failed", "user", user.id if user else None,
                     {"email": email, "reason": "inactive" if user and ok else "bad_credentials"}, ip)
        db.commit()
        raise Unauthorized("Invalid email or password")
    token, _, exp = create_access_token(user.id, user.role.name)
    user.last_login_at = datetime.now(UTC)
    audit.record(db, user.id, "auth.login", "user", user.id, {}, ip)
    db.commit()
    return TokenOut(access_token=token, expires_at=exp, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(current: Current) -> UserOut:
    return UserOut.model_validate(current.user)


@router.post("/logout", response_model=Message, status_code=status.HTTP_200_OK,
             summary="Revoke the current token (server-side denylist until it expires)")
def logout(current: Current, request: Request, db: DB) -> Message:
    now = datetime.now(UTC)
    db.execute(delete(m.RevokedToken).where(m.RevokedToken.expires_at < now))  # prune
    db.add(m.RevokedToken(jti=current.jti, user_id=current.id, expires_at=datetime.fromtimestamp(current.exp, UTC)))
    audit.record(db, current.id, "auth.logout", "user", current.id, {}, client_ip(request))
    db.commit()
    return Message(message="Logged out")
