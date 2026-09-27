"""Billing endpoints. Phase 3B: the public plan list for the pricing page."""

from fastapi import APIRouter, Response

from app.schemas.billing import PlansResponse
from app.services.billing import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=PlansResponse, summary="Plans and prices")
async def list_plans(response: Response) -> PlansResponse:
    """Public: the plans shown on the website. No sign-in needed."""
    # Plans only change with a deploy; let browsers and proxies keep them for 5 minutes.
    response.headers["Cache-Control"] = "public, max-age=300"
    return BillingService().public_plans()
