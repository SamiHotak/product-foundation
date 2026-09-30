"""What special sessions may do. The ONE place to read or change these rules.

Two kinds of sessions are restricted, checked centrally for every signed-in request
(app/routers/deps.py). Both use ALLOW lists, so a new endpoint is blocked for them until
someone adds it here on purpose (safe by default):

- The demo user ("Try the demo") may only READ, plus the few harmless actions in
  DEMO_ALLOWED. Everyone shares one demo workspace, so nothing a visitor does may
  change what the next visitor sees (or cost us money).
- An admin viewing the app as a user (impersonation, for support) may READ (except
  DATA_DOWNLOADS: exports of personal data), plus the actions in IMPERSONATION_ALLOWED.
  They can't invite people, change members, create keys, pay, or change the account:
  otherwise support access could outlive the support session (e.g. inviting yourself).

Paths are written WITHOUT the API prefix ("/api"), so changing API_PREFIX can't open them.
"""

import re

from fastapi import status

from app.core.errors import AppError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_UUID = r"[0-9a-fA-F-]{36}"

Rules = tuple[tuple[str, re.Pattern[str]], ...]

# Needed by every restricted session: sign out, switch workspace, stop viewing as a user.
_ALWAYS: Rules = (
    ("POST", re.compile(r"^/auth/logout$")),
    ("PUT", re.compile(r"^/auth/session/organization$")),
    ("POST", re.compile(r"^/admin/impersonation/stop$")),
)

# (method, path) the demo user may use besides reading.
DEMO_ALLOWED: Rules = (
    *_ALWAYS,
    ("POST", re.compile(r"^/jobs/example$")),
    ("POST", re.compile(r"^/ai/summaries$")),
    ("POST", re.compile(rf"^/files/{_UUID}/download$")),
)

# (method, path) an admin viewing the app as a user may use besides reading.
IMPERSONATION_ALLOWED: Rules = (
    *_ALWAYS,
    ("POST", re.compile(r"^/jobs/example$")),
    ("POST", re.compile(r"^/ai/summaries$")),
    ("POST", re.compile(rf"^/files/{_UUID}/download$")),
)

# Reads an admin viewing as a user may NOT make: downloads of personal data exports.
DATA_DOWNLOADS: Rules = (("GET", re.compile(r"^/exports/[^/]+/download$")),)


class DemoReadOnlyError(AppError):
    """The demo user tried to change something."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "demo_read_only"


class ImpersonationBlockedError(AppError):
    """An admin viewing as a user tried something only the user may do."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "not_while_impersonating"


def _matches(rules: Rules, method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in rules)


def _allowed(rules: Rules, method: str, path: str | None) -> bool:
    if path is None:  # not an API path: only reading
        return method in SAFE_METHODS
    return method in SAFE_METHODS or _matches(rules, method, path)


def check_session_restrictions(
    method: str, path: str, *, api_prefix: str, is_demo: bool, impersonating: bool
) -> None:
    """Raise if this kind of session may not make this request."""
    method = method.upper()
    prefix = api_prefix.rstrip("/")
    local: str | None
    if not prefix:
        local = path
    elif path.startswith(prefix + "/"):
        local = path[len(prefix) :]
    else:
        local = None
    if is_demo and not _allowed(DEMO_ALLOWED, method, local):
        raise DemoReadOnlyError(
            "This is a shared demo, so you can look around but not change things. "
            "Create your own free account to try everything."
        )
    if impersonating and (
        not _allowed(IMPERSONATION_ALLOWED, method, local)
        or (local is not None and _matches(DATA_DOWNLOADS, method, local))
    ):
        raise ImpersonationBlockedError(
            "Not possible while you view the app as someone else: only the user can do "
            "this. Stop viewing as them first."
        )
