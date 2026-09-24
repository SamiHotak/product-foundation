"""One error format for the whole API.

Every error response looks like:
    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": ...}}

Raise `AppError` (or a subclass) from services; never build HTTP errors in business code.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    """The resource does not exist (or the caller may not see it)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current state."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class PermissionDeniedError(AppError):
    """The caller is authenticated but not allowed to do this."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class ServiceUnavailableError(AppError):
    """A dependency (database, cache, provider) is down."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def error_body(code: str, message: str, request: Request, details: Any = None) -> dict[str, Any]:
    """Build the standard error envelope."""
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }
    if details is not None:
        body["details"] = details
    return {"error": body}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle expected application errors."""
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, request, exc.details),
    )


_HTTP_CODES = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle Starlette HTTP errors (404 for unknown routes, 405, ...)."""
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(
            _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail), request
        ),
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle request validation errors with field-level details (the input is not echoed)."""
    assert isinstance(exc, RequestValidationError)
    details = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_body("validation_error", "Some fields are invalid.", request, details),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log the full error, return a generic message (never leak internals)."""
    logger.error(
        "unhandled_error",
        path=request.url.path,
        error_type=type(exc).__name__,
        exc_info=exc,
    )
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        # This handler runs outside the request middleware, so set the header here too.
        headers={"X-Request-ID": request_id} if request_id else None,
        content=error_body(
            "internal_error",
            "Something went wrong on our side. Try again, or contact support with the request id.",
            request,
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach all handlers to the app."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
