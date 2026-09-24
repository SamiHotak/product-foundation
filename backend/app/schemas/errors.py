"""The one error format every endpoint uses (see app/core/errors.py)."""

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    """What went wrong."""

    code: str
    message: str
    request_id: str | None
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Error envelope: `{"error": {...}}`."""

    error: ErrorBody


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` entries for the given status codes (typed error bodies)."""
    descriptions = {
        400: "Bad request",
        401: "Not signed in",
        403: "Not allowed",
        404: "Not found",
        409: "Conflict",
        422: "Some fields are invalid",
        429: "Too many requests",
        500: "Unexpected server error",
        503: "A dependency is not reachable",
    }
    return {
        code: {"model": ErrorResponse, "description": descriptions.get(code, "Error")}
        for code in codes
    }
