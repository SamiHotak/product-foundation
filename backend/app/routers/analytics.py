"""Cookie-less website analytics: the browser posts page views here (see services/analytics)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.routers.deps import AppSettings, client_ip
from app.schemas.analytics import AnalyticsEvent
from app.services.analytics import AnalyticsSender, Visitor, build_analytics_sender

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_analytics_sender(settings: AppSettings) -> AnalyticsSender | None:
    """The configured provider, or None when analytics is off (overridden in tests)."""
    return build_analytics_sender(settings)


@router.post(
    "/event",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Record a page view",
)
async def record_event(
    event: AnalyticsEvent,
    request: Request,
    background: BackgroundTasks,
    settings: AppSettings,
    sender: Annotated[AnalyticsSender | None, Depends(get_analytics_sender)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> Response:
    """Public. Always answers 204; the event is forwarded after the response (if on)."""
    user_agent = request.headers.get("user-agent", "")
    if sender is None or not user_agent:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    ip = client_ip(request)
    over_limit = await limiter.hit(
        f"analytics-ip:{ip}",
        limit=settings.analytics_events_per_minute_per_ip,
        window_seconds=60,
    )
    if over_limit is None:
        background.add_task(sender.send, event, Visitor(ip=ip, user_agent=user_agent[:500]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
