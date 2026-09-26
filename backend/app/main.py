"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app import __version__
from app.core.config import Settings, get_settings
from app.core.csrf import CsrfMiddleware
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import get_async_engine
from app.routers import auth, health, jobs, organizations
from app.schemas.errors import error_responses

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hooks."""
    settings: Settings = app.state.settings
    logger.info("startup", environment=settings.environment.value, version=__version__)
    yield
    await get_async_engine().dispose()
    logger.info("shutdown")


def operation_id(route: APIRoute) -> str:
    """Use the Python function name as the OpenAPI operationId (stable, readable client)."""
    return route.name


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
        generate_unique_id_function=operation_id,
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
    app.add_middleware(
        CsrfMiddleware,
        cookie_name=settings.session_cookie_name,
        allowed_origins=settings.allowed_origins,
    )
    # Added last = runs first, so the request id exists for everything else.
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    # Every endpoint can answer 422 / 500 in the standard error format.
    api = APIRouter(prefix=settings.api_prefix, responses=error_responses(422, 500))
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(organizations.router)
    api.include_router(jobs.router)
    app.include_router(api)

    return app


app = create_app()
