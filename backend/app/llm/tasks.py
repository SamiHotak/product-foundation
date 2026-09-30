"""LLM tasks: WHAT the app asks a model to do. One entry per kind of request.

A task fixes the model, the instructions, the output shape (a Pydantic model = structured
output), size limits, timeout and retries. Code never calls a model directly; it runs a
task through the gateway:

    result = gateway.run("summarize", text, organization_id=..., user_id=...)
    result.output  # a Summary instance

To add a task to a product: write an output model, add an LlmTask to TASKS, add evaluation
examples in app/llm/evals/data/<task>.jsonl, and run `make eval ARGS="--task <task>"`.
Change a task's model without code: LLM_MODELS='{"summarize": "gpt-6.1-sol"}'.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict, Field


class Summary(BaseModel):
    """The example task's output.

    Keep output models to what OpenAI's strict schemas support: no string lengths
    (maxLength is rejected by the API). Check lengths in the task's `check` instead.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="A short title for the text, at most 8 words.")
    key_points: list[str] = Field(
        description="The 2 to 5 most important points, one short sentence each.",
        min_length=1,
        max_length=6,
    )
    language: str = Field(
        description="ISO 639-1 code of the language the text is written in, e.g. en or de."
    )


def _fake_summary(text: str) -> Summary:
    """The pretend model (LLM_DEV_FAKE): simple rules, same answer for the same text."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    words = (sentences[0] if sentences else text).split()
    title = " ".join(words[:8]).rstrip(".,;:!?") or "Untitled"
    points = [s[:200] for s in sentences[1:5]] or [text.strip()[:200] or "(empty)"]
    german = len(re.findall(r"\b(der|die|und|das|ist|nicht|mit)\b", text, re.IGNORECASE))
    english = len(re.findall(r"\b(the|and|is|of|to|with|not)\b", text, re.IGNORECASE))
    return Summary(title=title, key_points=points, language="de" if german > english else "en")


def _check_summary(output: BaseModel) -> str | None:
    assert isinstance(output, Summary)
    if not output.title.strip() or len(output.title) > 150:
        return "title empty or too long"
    if any(not p.strip() or len(p) > 500 for p in output.key_points):
        return "key point empty or too long"
    if not re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", output.language):
        return "language is not an ISO 639-1 code"
    return None


@dataclass(frozen=True)
class LlmTask:
    """One kind of LLM request."""

    name: str
    description: str
    model: str
    instructions: str
    output: type[BaseModel]
    max_input_chars: int = 20_000
    max_output_tokens: int = 2_000  # includes reasoning tokens on reasoning models
    timeout_seconds: float = 60.0  # per attempt
    max_attempts: int = 3  # retries temporary errors (rate limits, timeouts, 5xx)
    # Extra checks after the schema (return a reason to reject, or None).
    check: Callable[[BaseModel], str | None] | None = None
    # What the pretend model answers (local development only).
    fake: Callable[[str], BaseModel] | None = field(default=None, repr=False)


TASKS: dict[str, LlmTask] = {
    "summarize": LlmTask(
        name="summarize",
        description="Title and key points of a text (the example task).",
        model="gpt-6-luna",
        instructions=(
            "Summarize the user's text for a busy reader.\n"
            "- title: at most 8 words, in the language of the text.\n"
            "- key_points: 2 to 5 points, one short sentence each, in the language of the "
            "text, only facts that are in the text.\n"
            "- language: the ISO 639-1 code of the text's language."
        ),
        output=Summary,
        max_input_chars=5_000,
        max_output_tokens=1_500,
        timeout_seconds=45.0,
        check=_check_summary,
        fake=_fake_summary,
    ),
}


class UnknownTaskError(KeyError):
    """No task with this name."""


def get_task(name: str, model_overrides: dict[str, str] | None = None) -> LlmTask:
    """A task by name, with the model from LLM_MODELS if one is set for it."""
    if name not in TASKS:
        raise UnknownTaskError(name)
    task = TASKS[name]
    override = (model_overrides or {}).get(name)
    if override:
        return replace(task, model=override)
    return task
