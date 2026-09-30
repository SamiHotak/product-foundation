"""Demo mode: a shared, realistic workspace behind the "Try the demo" button.

- `seed_demo()`        creates the demo user, a small team, jobs, files, API key, audit
                       events, AI usage and a paid plan. Safe to run many times.
- `reset_demo_data()`  deletes all of it and seeds it again (nightly, Celery beat).
- The demo user is READ-MOSTLY: app/core/restrictions.py refuses every change except a
  few harmless actions (run the example job, ask the AI, download a file). So one
  visitor can't change what the next visitor sees.

The demo user can't sign in with a password or Google: only through POST /auth/demo,
which works only when DEMO_ENABLED=true.

Products replace `SAMPLE_FILES`, `SAMPLE_JOBS` etc. with data that shows off their own
features (e.g. AskDocs: a few sample documents and questions).
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import hash_token, new_token
from app.db.session import sync_session
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.billing import Subscription, UsageRecord
from app.models.file import FileStatus, StoredFile
from app.models.job import Job, JobStatus
from app.models.llm_call import LlmCall
from app.models.organization import Membership, Organization, Role
from app.models.user import User
from app.services.storage import (
    ObjectStorage,
    StorageError,
    org_prefix,
    org_prefixes,
    storage_for,
)
from app.services.usage import month_start

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

DEMO_WORKSPACE = "Nordlicht Studio (demo)"
DEMO_PLAN = "pro"
# Only one process seeds at a time (two "Try the demo" clicks at once, or the nightly
# reset while someone clicks). A Postgres advisory lock, released at commit.
_LOCK_ID = 7_300_451


@dataclass(frozen=True)
class Teammate:
    """A pretend colleague in the demo workspace (can't sign in)."""

    name: str
    email: str
    role: Role
    joined_days_ago: int


TEAM: tuple[Teammate, ...] = (
    Teammate("Mia Weber", "mia.weber@example.com", Role.ADMIN, 40),
    Teammate("Jonas Becker", "jonas.becker@example.com", Role.MEMBER, 21),
    Teammate("Lena Hoffmann", "lena.hoffmann@example.com", Role.MEMBER, 6),
)

_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

# (file name, content type, bytes, uploaded by (index in TEAM, -1 = demo user), days ago)
SAMPLE_FILES: tuple[tuple[str, str, bytes, int, int], ...] = (
    (
        "Price list 2026.csv",
        "text/csv",
        b"product,size,price_eur\nWedding film,full day,2490\nImage film,2 min,1890\n"
        b"Photo shoot,half day,690\nDrone add-on,per day,350\n",
        0,
        12,
    ),
    (
        "Kick-off meeting notes.md",
        "text/plain",
        "# Kick-off with Bäckerei Lange\n\n- Goal: 3 short videos for Instagram\n"
        "- Shoot on 14 October, 7:00 (before the shop opens)\n"
        "- Budget agreed: 1,890 EUR\n- Next step: send the storyboard by Friday\n".encode(),
        1,
        5,
    ),
    ("Contract template.pdf", "application/pdf", _PDF, -1, 3),
    (
        "Welcome.txt",
        "text/plain",
        b"Welcome to the demo workspace! Everything you see is sample data.\n"
        b"It is reset every night.\n",
        -1,
        1,
    ),
)

SAMPLE_SUMMARY_TEXT = (
    "Bäckerei Lange wants three short Instagram videos. The shoot is on 14 October at "
    "7:00, before the shop opens. The budget of 1,890 EUR is agreed. The storyboard is "
    "due on Friday."
)


def _demo_user(session: Session, settings: Settings) -> User | None:
    return session.scalar(select(User).where(User.email == settings.demo_email))


def demo_organization_id(session: Session, settings: Settings) -> uuid.UUID | None:
    """The demo workspace (the demo user's workspace), or None if not seeded."""
    user = _demo_user(session, settings)
    if user is None:
        return None
    return session.scalar(
        select(Membership.organization_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
        .limit(1)
    )


def seed_demo(
    settings: Settings,
    storage: ObjectStorage | None = None,
    *,
    open_session: SessionFactory = sync_session,
    now: datetime | None = None,
) -> uuid.UUID:
    """Create the demo data unless it exists. Returns the demo user's id."""
    now = now or datetime.now(UTC)
    with open_session() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
        existing = _demo_user(session, settings)
        # Checked FIRST: "Try the demo" must never sign anyone into a real account.
        if existing is not None and not existing.is_demo:
            raise RuntimeError(
                f"{settings.demo_email} is a real account. Set DEMO_EMAIL to another address."
            )
        if existing is not None and demo_organization_id(session, settings) is not None:
            return existing.id
        user_id, uploads = _create(session, settings, storage is not None, now, existing)
    # Files are uploaded after the rows are saved (a failed upload leaves a harmless row
    # whose download says "not found" in storage; the next reset fixes it).
    if storage is not None:
        for key, data, content_type in uploads:
            try:
                storage.put(key, data, content_type)
            except StorageError as exc:
                logger.warning("demo_file_not_uploaded", error=str(exc))
    logger.info("demo_seeded", user_id=str(user_id))
    return user_id


def _create(
    session: Session,
    settings: Settings,
    with_files: bool,
    now: datetime,
    existing: User | None,
) -> tuple[uuid.UUID, list[tuple[str, bytes, str]]]:
    def ago(days: float, hours: float = 0) -> datetime:
        return now - timedelta(days=days, hours=hours)

    user = existing or User(
        email=settings.demo_email,
        name="Demo User",
        password_hash=None,  # no password: only POST /auth/demo signs in
        email_verified_at=ago(60),
        is_demo=True,
        created_at=ago(60),
    )
    session.add(user)
    org = Organization(name=DEMO_WORKSPACE, created_at=ago(60))
    session.add(org)
    session.flush()
    session.add(
        Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER, created_at=ago(60))
    )

    people: list[User] = []
    for mate in TEAM:
        person = session.scalar(select(User).where(User.email == mate.email))
        if person is None:
            person = User(
                email=mate.email,
                name=mate.name,
                password_hash=None,
                email_verified_at=ago(mate.joined_days_ago),
                is_demo=True,
                created_at=ago(mate.joined_days_ago),
            )
            session.add(person)
            session.flush()
        elif not person.is_demo:
            continue  # a real account uses this address: leave it out of the demo
        people.append(person)
        session.add(
            Membership(
                organization_id=org.id,
                user_id=person.id,
                role=mate.role,
                created_at=ago(mate.joined_days_ago),
            )
        )
        _audit(
            session,
            org.id,
            user.id,
            "member.joined",
            ago(mate.joined_days_ago),
            "user",
            person.id,
            {"role": mate.role.value},
        )

    def by(index: int) -> User:
        return user if index < 0 or index >= len(people) else people[index]

    # A paid plan without Stripe (no customer id): shows the paid limits and features.
    session.add(
        Subscription(
            organization_id=org.id,
            plan_id=DEMO_PLAN,
            interval="month",
            status="active",
            current_period_end=now + timedelta(days=18),
            trial_used=True,
        )
    )
    _audit(
        session,
        org.id,
        user.id,
        "billing.plan_changed",
        ago(30),
        None,
        None,
        {"from": "Free", "to": "Pro", "status": "active"},
    )

    secret = f"{settings.api_key_prefix}_{new_token()}"  # never shown: nobody can use it
    key = ApiKey(
        organization_id=org.id,
        name="Website contact form",
        prefix=secret[: len(settings.api_key_prefix) + 9],
        key_hash=hash_token(secret),
        scopes=["jobs:read", "jobs:write"],
        created_by_id=user.id,
        last_used_at=ago(0, 3),
        created_at=ago(25),
    )
    session.add(key)
    session.flush()
    _audit(
        session, org.id, user.id, "api_key.created", ago(25), "api_key", key.id, {"name": key.name}
    )

    _add_jobs(session, org.id, user, people, ago)
    uploads = _add_files(session, org.id, by, ago) if with_files else []
    _add_ai_usage(session, org.id, user, people, ago, now)
    _audit(session, org.id, user.id, "auth.login", ago(0, 1), None, None, {"method": "demo"})
    session.flush()
    return user.id, uploads


def _audit(
    session: Session,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: str,
    at: datetime,
    target_type: str | None,
    target_id: uuid.UUID | None,
    details: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            organization_id=org_id,
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            details=details,
            created_at=at,
        )
    )


def _add_jobs(
    session: Session,
    org_id: uuid.UUID,
    user: User,
    people: list[User],
    ago: Callable[..., datetime],
) -> None:
    starters = [user, *people]
    for i in range(6):
        started = ago(i * 2 + 1, 2)
        session.add(
            Job(
                organization_id=org_id,
                created_by_id=starters[i % len(starters)].id,
                kind="example",
                status=JobStatus.DONE,
                progress=100,
                message="Done",
                params={"steps": 5, "fail": False},
                result={"steps": 5, "message": "Finished 5 steps."},
                attempts=1,
                started_at=started,
                finished_at=started + timedelta(seconds=6),
                created_at=started,
            )
        )
    failed_at = ago(4, 5)
    session.add(
        Job(
            organization_id=org_id,
            created_by_id=starters[-1].id,
            kind="example",
            status=JobStatus.FAILED,
            progress=40,
            message="Failed",
            params={"steps": 5, "fail": True},
            error="The example job failed on purpose (to show what a failed job looks like).",
            attempts=1,
            started_at=failed_at,
            finished_at=failed_at + timedelta(seconds=3),
            created_at=failed_at,
        )
    )


def _add_files(
    session: Session,
    org_id: uuid.UUID,
    by: Callable[[int], User],
    ago: Callable[..., datetime],
) -> list[tuple[str, bytes, str]]:
    uploads = []
    for name, content_type, data, uploader, days in SAMPLE_FILES:
        file_id = uuid.uuid4()
        key = f"{org_prefix(org_id)}files/{file_id}"
        session.add(
            StoredFile(
                id=file_id,
                organization_id=org_id,
                uploaded_by_id=by(uploader).id,
                filename=name,
                content_type=content_type,
                size_bytes=len(data),
                storage_key=key,
                status=FileStatus.READY,
                upload_expires_at=ago(days),
                completed_at=ago(days),
                created_at=ago(days),
            )
        )
        _audit(
            session,
            org_id,
            by(uploader).id,
            "file.uploaded",
            ago(days),
            "file",
            file_id,
            {"filename": name, "size_bytes": len(data)},
        )
        uploads.append((key, data, content_type))
    return uploads


def _add_ai_usage(
    session: Session,
    org_id: uuid.UUID,
    user: User,
    people: list[User],
    ago: Callable[..., datetime],
    now: datetime,
) -> None:
    users = [user, *people]
    month = month_start(now)
    calls = 0
    for i in range(12):
        at = ago(i * 0.7, 1)
        if at.date() < month:
            continue
        calls += 1
        session.add(
            LlmCall(
                organization_id=org_id,
                user_id=users[i % len(users)].id,
                task="summarize",
                provider="openai",
                model="gpt-6-luna",
                status="ok" if i != 5 else "error",
                error_code=None if i != 5 else "rate_limited",
                input_tokens=420 + i * 37,
                cached_input_tokens=0,
                output_tokens=120 + i * 11,
                cost_micro_usd=(420 + i * 37) // 10 + (120 + i * 11) // 2,
                latency_ms=1400 + i * 90,
                attempts=1 if i != 5 else 3,
                trace_id=uuid.uuid4().hex,
                created_at=at,
            )
        )
    for metric, count in (("jobs_per_month", 37), ("ai_requests_per_month", calls)):
        session.add(
            UsageRecord(organization_id=org_id, metric=metric, period_start=month, count=count)
        )


def reset_demo_data(
    settings: Settings,
    storage: ObjectStorage | None = None,
    *,
    open_session: SessionFactory = sync_session,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete the demo workspace, its people and files, then seed it again.

    Demo visitors are signed out (their sessions belong to the deleted user).
    """
    storage = storage if storage is not None else storage_for(settings)
    with open_session() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})
        org_ids: list[uuid.UUID] = []
        user = _demo_user(session, settings)
        if user is not None and not user.is_demo:
            raise RuntimeError(f"{settings.demo_email} is a real account; not resetting it.")
        if user is not None:
            org_ids = list(
                session.scalars(
                    select(Membership.organization_id).where(Membership.user_id == user.id)
                )
            )
        if org_ids:
            session.execute(delete(Organization).where(Organization.id.in_(org_ids)))
        users = session.scalar(select(func.count()).select_from(User).where(User.is_demo)) or 0
        session.execute(delete(User).where(User.is_demo))
    files = 0
    if storage is not None:
        for org_id in org_ids:
            try:
                for prefix in org_prefixes(org_id):
                    files += storage.delete_prefix(prefix)
            except StorageError as exc:
                logger.warning("demo_files_not_deleted", error=str(exc))
    seed_demo(settings, storage, open_session=open_session, now=now)
    return {"workspaces": len(org_ids), "users": int(users), "files": files}
