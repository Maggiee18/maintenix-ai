from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from .config import get_settings

ROLES = ("admin", "engineer", "technician", "viewer")
_MIN_PASSWORD = 10


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; reject longer to avoid silent truncation
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode())
    except ValueError:
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < _MIN_PASSWORD:
        problems.append(f"at least {_MIN_PASSWORD} characters")
    if password.lower() == password or password.upper() == password:
        problems.append("mixed upper and lower case")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")
    if len(password.encode()) > 72:
        problems.append("at most 72 bytes")
    return problems


def create_access_token(user_id: int, role: str) -> tuple[str, str, datetime]:
    s = get_settings()
    jti = uuid.uuid4().hex
    exp = datetime.now(UTC) + timedelta(minutes=s.jwt_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "jti": jti, "exp": exp, "iat": datetime.now(UTC), "typ": "access"}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), jti, exp


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "jti"]})
