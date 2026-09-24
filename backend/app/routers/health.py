"""Health endpoints used by Docker, Caddy, the deploy script and uptime checks."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.schemas.health import LivenessResponse, ReadinessResponse
from app.services.health import HealthService, build_health_service

router = APIRouter(prefix="/health", tags=["health"])


def get_health_service(settings: Annotated[Settings, Depends(get_settings)]) -> HealthService:
    """Dependency that builds the health service (overridden in tests)."""
    return build_health_service(settings)


@router.get("", response_model=LivenessResponse, summary="Liveness")
async def liveness(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> LivenessResponse:
    """Return 200 while the process is running. Does not touch dependencies."""
    return service.liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is down"}},
)
async def readiness(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> ReadinessResponse:
    """Check Postgres and Redis. Returns 503 if any check fails."""
    report = await service.readiness()
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
