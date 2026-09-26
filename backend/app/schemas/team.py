"""Team schemas: workspace settings, members, invites, ownership (the API contract)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.organization import Role

# Roles you can give with an invite or a role change. Ownership moves only with a transfer.
AssignableRole = Literal["admin", "member"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizationUpdate(_Strict):
    """Rename the active workspace."""

    name: str = Field(min_length=1, max_length=80)


class MemberRead(BaseModel):
    """A person in the workspace."""

    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    joined_at: datetime
    is_you: bool


class MemberList(BaseModel):
    """Owner first, then admins, then members."""

    items: list[MemberRead]


class MemberUpdate(_Strict):
    """Change someone's role."""

    role: AssignableRole


class TransferOwnership(_Strict):
    """Make another member the owner. You become an admin."""

    user_id: uuid.UUID


class InviteCreate(_Strict):
    """Invite someone by email."""

    email: EmailStr
    role: AssignableRole = "member"


class InviteRead(BaseModel):
    """An open invite."""

    id: uuid.UUID
    email: str
    role: Role
    invited_by_name: str | None
    created_at: datetime
    expires_at: datetime


class InviteList(BaseModel):
    """Open invites, newest first."""

    items: list[InviteRead]


class InviteTokenRequest(_Strict):
    """The token from an invite link."""

    token: str = Field(min_length=20, max_length=200)


class InvitePreview(BaseModel):
    """What the invite page shows before accepting."""

    organization_name: str
    invited_by_name: str | None
    email: str
    role: Role
    expires_at: datetime
    account_exists: bool = Field(
        description="True: sign in to accept. False: create an account with the invite."
    )


class InviteSignup(_Strict):
    """Create an account from an invite link (the link proves the email address)."""

    token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
