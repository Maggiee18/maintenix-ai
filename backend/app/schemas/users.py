from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, EmailStr, Field, field_validator

from ..core.security import password_problems
from .common import ORMModel

RoleName = Literal["admin", "engineer", "technician", "viewer"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: RoleName = Field(validation_alias=AliasChoices("role_name", "role"))
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserBrief(ORMModel):
    id: int
    full_name: str
    role: RoleName = Field(validation_alias=AliasChoices("role_name", "role"))


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


def _check_password(v: str) -> str:
    problems = password_problems(v)
    if problems:
        raise ValueError("Password needs " + ", ".join(problems))
    return v


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    role: RoleName
    password: str = Field(max_length=72)

    _pw = field_validator("password")(_check_password)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    role: RoleName | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=72)
    _pw = field_validator("password")(_check_password)
