"""Nightly GDPR jobs (Celery beat): delete what is due, and remove old data.

- `purge_due()`   deletes accounts and workspaces whose deletion date has passed.
- `cleanup()`     removes expired export ZIPs and audit events past their retention.

Each account / workspace is deleted in its own transaction, so one problem never
blocks the others. Deleting a row cascades to its data through foreign keys.

A workspace that ever started a checkout: its Stripe customer is deleted first. That ends
every subscription at once (no refund, no further charges) and removes the personal data
from Stripe (Stripe keeps the invoices tax law requires). If Stripe can't be reached, that
workspace waits for the next night.

The workspace's stored files (everything under "orgs/<id>/" in the bucket) are deleted
before its rows. If the storage can't be reached, that workspace also waits a night.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.organization import Role
from app.repositories.billing import SyncBillingRepository
from app.repositories.deletion import SyncDeletionRepository
from app.repositories.exports import SyncMaintenance
from app.services.audit import SYSTEM_FLAG, AuditAction

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]
DeleteCustomer = Callable[[str], None]
# Deletes every stored object of a workspace (app.services.storage.org_prefix).
DeleteFiles = Callable[[uuid.UUID], None]


@dataclass(frozen=True)
class Outside:
    """Data outside Postgres that goes with a workspace (None = that service is off)."""

    delete_customer: DeleteCustomer | None = None
    delete_files: DeleteFiles | None = None


def _delete_org(session: Session, org_id: uuid.UUID, outside: Outside) -> None:
    """Delete the workspace's Stripe customer (if any), its files, then the workspace."""
    customer_id = SyncBillingRepository(session).customer_id(org_id)
    if customer_id and outside.delete_customer is not None:
        # Raises -> this deletion is rolled back and retried tomorrow.
        outside.delete_customer(customer_id)
    if outside.delete_files is not None:
        outside.delete_files(org_id)  # raises -> same: retried tomorrow
    SyncDeletionRepository(session).delete_org(org_id)


def _purge_user(session: Session, user_id: uuid.UUID, now: datetime, outside: Outside) -> bool:
    """Delete one account. Returns False if it was cancelled in the meantime."""
    repo = SyncDeletionRepository(session)
    user = repo.lock_user(user_id)
    if user is None or user.deletion_scheduled_at is None or user.deletion_scheduled_at > now:
        return False
    for membership, size in repo.memberships(user_id):
        org_id = membership.organization_id
        if size == 1:
            _delete_org(session, org_id, outside)  # nobody else is in it
        elif membership.role is Role.OWNER:
            # Owners of shared workspaces are blocked when scheduling; this covers people
            # who joined afterwards. The longest-standing admin (else member) takes over.
            successor = repo.successor(org_id, user_id)
            assert successor is not None
            successor.role = Role.OWNER
            session.add(
                AuditLog(
                    organization_id=org_id,
                    action=AuditAction.ORG_OWNERSHIP_TRANSFERRED.value,
                    target_type="user",
                    target_id=str(successor.user_id),
                    details={
                        SYSTEM_FLAG: True,
                        "reason": "The previous owner deleted their account.",
                    },
                )
            )
    SyncMaintenance(session).delete_account_events(user_id)
    repo.delete_user(user_id)
    return True


def _purge_org(session: Session, org_id: uuid.UUID, now: datetime, outside: Outside) -> bool:
    """Delete one workspace. Returns False if it was cancelled in the meantime."""
    repo = SyncDeletionRepository(session)
    org = repo.lock_org(org_id)
    if org is None or org.deletion_scheduled_at is None or org.deletion_scheduled_at > now:
        return False
    _delete_org(session, org_id, outside)
    return True


def _run_each(
    ids: list[uuid.UUID],
    open_session: SessionFactory,
    work: Callable[[Session, uuid.UUID, datetime, Outside], bool],
    now: datetime,
    kind: str,
    outside: Outside,
) -> int:
    """Run `work` for every id, one transaction each. Returns how many were deleted."""
    deleted = 0
    for item_id in ids:
        try:
            with open_session() as session:
                done = work(session, item_id, now, outside)
        except Exception as exc:
            logger.error("purge_failed", kind=kind, id=str(item_id), error_type=type(exc).__name__)
            continue
        deleted += int(done)
    return deleted


def purge_due(
    open_session: SessionFactory,
    now: datetime,
    delete_customer: DeleteCustomer | None = None,
    delete_files: DeleteFiles | None = None,
) -> dict[str, int]:
    """Delete every account and workspace whose deletion date has passed.

    `delete_customer(stripe_customer_id)` removes the Stripe customer first (None: billing off).
    `delete_files(organization_id)` removes the workspace's stored files (None: no storage).
    """
    outside = Outside(delete_customer, delete_files)
    with open_session() as session:
        repo = SyncDeletionRepository(session)
        user_ids, org_ids = repo.users_due(now), repo.orgs_due(now)
    users = _run_each(user_ids, open_session, _purge_user, now, "user", outside)
    orgs = _run_each(org_ids, open_session, _purge_org, now, "workspace", outside)
    return {"users": users, "workspaces": orgs}


def cleanup(
    open_session: SessionFactory, now: datetime, *, audit_retention_days: int
) -> dict[str, int]:
    """Remove expired export files and old audit events."""
    with open_session() as session:
        maintenance = SyncMaintenance(session)
        exports = maintenance.delete_expired_exports(now)
        audit = maintenance.delete_old_audit(now - timedelta(days=audit_retention_days))
        # Stripe retries a webhook for up to 3 days; 30 days of event ids is plenty.
        events = SyncBillingRepository(session).delete_old_events(now - timedelta(days=30))
    return {"exports": exports, "audit_events": audit, "stripe_events": events}
