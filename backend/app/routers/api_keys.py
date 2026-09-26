"""API keys of the active workspace (owners and admins)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Response, status

from app.core.permissions import Permission
from app.routers.deps import ApiKeys, require
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyList
from app.schemas.errors import error_responses
from app.services.organizations import OrgContext

router = APIRouter(prefix="/organizations/current/api-keys", tags=["api keys"])

CanManage = Annotated[OrgContext, require(Permission.API_KEYS_MANAGE)]


@router.get("", response_model=ApiKeyList, responses=error_responses(401, 403), summary="API keys")
async def list_api_keys(ctx: CanManage, keys: ApiKeys) -> ApiKeyList:
    """Active keys (secrets are never shown again)."""
    return ApiKeyList(items=await keys.list_keys(ctx))


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403),
    summary="Create an API key",
)
async def create_api_key(data: ApiKeyCreate, ctx: CanManage, keys: ApiKeys) -> ApiKeyCreated:
    """The response contains the key. It is shown only this once."""
    return await keys.create(
        ctx, name=data.name, scopes=list(data.scopes), expires_in_days=data.expires_in_days
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
    summary="Revoke an API key",
)
async def revoke_api_key(key_id: uuid.UUID, ctx: CanManage, keys: ApiKeys) -> Response:
    """The key stops working immediately."""
    await keys.revoke(ctx, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
