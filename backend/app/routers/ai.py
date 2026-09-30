"""AI features of the active workspace (signed-in people)."""

from fastapi import APIRouter, Request, status

from app.core.errors import RateLimitedError
from app.routers.deps import Ai, AppSettings, Limiter, OrgCtx, client_ip
from app.schemas.ai import AiStatus, SummaryCreate
from app.schemas.errors import error_responses
from app.schemas.jobs import JobRead

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AiStatus, responses=error_responses(401), summary="AI status")
async def ai_status(ctx: OrgCtx, ai: Ai) -> AiStatus:
    """Whether AI can be used right now (set up, not paused) and by whom."""
    return await ai.status(ctx)


@router.post(
    "/summaries",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(401, 402, 403, 429, 503),
    summary="Summarize a text",
)
async def create_summary(
    data: SummaryCreate,
    ctx: OrgCtx,
    ai: Ai,
    request: Request,
    limiter: Limiter,
    settings: AppSettings,
) -> JobRead:
    """Starts a background job. Follow it with `GET /jobs/{id}`; the summary is its result."""
    if ctx.user.is_demo:  # one shared workspace: each visitor gets a small share
        wait = await limiter.hit(
            f"demo-ai:{client_ip(request)}",
            limit=settings.demo_ai_per_hour,
            window_seconds=3600,
        )
        if wait is not None:
            raise RateLimitedError(
                "The demo allows a few AI summaries per hour. Create your own free account "
                "to try more.",
                retry_after=wait,
            )
    job = await ai.start_summary(ctx, data.text)
    return JobRead.model_validate(job)
