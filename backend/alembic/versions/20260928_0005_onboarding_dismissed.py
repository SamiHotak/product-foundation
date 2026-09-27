"""Remember when a person hid the "Get started" checklist in a workspace.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "memberships",
        sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Revert the migration."""
    op.drop_column("memberships", "onboarding_dismissed_at")
