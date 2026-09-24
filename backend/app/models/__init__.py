"""ORM models. Import every model here so Alembic autogenerate can see it.

Phase 1 has no tables yet. Planned (see docs/ARCHITECTURE.md): User, Organization,
Membership, Invite, ApiKey, AuditLog (phase 2), Job (phase 1B), Subscription,
UsageRecord, File (phase 4).
"""

from app.db.base import Base

__all__ = ["Base"]
