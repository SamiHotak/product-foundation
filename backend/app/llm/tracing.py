"""LLM traces for Langfuse (costs, tokens, timing, and, if allowed, prompts and answers).

Langfuse takes traces over OpenTelemetry (OTLP/HTTP JSON) at
`<LANGFUSE_HOST>/api/public/otel/v1/traces` (its old /ingestion API is being switched off
in November 2026, so we don't use it). We build the one span per call ourselves: no SDK,
no background threads, easy to test.

Sending never slows down or breaks a request: the gateway hands the trace to a Celery
task (`send_llm_trace`), which posts it and retries while Langfuse is unreachable.
"""

import base64
import json
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def new_trace_id() -> str:
    """32 hex characters (OpenTelemetry trace id)."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """16 hex characters (OpenTelemetry span id)."""
    return secrets.token_hex(8)


@dataclass
class TraceEvent:
    """One LLM call as Langfuse shows it."""

    trace_id: str
    span_id: str
    name: str  # the task name
    start_ns: int
    end_ns: int
    organization_id: str
    user_id: str | None
    provider: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_usd: float
    status: str  # "ok" or an error code
    attempts: int
    environment: str
    input: str | None = None  # only when LLM_TRACE_CONTENT is on
    output: str | None = None
    error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (the Celery task argument)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceEvent":
        """Inverse of to_dict."""
        return cls(**data)


def _attr(key: str, value: str | int | float | bool | list[str]) -> dict[str, Any]:
    if isinstance(value, bool):
        wrapped: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        wrapped = {"intValue": str(value)}
    elif isinstance(value, float):
        wrapped = {"doubleValue": value}
    elif isinstance(value, list):
        wrapped = {"arrayValue": {"values": [{"stringValue": v} for v in value]}}
    else:
        wrapped = {"stringValue": value}
    return {"key": key, "value": wrapped}


def otlp_payload(event: TraceEvent, service_name: str) -> dict[str, Any]:
    """The OTLP/HTTP JSON body with one "generation" span (Langfuse attribute names)."""
    usage = {
        "input": event.input_tokens - event.cached_input_tokens,
        "input_cached_tokens": event.cached_input_tokens,
        "output": event.output_tokens,
        "total": event.input_tokens + event.output_tokens,
    }
    attributes = [
        _attr("langfuse.trace.name", event.name),
        _attr("langfuse.observation.type", "generation"),
        _attr("langfuse.observation.model.name", event.model),
        _attr("gen_ai.request.model", event.model),
        _attr("gen_ai.system", event.provider),
        _attr("langfuse.observation.usage_details", json.dumps(usage)),
        _attr("langfuse.observation.cost_details", json.dumps({"total": event.cost_usd})),
        _attr("langfuse.environment", event.environment),
        _attr("langfuse.trace.tags", [f"task:{event.name}", f"provider:{event.provider}"]),
        # The workspace groups traces like a "session" (filter by workspace in Langfuse).
        _attr("langfuse.session.id", event.organization_id),
        _attr("langfuse.trace.metadata.organization_id", event.organization_id),
        _attr("langfuse.observation.metadata.attempts", str(event.attempts)),
    ]
    if event.user_id:
        attributes.append(_attr("langfuse.user.id", event.user_id))
    for key, value in event.metadata.items():
        attributes.append(_attr(f"langfuse.trace.metadata.{key}", value))
    if event.input is not None:
        attributes.append(_attr("langfuse.observation.input", event.input))
    if event.output is not None:
        attributes.append(_attr("langfuse.observation.output", event.output))
    ok = event.status == "ok"
    if not ok:
        attributes.append(_attr("langfuse.observation.level", "ERROR"))
        attributes.append(
            _attr("langfuse.observation.status_message", f"{event.status}: {event.error or ''}")
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", service_name)]},
                "scopeSpans": [
                    {
                        "scope": {"name": "product-foundation.llm_gateway"},
                        "spans": [
                            {
                                "traceId": event.trace_id,
                                "spanId": event.span_id,
                                "name": event.name,
                                "kind": 3,  # CLIENT: a call to an outside service
                                "startTimeUnixNano": str(event.start_ns),
                                "endTimeUnixNano": str(event.end_ns),
                                "attributes": attributes,
                                "status": {"code": 1 if ok else 2},  # OK / ERROR
                            }
                        ],
                    }
                ],
            }
        ]
    }


class LangfuseUnavailableError(Exception):
    """Langfuse could not be reached or answered 5xx / 429 (retry later)."""


class LangfuseExporter:
    """Posts one trace to Langfuse (called by the Celery task)."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        assert settings.langfuse_secret_key is not None
        token = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key.get_secret_value()}"
        self._url = f"{settings.langfuse_host}/api/public/otel/v1/traces"
        self._headers = {
            "Authorization": "Basic " + base64.b64encode(token.encode()).decode(),
            "Content-Type": "application/json",
            "x-langfuse-ingestion-version": "4",
        }
        self._service = settings.app_name
        self._client = client or httpx.Client(timeout=10.0)

    def send(self, event: TraceEvent) -> None:
        """Raises LangfuseUnavailableError for temporary problems; logs permanent ones."""
        try:
            res = self._client.post(
                self._url, headers=self._headers, json=otlp_payload(event, self._service)
            )
        except httpx.HTTPError as exc:
            raise LangfuseUnavailableError(str(exc)) from exc
        if res.status_code >= 500 or res.status_code == 429:
            raise LangfuseUnavailableError(f"HTTP {res.status_code}")
        if res.status_code >= 400:
            # Wrong keys or a payload Langfuse doesn't accept: retrying won't help.
            logger.error("langfuse_rejected", status=res.status_code, body=res.text[:300])


class Tracer(Protocol):
    """Where the gateway sends traces (tests use a list)."""

    def record(self, event: TraceEvent) -> None:
        """Hand the trace over. Must never raise."""
        ...


class NoTracer:
    """Tracing is off (no Langfuse keys)."""

    def record(self, event: TraceEvent) -> None:
        """Do nothing."""


class CeleryTracer:
    """Queues the trace for the worker, which sends it to Langfuse."""

    def record(self, event: TraceEvent) -> None:
        """Never raises: a trace must never break the product."""
        try:
            from app.workers.celery_app import celery_app

            celery_app.send_task(
                "app.workers.tasks.send_llm_trace",
                kwargs={"event": event.to_dict()},
                ignore_result=True,
                retry=True,
                retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2},
            )
        except Exception as exc:
            logger.warning("llm_trace_not_queued", error_type=type(exc).__name__)


def tracer_for(settings: Settings) -> Tracer:
    """Langfuse (through the worker) when configured, else nothing."""
    return CeleryTracer() if settings.langfuse_enabled else NoTracer()
