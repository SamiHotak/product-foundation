"""One row per LLM call made through the gateway (app/llm/gateway.py).

Used for costs per workspace (admin → Usage), debugging and the monthly cost report.
Prompts and answers are NOT stored here (only in Langfuse, if tracing content is on).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class LlmCall(UUIDPrimaryKeyMixin, Base):
    """What one AI request cost and how it went. Rows are never updated."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_org_created", "organization_id", "created_at"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    task: Mapped[str] = mapped_column(String(64))  # the task name from app/llm/tasks.py
    provider: Mapped[str] = mapped_column(String(16))  # "openai" or "fake"
    model: Mapped[str] = mapped_column(String(64))
    # "ok", "error" (the model failed after all retries) or "invalid_output".
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Cost in millionths of a US dollar (1 USD = 1,000,000). Integers never round badly.
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    # Links the row to its Langfuse trace (32 hex characters).
    trace_id: Mapped[str] = mapped_column(String(32))
