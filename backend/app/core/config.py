from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {"", "change-me", "changeme", "secret", "dev-secret-change-me"}


class Settings(BaseSettings):
    """Runtime configuration from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Maintenix AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = Field(..., description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host/db")
    db_pool_size: int = 10

    jwt_secret: str = Field(..., min_length=16)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expire_minutes: int = Field(60, ge=5, le=24 * 60)

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    models_dir: Path = Path("models")
    prediction_window: int = Field(60, ge=48, le=500)

    login_rate_limit: int = 10  # attempts
    login_rate_window_seconds: int = 300
    max_upload_bytes: int = 5 * 1024 * 1024
    max_batch_rows: int = 5000

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production":
            if self.jwt_secret.lower() in _INSECURE_SECRETS or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be a random value of at least 32 characters in production")
            if any(o == "*" for o in self.cors_origins):
                raise ValueError("Wildcard CORS origin is not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
