"""Phase 4B: uploaded files, LLM call log, runtime switches (AI kill switch),
impersonation sessions for admins, and the demo user flag.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "files",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "uploading",
                "scanning",
                "ready",
                "rejected",
                name="file_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("status_message", sa.String(length=300), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_files_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_files_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_files_storage_key")),
    )
    op.create_index(
        "ix_files_org_created", "files", ["organization_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_files_status"), "files", ["status"], unique=False)
    op.create_index(op.f("ix_files_uploaded_by_id"), "files", ["uploaded_by_id"], unique=False)
    op.create_table(
        "llm_calls",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_llm_calls_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_llm_calls_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_created_at"), "llm_calls", ["created_at"], unique=False)
    op.create_index(op.f("ix_llm_calls_user_id"), "llm_calls", ["user_id"], unique=False)
    op.create_index(
        "ix_llm_calls_org_created", "llm_calls", ["organization_id", "created_at"], unique=False
    )
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_system_flags_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_flags")),
    )
    op.add_column("sessions", sa.Column("impersonator_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sessions_impersonator_id_users"),
        "sessions",
        "users",
        ["impersonator_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_sessions_impersonator_id"), "sessions", ["impersonator_id"], unique=False
    )
    op.add_column(
        "users", sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_column("users", "is_demo")
    op.drop_index(op.f("ix_sessions_impersonator_id"), table_name="sessions")
    op.drop_constraint(op.f("fk_sessions_impersonator_id_users"), "sessions", type_="foreignkey")
    op.drop_column("sessions", "impersonator_id")
    op.drop_table("system_flags")
    op.drop_index("ix_llm_calls_org_created", table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_user_id"), table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_created_at"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(op.f("ix_files_uploaded_by_id"), table_name="files")
    op.drop_index(op.f("ix_files_status"), table_name="files")
    op.drop_index("ix_files_org_created", table_name="files")
    op.drop_table("files")
