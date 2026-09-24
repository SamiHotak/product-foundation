"""Health check schemas."""

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "error"]


class LivenessResponse(BaseModel):
    """The process is up."""

    status: Literal["ok"] = "ok"
    version: str
    environment: str


class DependencyCheck(BaseModel):
    """Result of one dependency check."""

    name: str
    status: CheckStatus
    latency_ms: float | None = None
    error: str | None = Field(default=None, description="Short, safe error text.")


class ReadinessResponse(BaseModel):
    """Every dependency the API needs to serve traffic."""

    status: CheckStatus
    version: str
    environment: str
    checks: list[DependencyCheck]
