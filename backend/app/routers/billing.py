"""Billing endpoints: plans (public), the workspace's plan and usage, checkout, portal,
and the Stripe webhook."""

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from app.core.permissions import Permission
from app.routers.deps import Billing, Catalog, OrgCtx, require
from app.schemas.billing import BillingOverview, CheckoutCreate, PlansResponse, RedirectResponse
from app.schemas.errors import error_responses
from app.services.billing import public_plans
from app.services.organizations import OrgContext

router = APIRouter(prefix="/billing", tags=["billing"])

Owner = Annotated[OrgContext, require(Permission.BILLING_MANAGE)]


@router.get("/plans", response_model=PlansResponse, summary="Plans and prices")
async def list_plans(response: Response, catalog: Catalog) -> PlansResponse:
    """Public: the plans shown on the website. No sign-in needed."""
    # Plans only change with a deploy; let browsers and proxies keep them for 5 minutes.
    response.headers["Cache-Control"] = "public, max-age=300"
    return public_plans(catalog.plans)


@router.get(
    "/current",
    response_model=BillingOverview,
    responses=error_responses(401),
    summary="Plan and usage of the active workspace",
)
async def get_billing(ctx: OrgCtx, billing: Billing) -> BillingOverview:
    """Every member may see the plan and usage. Only the owner can change them."""
    return await billing.overview(ctx)


@router.post(
    "/checkout",
    response_model=RedirectResponse,
    responses=error_responses(400, 401, 403, 409, 503),
    summary="Start a checkout",
)
async def start_checkout(data: CheckoutCreate, ctx: Owner, billing: Billing) -> RedirectResponse:
    """Owner only. Returns the Stripe Checkout address; send the browser there."""
    return await billing.start_checkout(ctx, data.plan_id, data.interval)


@router.post(
    "/portal",
    response_model=RedirectResponse,
    responses=error_responses(401, 403, 404, 503),
    summary="Open the customer portal",
)
async def open_portal(ctx: Owner, billing: Billing) -> RedirectResponse:
    """Owner only. Stripe's portal: payment method, invoices, VAT ID, change plan, cancel."""
    return await billing.open_portal(ctx)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    billing: Billing,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    """Stripe calls this. The signature proves it is Stripe; the body must stay untouched."""
    await billing.handle_webhook(await request.body(), stripe_signature)
    return {"received": True}
