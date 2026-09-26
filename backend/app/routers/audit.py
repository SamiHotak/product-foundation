"""Audit log of the active workspace (owners and admins)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.permissions import Permission
from app.routers.deps import Audit, require
from app.schemas.audit import AuditPage
from app.schemas.errors import error_responses
from app.services.organizations import OrgContext

router = APIRouter(prefix="/organizations/current/audit-log", tags=["audit log"])


@router.get(
    "",
    response_model=AuditPage,
    responses=error_responses(400, 401, 403),
    summary="Audit log",
)
async def list_audit_log(
    ctx: Annotated[OrgContext, require(Permission.AUDIT_READ)],
    audit: Audit,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[str | None, Query(max_length=200, description="next_cursor")] = None,
    action: Annotated[
        str | None, Query(max_length=64, pattern=r"^[a-z_.]+$", description='e.g. "member"')
    ] = None,
) -> AuditPage:
    """Newest first. Filter by area ("member", "invite", "api_key", ...) or exact action."""
    items, next_cursor = await audit.list_for_org(
        ctx.organization.id, limit=limit, before=before, action_prefix=action
    )
    return AuditPage(items=items, next_cursor=next_cursor)
