"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import get_async_engine
from app.routers import health

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hooks."""
    settings: Settings = app.state.settings
    logger.info("startup", environment=settings.environment.value, version=__version__)
    yield
    await get_async_engine().dispose()
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI app."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # API docs only outside production.
        docs_url=None if settings.is_production else f"{settings.api_prefix}/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else f"{settings.api_prefix}/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    # Added last = runs first, so the request id exists for everything else.
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(health.router)
    app.include_router(api)

    return app


app = create_app()
