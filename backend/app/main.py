from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text

from . import __version__
from .api.v1 import admin, auth, dashboard, equipment, maintenance, predictions, reports, sensors
from .core.config import get_settings
from .core.errors import install_error_handlers
from .core.logging import RequestContextMiddleware, configure_logging
from .db.session import get_sessionmaker
from .models import entities as m
from .services.models_registry import model_cache

DESCRIPTION = """
Maintenix AI predictive-maintenance API.

* Authenticate with `POST /api/v1/auth/login`, then send `Authorization: Bearer <token>`.
* Predictions are **advisory**. Nothing in this API controls equipment.
* Demo equipment and readings are **simulated** and flagged with `data_source = "simulated"`.
"""


def _health() -> dict[str, Any]:
    status, db_ok, n_models = "ok", True, 0
    try:
        with get_sessionmaker()() as db:
            db.execute(text("SELECT 1"))
            n_models = db.scalar(select(func.count()).select_from(m.ModelVersion).where(m.ModelVersion.status == "production")) or 0
    except Exception:  # noqa: BLE001 - health must never raise
        status, db_ok = "degraded", False
    return {"status": status, "version": __version__, "database": "ok" if db_ok else "unavailable",
            "production_models": n_models, "models_loaded_in_memory": model_cache.loaded_count()}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Maintenix AI API", version=__version__, description=DESCRIPTION,
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID", "Content-Disposition"])
    install_error_handlers(app)

    @app.middleware("http")
    async def security_headers(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/health", tags=["health"])
    def health() -> dict[str, Any]:
        return _health()

    v1 = APIRouter(prefix="/api/v1")

    @v1.get("/health", tags=["health"])
    def health_v1() -> dict[str, Any]:
        return _health()

    for r in (auth.router, equipment.router, sensors.router, predictions.router, maintenance.router,
              dashboard.router, reports.router, admin.router):
        v1.include_router(r)
    app.include_router(v1)
    return app


app = create_app()
