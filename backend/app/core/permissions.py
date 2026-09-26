"""Who may do what. The ONE place to read or change the rules.

Roles (per workspace):
- owner   exactly one per workspace. Everything, incl. deleting the workspace and giving
          ownership to someone else.
- admin   manages the team (invite, change roles, remove), API keys, audit log, exports.
          Can never change or remove the owner.
- member  uses the product. Sees who is in the team.

API keys get *scopes*, which are a subset of the permissions below (`API_KEY_SCOPES`).
So one check works for both: `caller.can(Permission.JOBS_READ)`.

Products add their own permissions (e.g. `documents:write`) here and to the role sets.
"""

from enum import StrEnum


class Permission(StrEnum):
    """Something a caller may be allowed to do in a workspace."""

    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    ORG_EXPORT = "org:export"
    OWNERSHIP_TRANSFER = "ownership:transfer"
    MEMBERS_READ = "members:read"
    MEMBERS_INVITE = "members:invite"
    MEMBERS_MANAGE = "members:manage"
    API_KEYS_MANAGE = "api_keys:manage"
    AUDIT_READ = "audit:read"
    JOBS_READ = "jobs:read"
    JOBS_WRITE = "jobs:write"


_MEMBER = frozenset(
    {
        Permission.MEMBERS_READ,
        Permission.JOBS_READ,
        Permission.JOBS_WRITE,
    }
)
_ADMIN = _MEMBER | {
    Permission.ORG_UPDATE,
    Permission.ORG_EXPORT,
    Permission.MEMBERS_INVITE,
    Permission.MEMBERS_MANAGE,
    Permission.API_KEYS_MANAGE,
    Permission.AUDIT_READ,
}
_OWNER = _ADMIN | {Permission.ORG_DELETE, Permission.OWNERSHIP_TRANSFER}

# Keyed by the role's value ("owner", "admin", "member"), see app.models.organization.Role.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "owner": _OWNER,
    "admin": _ADMIN,
    "member": _MEMBER,
}

# What an API key may be allowed to do. Team, billing and key management stay
# with signed-in people, so a leaked key can never lock the owner out.
API_KEY_SCOPES: frozenset[Permission] = frozenset({Permission.JOBS_READ, Permission.JOBS_WRITE})


def role_permissions(role: str) -> frozenset[Permission]:
    """Permissions of a role (empty for an unknown role)."""
    return ROLE_PERMISSIONS.get(role, frozenset())
