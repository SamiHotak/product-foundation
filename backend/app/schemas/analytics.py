"""Website analytics event (sent by the browser, forwarded to Plausible or Umami)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

EventName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
PropKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,29}$")]
PropValue = Annotated[str, StringConstraints(max_length=100)]


class AnalyticsEvent(BaseModel):
    """One page view or custom event. Holds no personal data by design."""

    name: EventName = Field(default="pageview", description='"pageview" or a custom event.')
    path: Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"^/")] = Field(
        description="Page path only. Query strings and #fragments are removed on the server too."
    )
    referrer: Annotated[str, StringConstraints(max_length=500)] | None = Field(
        default=None, description="The page the visitor came from. Only its origin is kept."
    )
    props: dict[PropKey, PropValue] = Field(default_factory=dict, max_length=10)
