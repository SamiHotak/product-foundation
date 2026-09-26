"""Auth and organization schemas (the API contract)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.permissions import Permission
from app.models.organization import Role

PASSWORD_MIN = 10
PASSWORD_MAX = 128


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignupRequest(_Strict):
    """Create an account. A verification email is sent."""

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    # Not stripped: spaces are allowed in passwords.
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class LoginRequest(_Strict):
    """Email + password."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class EmailRequest(_Strict):
    """Just an email (resend verification, forgot password)."""

    email: EmailStr


class TokenRequest(_Strict):
    """A token from an email link."""

    token: str = Field(min_length=20, max_length=200)


class ResetPasswordRequest(_Strict):
    """Token from the reset email + the new password."""

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class MessageResponse(BaseModel):
    """A short message for people."""

    message: str


class AuthProviders(BaseModel):
    """Which sign-in options are switched on."""

    password: bool = True
    google: bool


class UserRead(BaseModel):
    """The signed-in user."""

    id: uuid.UUID
    email: str
    name: str
    email_verified: bool
    has_password: bool
    google_linked: bool
    created_at: datetime
    deletion_scheduled_at: datetime | None = Field(
        default=None, description="Set when the account will be deleted (can be cancelled)."
    )


class OrganizationRead(BaseModel):
    """An organization and the current user's role in it."""

    id: uuid.UUID
    name: str
    role: Role
    deletion_scheduled_at: datetime | None = Field(
        default=None, description="Set when the workspace will be deleted (can be cancelled)."
    )


class MeResponse(BaseModel):
    """Everything the app needs after sign-in."""

    user: UserRead
    organizations: list[OrganizationRead]
    active_organization_id: uuid.UUID
    permissions: list[Permission] = Field(
        description="What you may do in the active workspace (the UI hides everything else)."
    )


class OrganizationCreate(_Strict):
    """Create a workspace."""

    name: str = Field(min_length=1, max_length=80)


class SwitchOrganization(_Strict):
    """Switch the active workspace for this browser."""

    organization_id: uuid.UUID
