"""The LLM gateway: the ONE way the app calls a language model.

    gateway = LlmGateway.from_settings(get_settings())
    result = gateway.run("summarize", text, organization_id=org.id, user_id=user.id)
    result.output  # the task's Pydantic model, already checked

For every call, in this order:
1. Kill switches: LLM_ENABLED=false (restart needed) or "Pause AI" in /admin (instant).
2. Guardrails: the input is size-limited and wrapped as data (app/llm/guardrails.py).
3. Plan limit: one "AI request" is counted for the workspace (402 limit_reached when the
   month's allowance is used up). It is given back if the model could not be reached.
4. The model is called with the task's model, instructions, output schema and timeout.
   Temporary errors (rate limits, timeouts, 5xx) are retried with backoff.
5. The answer is checked (schema + the task's own check).
6. Tokens, cost (app/llm/pricing.py), time and outcome are saved in `llm_calls`, and a
   trace goes to Langfuse (through the worker, never slowing the call down).

The gateway is synchronous (it runs in Celery workers). From async API code use
`await asyncio.to_thread(gateway.run, ...)`. Database work happens in its own short
transactions, so the usage count and cost are saved even if the caller fails later.
"""

import random
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger
from app.core.plans import DEFAULT_CATALOG, PlanCatalog
from app.llm import guardrails
from app.llm.pricing import cost_micro_usd, price_for
from app.llm.providers import LlmProvider, ProviderError, ProviderResult, provider_for
from app.llm.tasks import LlmTask, get_task
from app.llm.tracing import TraceEvent, Tracer, new_span_id, new_trace_id, tracer_for
from app.models.llm_call import LlmCall
from app.models.system_flag import Flag
from app.services.flags import read_flag
from app.services.usage import SyncUsageMeter

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

AI_OFF = "AI features are not set up on this server yet."
AI_PAUSED = "AI features are paused right now. Try again later."
AI_FAILED = "The AI service did not answer. Try again in a minute."
AI_BAD_ANSWER = "The AI gave an answer we could not use. Try again, or change the text a little."


class AiUnavailableError(ServiceUnavailableError):
    """AI is switched off, paused, or not configured."""

    code = "ai_unavailable"


class AiFailedError(AppError):
    """The model could not give a usable answer (after retries)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "ai_failed"


class AiInputError(AppError):
    """The input can't be sent (e.g. too long)."""

    code = "ai_input_invalid"


@dataclass(frozen=True)
class LlmResult:
    """A successful call."""

    output: BaseModel
    task: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    latency_ms: int
    attempts: int
    trace_id: str
    call_id: uuid.UUID

    @property
    def cost_usd(self) -> float:
        """Cost in US dollars."""
        return self.cost_micro_usd / 1_000_000


@dataclass
class _Attempts:
    count: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    last_error: ProviderError | None = None
    waits: list[float] = field(default_factory=list)


class LlmGateway:
    """Runs LLM tasks with limits, retries, cost accounting and tracing."""

    def __init__(
        self,
        settings: Settings,
        provider: LlmProvider | None,
        open_session: SessionFactory,
        *,
        catalog: PlanCatalog = DEFAULT_CATALOG,
        tracer: Tracer | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._open_session = open_session
        self._catalog = catalog
        self._tracer = tracer or tracer_for(settings)
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> "LlmGateway":
        """The gateway as configured by environment variables."""
        from app.db.session import sync_session

        return cls(settings, provider_for(settings), sync_session)

    @property
    def provider_name(self) -> str:
        """ "openai", "fake" or "none"."""
        return self._provider.name if self._provider else "none"

    def availability(self) -> str | None:
        """None when AI can be used, else the reason (for the UI and a quick 503)."""
        if not self._settings.llm_enabled or self._provider is None:
            return AI_OFF
        with self._open_session() as session:
            if read_flag(session, Flag.AI_PAUSED):
                return AI_PAUSED
        return None

    def run(
        self,
        task_name: str,
        text: str,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        metadata: dict[str, str] | None = None,
    ) -> LlmResult:
        """Run one task. Raises LimitReachedError (402), AiUnavailableError (503),
        AiInputError (400) or AiFailedError (502)."""
        task = get_task(task_name, self._settings.llm_models)
        reason = self.availability()
        if reason:
            raise AiUnavailableError(reason)
        provider = self._provider
        assert provider is not None
        try:
            user_input = guardrails.untrusted(text, max_chars=task.max_input_chars)
        except guardrails.InputTooLongError as exc:
            raise AiInputError(str(exc)) from exc
        instructions = guardrails.instructions(task.instructions)

        with self._open_session() as session:  # counted now, saved even if the call fails
            SyncUsageMeter(session, self._catalog).consume(organization_id, "ai_requests_per_month")

        trace_id, span_id = new_trace_id(), new_span_id()
        start_ns, started = time.time_ns(), time.perf_counter()
        attempts = _Attempts()
        result: ProviderResult | None = None
        rejection: str | None = None
        while attempts.count < task.max_attempts:
            attempts.count += 1
            try:
                try:
                    result = provider.complete(task, instructions, user_input)
                except ProviderError:
                    raise
                except Exception as unexpected:  # a bug or an SDK surprise: never retry it
                    logger.exception("llm_unexpected_error", task=task.name)
                    raise ProviderError(
                        "unexpected", type(unexpected).__name__, retryable=False
                    ) from unexpected
            except ProviderError as exc:
                attempts.last_error = exc
                attempts.input_tokens += exc.input_tokens
                attempts.output_tokens += exc.output_tokens
                logger.warning(
                    "llm_attempt_failed",
                    task=task.name,
                    code=exc.code,
                    attempt=attempts.count,
                    retryable=exc.retryable,
                )
                if not exc.retryable or attempts.count >= task.max_attempts:
                    break
                wait = exc.retry_after or min(8.0, 0.5 * 2 ** (attempts.count - 1))
                wait += random.uniform(0, wait / 4)  # noqa: S311 - jitter, not security
                attempts.waits.append(wait)
                self._sleep(wait)
                continue
            attempts.input_tokens += result.input_tokens
            attempts.cached_input_tokens += result.cached_input_tokens
            attempts.output_tokens += result.output_tokens
            rejection = task.check(result.output) if task.check else None
            if rejection is None:
                break
            logger.warning("llm_output_rejected", task=task.name, reason=rejection)
            result = None  # try again: the model sometimes gets it right the second time
        latency_ms = round((time.perf_counter() - started) * 1000)
        end_ns = time.time_ns()

        model = result.model if result else task.model
        price = price_for(model) or price_for(task.model)
        if price is None:
            logger.error("llm_price_missing", model=model, hint="add it to app/llm/pricing.py")
        cost = (
            cost_micro_usd(
                price,
                input_tokens=attempts.input_tokens,
                cached_input_tokens=attempts.cached_input_tokens,
                output_tokens=attempts.output_tokens,
            )
            if price
            else 0
        )
        if result is not None:
            status_code, error_code = "ok", None
        elif rejection is not None:
            status_code, error_code = "invalid_output", rejection[:64]
        else:
            status_code = "error"
            error_code = attempts.last_error.code if attempts.last_error else "unknown"

        with self._open_session() as session:
            if result is None and attempts.input_tokens == 0 and attempts.output_tokens == 0:
                # Nothing reached the model (or nothing was billed): the request doesn't count.
                SyncUsageMeter(session, self._catalog).release(
                    organization_id, "ai_requests_per_month"
                )
            call = LlmCall(
                organization_id=organization_id,
                user_id=user_id,
                task=task.name,
                provider=provider.name,
                model=model[:64],
                status=status_code,
                error_code=error_code,
                input_tokens=attempts.input_tokens,
                cached_input_tokens=attempts.cached_input_tokens,
                output_tokens=attempts.output_tokens,
                cost_micro_usd=cost,
                latency_ms=latency_ms,
                attempts=attempts.count,
                trace_id=trace_id,
            )
            session.add(call)
            session.flush()
            call_id = call.id

        self._trace(
            task,
            trace_id=trace_id,
            span_id=span_id,
            start_ns=start_ns,
            end_ns=end_ns,
            organization_id=organization_id,
            user_id=user_id,
            provider=provider.name,
            model=model,
            attempts=attempts,
            cost=cost,
            status=status_code if status_code == "ok" else (error_code or status_code),
            user_input=text,
            output=result.output_json if result else None,
            error=self._trace_error(attempts.last_error, rejection),
            metadata=metadata or {},
        )
        logger.info(
            "llm_call",
            task=task.name,
            model=model,
            status=status_code,
            error_code=error_code,
            attempts=attempts.count,
            input_tokens=attempts.input_tokens,
            output_tokens=attempts.output_tokens,
            cost_micro_usd=cost,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )
        if result is None:
            raise AiFailedError(AI_BAD_ANSWER if rejection else AI_FAILED)
        return LlmResult(
            output=result.output,
            task=task.name,
            model=model,
            input_tokens=attempts.input_tokens,
            cached_input_tokens=attempts.cached_input_tokens,
            output_tokens=attempts.output_tokens,
            cost_micro_usd=cost,
            latency_ms=latency_ms,
            attempts=attempts.count,
            trace_id=trace_id,
            call_id=call_id,
        )

    def _trace_error(self, error: ProviderError | None, rejection: str | None) -> str | None:
        """Error text for the trace. Details can quote the model's answer (derived from the
        user's text), so without LLM_TRACE_CONTENT only the error code is sent."""
        if error is None and rejection is None:
            return None
        if self._settings.llm_trace_content:
            return str(error) if error else rejection
        return error.code if error else "rejected_by_check"

    def _trace(
        self,
        task: LlmTask,
        *,
        user_input: str,
        output: str | None,
        attempts: _Attempts,
        cost: int,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        **values: Any,
    ) -> None:
        content = self._settings.llm_trace_content
        self._tracer.record(
            TraceEvent(
                name=task.name,
                organization_id=str(organization_id),
                user_id=str(user_id) if user_id else None,
                input_tokens=attempts.input_tokens,
                cached_input_tokens=attempts.cached_input_tokens,
                output_tokens=attempts.output_tokens,
                cost_usd=cost / 1_000_000,
                attempts=attempts.count,
                environment=self._settings.environment.value,
                input=user_input if content else None,
                output=output if content else None,
                **values,
            )
        )
