"""The signed-in person's own profile, password and onboarding (the API contract)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import PASSWORD_MAX, PASSWORD_MIN


class ProfileUpdate(BaseModel):
    """Change your display name. (Changing the email address needs a new verification flow.)"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)


class PasswordChange(BaseModel):
    """Change (or, for Google-only accounts, set) your password."""

    # Not stripped: spaces are allowed in passwords.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    current_password: str | None = Field(
        default=None,
        max_length=PASSWORD_MAX,
        description="Required when the account already has a password.",
    )
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


# The steps the foundation knows. Products add theirs here and in services/onboarding.py.
OnboardingStepKey = Literal["verify_email", "invite_teammate", "create_api_key", "run_job"]


class OnboardingStep(BaseModel):
    """One "Get started" step and whether it is done in the active workspace."""

    key: OnboardingStepKey
    done: bool


class OnboardingStatus(BaseModel):
    """The checklist for you in the active workspace. Texts and links live in the frontend."""

    steps: list[OnboardingStep]
    dismissed: bool = Field(description="You hid the checklist in this workspace.")
