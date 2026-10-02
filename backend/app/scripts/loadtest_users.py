"""Test users with ready-made sessions for the load test (docs/LOADTEST.md).

Signing up 50 people one by one is not possible on purpose (email checks, 20 auth requests per
minute per address). So this script creates verified test users directly, each with their own
workspace and a session, and writes the session cookies to a file that k6 reads.

    python -m app.scripts.loadtest_users --users 50 --out /tmp/loadtest-users.json
    python -m app.scripts.loadtest_users --cleanup          (deletes them all again)

The users are named loadtest-<n>@loadtest.example.com (example.com is reserved: it never
receives email) and their workspaces "Loadtest workspace <n>". Each run gives them a new random
password. Cleanup deletes those users and the workspaces that only they belong to.
In production the script refuses to run unless you add --allow-production (do it before you have
customers, then clean up).
"""

import argparse
import json
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select

from app.core.config import Environment, get_settings
from app.core.security import hash_password, hash_token, new_token
from app.db.session import sync_session
from app.models.organization import Membership, Organization, Role
from app.models.session import UserSession
from app.models.user import User

EMAIL_DOMAIN = "@loadtest.example.com"
WORKSPACE_PREFIX = "Loadtest workspace "
MAX_USERS = 500


def create_users(count: int, hours: int) -> list[dict[str, str]]:
    """Create `count` verified users (own workspace, one session each). Returns cookie data."""
    now = datetime.now(UTC)
    # A new random password on every run (also for users that already exist): the test accounts
    # are never loginable with a password that is written down somewhere.
    password = secrets.token_urlsafe(18)
    password_hash = hash_password(password)  # one hash for all: Argon2 is slow on purpose
    rows: list[dict[str, str]] = []
    with sync_session() as session:
        for n in range(1, count + 1):
            email = f"loadtest-{n}{EMAIL_DOMAIN}"
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    name=f"Load Test {n}",
                    password_hash=password_hash,
                    email_verified_at=now,
                )
                session.add(user)
                session.flush()
            else:
                user.password_hash = password_hash
                user.email_verified_at = user.email_verified_at or now
            org_id = session.scalar(
                select(Membership.organization_id)
                .where(Membership.user_id == user.id)
                .order_by(Membership.created_at)
                .limit(1)
            )
            if org_id is None:
                org = Organization(name=f"{WORKSPACE_PREFIX}{n}")
                session.add(org)
                session.flush()
                session.add(Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER))
                org_id = org.id
            token = new_token()
            session.add(
                UserSession(
                    token_hash=hash_token(token),
                    user_id=user.id,
                    active_organization_id=org_id,
                    expires_at=now + timedelta(hours=hours),
                    last_seen_at=now,
                    user_agent="k6-loadtest",
                )
            )
            rows.append({"email": email, "password": password, "token": token})
    return rows


def cleanup() -> tuple[int, int]:
    """Delete the load test users, and the workspaces that ONLY they belong to.

    A workspace is found through its test members, not through its name (a customer can name a
    workspace anything). A workspace that has even one real member is kept.
    """
    with sync_session() as session:
        test_users = select(User.id).where(User.email.like(f"%{EMAIL_DOMAIN}"))
        with_test_member = select(Membership.organization_id).where(
            Membership.user_id.in_(test_users)
        )
        with_real_member = select(Membership.organization_id).where(
            Membership.user_id.not_in(test_users)
        )
        orgs = cast(
            "CursorResult[Any]",
            session.execute(
                delete(Organization).where(
                    Organization.id.in_(with_test_member),
                    Organization.id.not_in(with_real_member),
                )
            ),
        )
        users = cast(
            "CursorResult[Any]",
            session.execute(delete(User).where(User.email.like(f"%{EMAIL_DOMAIN}"))),
        )
        return orgs.rowcount, users.rowcount


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("/tmp/loadtest-users.json"))  # noqa: S108
    parser.add_argument("--hours", type=int, default=3, help="how long the sessions last")
    parser.add_argument("--cleanup", action="store_true", help="delete the test users again")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.environment == Environment.PRODUCTION and not args.allow_production:
        print(
            "This is a PRODUCTION environment. Test users would end up in the real database.\n"
            "Do this only before you have customers, add --allow-production, "
            "and run --cleanup after."
        )
        return 1
    if args.cleanup:
        orgs, users = cleanup()
        print(f"Deleted {users} test users and {orgs} test workspaces.")
        return 0
    if not 1 <= args.users <= MAX_USERS:
        print(f"--users must be between 1 and {MAX_USERS}.")
        return 2
    rows = create_users(args.users, args.hours)
    payload = {"cookie_name": settings.session_cookie_name, "users": rows}
    # The file holds live session cookies: only the owner may read it.
    # O_NOFOLLOW: never write through a symlink someone planted. fchmod: also fix an old file.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(args.out, flags, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle)
    print(f"{len(rows)} test users ready. Sessions are in {args.out} (valid {args.hours} hours).")
    print("When you are done:  python -m app.scripts.loadtest_users --cleanup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
