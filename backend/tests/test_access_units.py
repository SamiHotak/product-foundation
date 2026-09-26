"""Unit tests for the access rules and small helpers (no database)."""

import typing
import uuid
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from app.core.errors import PermissionDeniedError
from app.core.permissions import API_KEY_SCOPES, ROLE_PERMISSIONS, Permission, role_permissions
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.routers.auth import safe_next
from app.routers.deps import bearer_token
from app.schemas.api_keys import ApiKeyScope
from app.services import email as emails
from app.services.audit import (
    SYSTEM_FLAG,
    InvalidCursorError,
    audit_entry,
    decode_cursor,
    encode_cursor,
)
from app.services.export_builder import _jsonable
from app.services.organizations import Caller


def test_roles_are_nested_member_admin_owner() -> None:
    member, admin, owner = (ROLE_PERMISSIONS[r] for r in ("member", "admin", "owner"))
    assert member < admin < owner
    assert owner - admin == {Permission.ORG_DELETE, Permission.OWNERSHIP_TRANSFER}
    assert Permission.MEMBERS_INVITE not in member
    assert role_permissions("nonsense") == frozenset()


def test_api_key_scopes_are_safe_and_match_the_schema() -> None:
    # Keys can only do what a normal member can do: never manage the team or keys.
    assert ROLE_PERMISSIONS["member"] >= API_KEY_SCOPES
    assert Permission.API_KEYS_MANAGE not in API_KEY_SCOPES
    # The API schema lists exactly these scopes (update both together).
    assert set(typing.get_args(ApiKeyScope)) == {p.value for p in API_KEY_SCOPES}


def test_caller_require() -> None:
    org = Organization(id=uuid.uuid4(), name="x")
    key_caller = Caller(organization=org, permissions=frozenset({Permission.JOBS_READ}))
    key_caller.require(Permission.JOBS_READ)
    with pytest.raises(PermissionDeniedError):
        key_caller.require(Permission.JOBS_WRITE)
    assert key_caller.user_id is None and key_caller.api_key_id is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/invite?token=abc", "/invite?token=abc"),
        ("/dashboard", "/dashboard"),
        (None, None),
        ("", None),
        ("https://evil.example", None),
        ("//evil.example/path", None),
        ("/\\evil.example", None),
        ("/ok\nSet-Cookie: x=1", None),
        ("/" + "a" * 600, None),
    ],
)
def test_safe_next_only_allows_paths_in_this_app(value: str | None, expected: str | None) -> None:
    assert safe_next(value) == expected


def _request(authorization: str | None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request({"type": "http", "headers": headers})


def test_bearer_token_parsing() -> None:
    assert bearer_token(_request("Bearer pf_abc")) == "pf_abc"
    assert bearer_token(_request("bearer   pf_abc  ")) == "pf_abc"
    assert bearer_token(_request("Basic dXNlcjpwdw==")) is None
    assert bearer_token(_request(None)) is None


def test_cursor_round_trip_and_garbage() -> None:
    stamp, row_id = datetime(2026, 9, 27, 10, 30, 1, 123456, tzinfo=UTC), uuid.uuid4()
    assert decode_cursor(encode_cursor(stamp, row_id)) == (stamp, row_id)
    for bad in ["", "nope", "!!!", encode_cursor(stamp, row_id)[:-6]]:
        with pytest.raises(InvalidCursorError):
            decode_cursor(bad)


def test_audit_actor_labels() -> None:
    base = {"id": uuid.uuid4(), "created_at": datetime.now(UTC), "action": "x.y"}
    user = User(id=uuid.uuid4(), name="Ezat", email="e@example.com")
    key = ApiKey(id=uuid.uuid4(), name="CI", prefix="pf_12345678")
    as_user = audit_entry((AuditLog(**base, details={}, actor_user_id=user.id), user, None))
    assert as_user.actor.type == "user" and as_user.actor.email == "e@example.com"
    as_key = audit_entry((AuditLog(**base, details={}, actor_api_key_id=key.id), None, key))
    assert as_key.actor.type == "api_key" and "pf_12345678" in (as_key.actor.name or "")
    system = audit_entry((AuditLog(**base, details={SYSTEM_FLAG: True, "reason": "r"}), None, None))
    assert system.actor.type == "system" and system.details == {"reason": "r"}
    deleted = audit_entry((AuditLog(**base, details={}), None, None))
    assert deleted.actor.type == "deleted_user"


def test_invite_email_escapes_names() -> None:
    mail = emails.invite_email(
        to="a@example.com",
        inviter_name="<script>alert(1)</script>",
        organization_name="Acme & Co",
        role="admin",
        url="http://localhost:3000/invite?token=abc",
        app_name="Foundation",
        days=7,
    )
    assert mail.html is not None and "<script>" not in mail.html
    assert "&amp; Co" in mail.html
    assert "as an admin" in mail.text
    assert "/invite?token=abc" in mail.text


def test_deletion_emails_explain_how_to_cancel() -> None:
    account = emails.account_deletion_email(
        to="a@example.com", name="A", when="11 October 2026", settings_url="u", app_name="F"
    )
    workspace = emails.workspace_deletion_email(
        to="a@example.com",
        name="A",
        organization_name="Acme",
        when="11 October 2026",
        settings_url="u",
        app_name="F",
    )
    assert "11 October 2026" in account.subject and "cancel" in account.text
    assert "Acme" in workspace.subject and "Cancel it" in workspace.text


def test_export_json_conversion() -> None:
    row_id = uuid.uuid4()
    out = _jsonable({"id": row_id, "at": datetime(2026, 1, 2, tzinfo=UTC), "list": [(1, 2)]})
    assert out == {"id": str(row_id), "at": "2026-01-02T00:00:00+00:00", "list": [[1, 2]]}
