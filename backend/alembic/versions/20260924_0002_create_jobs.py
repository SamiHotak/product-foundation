"""Create the jobs table (background job status for the live UI).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "done",
                "failed",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name=op.f("ck_jobs_progress_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_jobs_kind"), "jobs", ["kind"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_kind"), table_name="jobs")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_table("jobs")
