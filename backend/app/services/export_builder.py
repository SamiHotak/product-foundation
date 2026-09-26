"""Build GDPR export ZIPs (runs in the Celery worker).

A ZIP holds one JSON file per section plus a README. Products add their own data by
registering a section, e.g. in their own module:

    from app.services.export_builder import ORG_SECTIONS
    ORG_SECTIONS["documents.json"] = lambda reader, org_id: [...]

Rules: only the data of ONE user / ONE workspace; never password hashes, token hashes,
API key hashes or other secrets.
"""

import io
import json
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.data_export import DataExport, ExportScope
from app.models.job import Job
from app.repositories.exports import SyncExportReader

Section = Callable[[SyncExportReader, uuid.UUID], Any]


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _audit(rows: list[AuditLog]) -> list[dict[str, Any]]:
    return [
        {
            "at": a.created_at,
            "action": a.action,
            "workspace_id": a.organization_id,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "details": a.details,
            "ip_address": a.ip_address,
            "user_agent": a.user_agent,
        }
        for a in rows
    ]


def _jobs(rows: list[Job]) -> list[dict[str, Any]]:
    return [
        {
            "id": j.id,
            "kind": j.kind,
            "status": j.status,
            "created_at": j.created_at,
            "finished_at": j.finished_at,
            "params": j.params,
            "result": j.result,
            "error": j.error,
        }
        for j in rows
    ]


def _keys(rows: list[ApiKey]) -> list[dict[str, Any]]:
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "scopes": k.scopes,
            "created_at": k.created_at,
            "expires_at": k.expires_at,
            "last_used_at": k.last_used_at,
            "revoked_at": k.revoked_at,
        }
        for k in rows
    ]


# --- account sections (argument: user id) ---------------------------------------------------


def _profile(r: SyncExportReader, user_id: uuid.UUID) -> dict[str, Any]:
    user = r.user(user_id)
    assert user is not None
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "email_verified_at": user.email_verified_at,
        "sign_in_with_password": user.password_hash is not None,
        "sign_in_with_google": user.google_sub is not None,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "deletion_scheduled_at": user.deletion_scheduled_at,
    }


def _workspaces(r: SyncExportReader, user_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {"workspace_id": o.id, "workspace": o.name, "role": m.role, "joined_at": m.created_at}
        for m, o in r.memberships(user_id)
    ]


def _sessions(r: SyncExportReader, user_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "signed_in_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "expires_at": s.expires_at,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
        }
        for s in r.sessions(user_id)
    ]


ACCOUNT_SECTIONS: dict[str, Section] = {
    "profile.json": _profile,
    "workspaces.json": _workspaces,
    "sign_ins.json": _sessions,
    "activity.json": lambda r, uid: _audit(r.activity(uid)),
    "jobs.json": lambda r, uid: _jobs(r.jobs_by_user(uid)),
}


# --- workspace sections (argument: organization id) -----------------------------------------


def _workspace(r: SyncExportReader, org_id: uuid.UUID) -> dict[str, Any]:
    org = r.organization(org_id)
    assert org is not None
    return {"id": org.id, "name": org.name, "created_at": org.created_at}


def _members(r: SyncExportReader, org_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "user_id": u.id,
            "name": u.name,
            "email": u.email,
            "role": m.role,
            "joined_at": m.created_at,
        }
        for m, u in r.members(org_id)
    ]


def _invites(r: SyncExportReader, org_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "email": i.email,
            "role": i.role,
            "created_at": i.created_at,
            "expires_at": i.expires_at,
            "accepted_at": i.accepted_at,
            "revoked_at": i.revoked_at,
        }
        for i in r.invites(org_id)
    ]


ORG_SECTIONS: dict[str, Section] = {
    "workspace.json": _workspace,
    "members.json": _members,
    "invites.json": _invites,
    "api_keys.json": lambda r, oid: _keys(r.api_keys(oid)),
    "audit_log.json": lambda r, oid: _audit(r.audit_log(oid)),
    "jobs.json": lambda r, oid: _jobs(r.jobs(oid)),
}


README = """This ZIP contains a copy of your data from {app} ({scope}).
Created: {created} (UTC)

Each .json file is one part of the data (UTF-8 JSON, times in ISO 8601, UTC).
Secrets (password hashes, API keys, sign-in tokens) are never included.
Questions about your data? Reply to any email from us.
"""


def build_zip(
    reader: SyncExportReader,
    export: DataExport,
    *,
    app_name: str,
    progress: Callable[[int, str], None] | None = None,
) -> bytes:
    """Collect every section and return the ZIP file as bytes."""
    if export.scope is ExportScope.ACCOUNT:
        assert export.user_id is not None
        sections, subject_id, scope = ACCOUNT_SECTIONS, export.user_id, "your account"
    else:
        assert export.organization_id is not None
        sections, subject_id, scope = ORG_SECTIONS, export.organization_id, "a workspace"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        created = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        archive.writestr("README.txt", README.format(app=app_name, scope=scope, created=created))
        for index, (name, section) in enumerate(sections.items(), start=1):
            data = _jsonable(section(reader, subject_id))
            archive.writestr(name, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            if progress:
                progress(round(index / len(sections) * 90), f"Collected {name}")
    return buffer.getvalue()
