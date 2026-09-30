"""LLM providers: the code that actually talks to a model.

- `OpenAIProvider`  the OpenAI Responses API with Structured Outputs (the model must answer
                    with the task's JSON schema; we check it again with Pydantic).
- `FakeProvider`    a pretend model for local development and e2e tests (LLM_DEV_FAKE).
                    Tests use their own scripted fakes (tests/fakes.py).

Retries, costs, limits and tracing are NOT here: the gateway does them for every provider.
Providers only translate: one attempt in, a `ProviderResult` or a `ProviderError` out.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm.tasks import LlmTask


@dataclass(frozen=True)
class ProviderResult:
    """One successful answer."""

    output: BaseModel
    output_json: str
    model: str  # the exact model that answered (may be a dated snapshot)
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    response_id: str | None = None


class ProviderError(Exception):
    """One attempt failed. `retryable`: trying again may help (rate limit, timeout, 5xx)."""

    def __init__(
        self, code: str, message: str, *, retryable: bool, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        # Tokens are billed even when the answer is unusable (e.g. cut off, refused).
        self.input_tokens = 0
        self.output_tokens = 0


class LlmProvider(Protocol):
    """Makes ONE attempt of a task."""

    name: str

    def complete(self, task: LlmTask, instructions: str, user_input: str) -> ProviderResult:
        """Call the model once. Raises ProviderError."""
        ...


class OpenAIProvider:
    """OpenAI Responses API + Structured Outputs."""

    name = "openai"

    def __init__(self, api_key: str, base_url: str | None = None, http_client: Any = None) -> None:
        import openai

        self._openai = openai
        # max_retries=0: the gateway retries (so every attempt is counted and traced).
        # `http_client`: tests pass an httpx client with a fake transport.
        self._client = openai.OpenAI(
            api_key=api_key, base_url=base_url or None, max_retries=0, http_client=http_client
        )

    def complete(self, task: LlmTask, instructions: str, user_input: str) -> ProviderResult:
        """One attempt. We parse the answer ourselves (not `responses.parse`), so the
        tokens are known even when the answer is cut off, refused or not valid JSON."""
        openai = self._openai
        try:
            response = self._client.responses.create(
                model=task.model,
                instructions=instructions,
                input=user_input,
                text={"format": _text_format(task.output)},
                max_output_tokens=task.max_output_tokens,
                store=False,  # don't keep the conversation at OpenAI
                timeout=task.timeout_seconds,
            )
        except openai.RateLimitError as exc:
            raise ProviderError(
                "rate_limited", str(exc), retryable=True, retry_after=_retry_after(exc)
            ) from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("timeout", str(exc), retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("connection_error", str(exc), retryable=True) from exc
        except openai.InternalServerError as exc:
            raise ProviderError("server_error", str(exc), retryable=True) from exc
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "auth_error", "The OpenAI API key is wrong.", retryable=False
            ) from exc
        except openai.APIStatusError as exc:
            # 400 (bad request, unknown model), 403, 404, 422: trying again won't help.
            raise ProviderError(f"http_{exc.status_code}", str(exc), retryable=False) from exc

        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        cached = 0
        if usage and usage.input_tokens_details:
            cached = usage.input_tokens_details.cached_tokens or 0

        def fail(code: str, message: str, *, retryable: bool) -> ProviderError:
            error = ProviderError(code, message, retryable=retryable)
            error.input_tokens, error.output_tokens = input_tokens, output_tokens
            return error

        if response.status == "incomplete":
            # Usually max_output_tokens: the same request would be cut off again.
            raise fail("incomplete", "The answer was cut off.", retryable=False)
        if any(
            getattr(part, "type", None) == "refusal"
            for item in response.output
            for part in getattr(item, "content", None) or []
        ):
            raise fail("refused", "The model refused to answer.", retryable=False)
        try:
            parsed = task.output.model_validate_json(response.output_text)
        except ValidationError as exc:
            raise fail("invalid_output", str(exc)[:500], retryable=True) from exc
        return ProviderResult(
            output=parsed,
            output_json=parsed.model_dump_json(),
            model=response.model,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output_tokens,
            response_id=response.id,
        )


def _text_format(output: type[BaseModel]) -> Any:
    """The Structured Outputs format (strict JSON schema) for a Pydantic model."""
    from openai.lib._parsing._responses import type_to_text_format_param

    return type_to_text_format_param(output)


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return min(float(value), 30.0) if value else None
    except ValueError:
        return None


class FakeProvider:
    """A pretend model: answers with the task's `fake` function. Free, fast, no network."""

    name = "fake"

    def __init__(self, delay_seconds: float = 0.4) -> None:
        self._delay = delay_seconds

    def complete(self, task: LlmTask, instructions: str, user_input: str) -> ProviderResult:
        """Deterministic answer from the task's fake function."""
        if task.fake is None:
            raise ProviderError(
                "no_fake", f"Task {task.name!r} has no fake answer.", retryable=False
            )
        time.sleep(self._delay)  # feels like a model; shows the progress in the UI
        text = user_input.removeprefix("<user_content>\n").removesuffix("\n</user_content>")
        output = task.fake(text)
        return ProviderResult(
            output=output,
            output_json=output.model_dump_json(),
            model="fake",
            input_tokens=max(1, (len(instructions) + len(user_input)) // 4),
            cached_input_tokens=0,
            output_tokens=max(1, len(output.model_dump_json()) // 4),
            response_id=f"fake_{uuid.uuid4().hex[:12]}",
        )


_openai_clients: dict[tuple[str, str | None], OpenAIProvider] = {}


def provider_for(settings: Settings) -> LlmProvider | None:
    """OpenAI with a key, the pretend model in dev (LLM_DEV_FAKE), else None (AI is off)."""
    if settings.openai_enabled:
        assert settings.openai_api_key is not None
        key = (settings.openai_api_key.get_secret_value(), settings.openai_base_url)
        if key not in _openai_clients:  # one HTTP client per key (connection reuse)
            _openai_clients[key] = OpenAIProvider(*key)
        return _openai_clients[key]
    if settings.llm_dev_fake:
        return FakeProvider()
    return None
