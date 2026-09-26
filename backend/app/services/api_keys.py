"""API keys: create, list, revoke, and authenticate requests to the public REST API.

A key looks like "pf_<43 random characters>" (256 bits). Only its SHA-256 hash is stored;
random keys this long don't need a slow hash like passwords do. Requests send it as
`Authorization: Bearer pf_...`. Each key is limited to N requests per minute.
"""

import uuid
from datetime import timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError, RateLimitedError
from app.core.logging import get_logger
from app.core.permissions import API_KEY_SCOPES, Permission
from app.core.rate_limit import RateLimiter
from app.core.security import hash_token, new_token
from app.models.api_key import ApiKey
from app.models.user import User
from app.repositories.api_keys import ApiKeyRepository
from app.repositories.organizations import OrganizationRepository
from app.schemas.api_keys import ApiKeyCreated, ApiKeyRead
from app.services.audit import AuditAction, AuditService
from app.services.organizations import Caller, OrgContext
from app.services.sessions import utcnow

logger = get_logger(__name__)

# Writing last_used_at on every request would be a database write per call.
TOUCH_EVERY = timedelta(minutes=1)
PREFIX_CHARS = 8  # random characters shown after "pf_" to tell keys apart


class InvalidApiKeyError(AppError):
    """Missing, wrong, revoked or expired API key."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_api_key"


def api_key_read(key: ApiKey, creator: User | None) -> ApiKeyRead:
    """The API shape of a key (never the secret)."""
    now = utcnow()
    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=sorted(key.scopes),
        created_by_name=creator.name if creator else None,
        created_at=key.created_at,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        expired=key.expires_at is not None and key.expires_at <= now,
    )


class ApiKeyService:
    """API key operations. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        limiter: RateLimiter,
        audit: AuditService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._limiter = limiter
        self._audit = audit
        self._keys = ApiKeyRepository(db)

    def _new_secret(self) -> str:
        return f"{self._settings.api_key_prefix}_{new_token()}"

    async def create(
        self, ctx: OrgContext, *, name: str, scopes: list[str], expires_in_days: int | None
    ) -> ApiKeyCreated:
        """Create a key. The response is the only time the secret is visible."""
        ctx.require(Permission.API_KEYS_MANAGE)
        wanted = {Permission(s) for s in scopes}
        assert wanted <= API_KEY_SCOPES  # the schema already rejects anything else
        secret = self._new_secret()
        key = ApiKey(
            organization_id=ctx.organization.id,
            name=name.strip(),
            prefix=secret[: len(self._settings.api_key_prefix) + 1 + PREFIX_CHARS],
            key_hash=hash_token(secret),
            scopes=sorted(p.value for p in wanted),
            created_by_id=ctx.user.id,
            expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
        )
        await self._keys.add(key)
        await self._audit.record(
            AuditAction.API_KEY_CREATED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="api_key",
            target_id=key.id,
            details={"name": key.name, "prefix": key.prefix, "scopes": key.scopes},
        )
        await self._db.commit()
        logger.info("api_key_created", api_key_id=str(key.id))
        return ApiKeyCreated(**api_key_read(key, ctx.user).model_dump(), key=secret)

    async def list_keys(self, ctx: OrgContext) -> list[ApiKeyRead]:
        """The workspace's keys (not revoked)."""
        ctx.require(Permission.API_KEYS_MANAGE)
        return [api_key_read(k, u) for k, u in await self._keys.list_active(ctx.organization.id)]

    async def revoke(self, ctx: OrgContext, key_id: uuid.UUID) -> None:
        """Stop a key from working. Takes effect on its next request."""
        ctx.require(Permission.API_KEYS_MANAGE)
        key = await self._keys.get(key_id, organization_id=ctx.organization.id)
        if key is None or key.revoked_at is not None:
            raise NotFoundError("This API key does not exist.")
        key.revoked_at = utcnow()
        await self._audit.record(
            AuditAction.API_KEY_REVOKED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="api_key",
            target_id=key.id,
            details={"name": key.name, "prefix": key.prefix},
        )
        await self._db.commit()

    async def authenticate(self, secret: str) -> Caller:
        """Turn a Bearer key into a caller, or raise 401 (and 429 when over the limit)."""
        prefix = self._settings.api_key_prefix + "_"
        if not secret.startswith(prefix) or len(secret) > 200:
            raise InvalidApiKeyError("The API key is missing or not valid.")
        now = utcnow()
        key = await self._keys.get_by_hash(hash_token(secret))
        if key is None or not key.is_usable(now):
            raise InvalidApiKeyError("The API key is not valid, was revoked, or has expired.")
        wait = await self._limiter.hit(
            f"api-key:{key.id}",
            limit=self._settings.api_key_requests_per_minute,
            window_seconds=60,
        )
        if wait is not None:
            raise RateLimitedError("Too many requests with this API key.", retry_after=wait)
        org = await OrganizationRepository(self._db).get(key.organization_id)
        assert org is not None  # the key would have been deleted with the workspace
        if key.last_used_at is None or now - key.last_used_at > TOUCH_EVERY:
            key.last_used_at = now
            await self._db.commit()
        permissions = frozenset(Permission(s) for s in key.scopes) & API_KEY_SCOPES
        return Caller(organization=org, permissions=permissions, api_key=key)
