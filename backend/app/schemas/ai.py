"""AI schemas (the API contract)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AiStatus(BaseModel):
    """Can this workspace use AI right now?"""

    available: bool
    reason: str | None = Field(description="Why not, for people (when not available).")
    provider: Literal["openai", "fake", "none"] = Field(
        description='"fake": the pretend model for local development (fixed answers, free).'
    )
    can_use: bool = Field(description="The caller's role allows AI features.")
    sample_text: str = Field(description="A text to try the summary with.")
    samples_only: bool = Field(
        description="Only the sample text can be summarized (the shared demo)."
    )


class SummaryCreate(BaseModel):
    """Summarize a text (the example AI task)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=20, max_length=5000)
