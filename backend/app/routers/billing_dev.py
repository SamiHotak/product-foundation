"""Pretend checkout and portal for local development and e2e tests.

Only mounted when BILLING_DEV_TOOLS=true (docker-compose.dev.yml). The settings refuse
that in production. The pages change the subscription through the same code a Stripe
webhook uses, so the rest of the app can't tell the difference.
"""

import uuid
from html import escape
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.errors import AppError
from app.core.permissions import Permission
from app.core.security import unsign_data
from app.routers.deps import AppSettings, Billing, Catalog, require
from app.schemas.billing import DevSetPlan
from app.services.organizations import OrgContext

router = APIRouter(prefix="/billing/dev", tags=["billing (dev only)"], include_in_schema=False)

Owner = Annotated[OrgContext, require(Permission.BILLING_MANAGE)]


class InvalidDevLinkError(AppError):
    """The pretend checkout/portal link was changed or is older than an hour."""

    code = "invalid_link"


def _data(token: str, settings: AppSettings) -> dict[str, Any]:
    data = unsign_data(token, settings.secret_key.get_secret_value())
    if data is None:
        raise InvalidDevLinkError("This link is not valid any more. Start again from the app.")
    return data


async def _form(request: Request) -> tuple[str, str]:
    """token and action from the page's form (plain urlencoded, no extra library needed)."""
    fields = parse_qs((await request.body()).decode("utf-8", "replace"))
    return fields.get("token", [""])[0], fields.get("action", [""])[0]


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<link rel='icon' href='data:,'>"  # no /favicon.ico request (a 404 in the console)
        f"<title>{escape(title)}</title></head>"
        "<body style='font-family:system-ui,sans-serif;background:#f3f5f8;color:#1b2233;"
        "margin:0;padding:32px 16px'><main style='max-width:460px;margin:0 auto;"
        "background:#fff;border:1px solid #e3e7ee;border-radius:10px;padding:24px'>"
        "<p style='margin:0 0 12px;font-size:12px;font-weight:600;color:#9a5b00'>"
        "TEST MODE: no real payment. This page exists only in local development.</p>"
        f"<h1 style='font-size:20px;margin:0 0 12px'>{escape(title)}</h1>"
        f"{body}</main></body></html>"
    )


def _button(token: str, action: str, label: str, primary: bool = False) -> str:
    style = (
        "background:#244ba6;color:#fff;border:0"
        if primary
        else "background:#fff;color:#1b2233;border:1px solid #c9d0db"
    )
    return (
        "<form method='post' style='display:inline-block;margin:0 8px 8px 0'>"
        f"<input type='hidden' name='token' value='{escape(token)}'>"
        f"<input type='hidden' name='action' value='{escape(action)}'>"
        f"<button type='submit' style='{style};border-radius:6px;padding:9px 14px;"
        f"font-size:14px;font-weight:600;cursor:pointer'>{escape(label)}</button></form>"
    )


@router.get("/checkout")
async def dev_checkout_page(
    token: Annotated[str, Query()], settings: AppSettings, catalog: Catalog
) -> HTMLResponse:
    """The pretend Stripe Checkout."""
    data = _data(token, settings)
    plan = catalog.get(str(data["plan_id"]))
    assert plan is not None
    interval = str(data["interval"])
    price = plan.price_monthly if interval == "month" else plan.price_yearly
    trial = int(data["trial_days"])
    lines = f"<p>{escape(plan.name)}: {price / 100:.2f} € per {escape(interval)}.</p>"
    if trial:
        lines += f"<p>Free for {trial} days, then charged.</p>"
    return _page(
        f"Checkout: {plan.name}",
        lines
        + _button(token, "pay", "Pay (pretend)", primary=True)
        + _button(token, "cancel", "Back without paying"),
    )


@router.post("/checkout")
async def dev_checkout_submit(
    request: Request, settings: AppSettings, billing: Billing
) -> RedirectResponse:
    """Button "Pay": the subscription starts (trial if the plan has one), then back to the app."""
    token, action = await _form(request)
    data = _data(token, settings)
    if action != "pay":
        return RedirectResponse(str(data["cancel_url"]), status_code=status.HTTP_303_SEE_OTHER)
    trial = int(data["trial_days"])
    await billing.dev_apply(
        uuid.UUID(str(data["organization_id"])),
        str(data["customer_id"]),
        plan_id=str(data["plan_id"]),
        status="trialing" if trial else "active",
        interval=str(data["interval"]),
        trial_days=trial,
    )
    return RedirectResponse(str(data["success_url"]), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/portal")
async def dev_portal_page(
    token: Annotated[str, Query()], settings: AppSettings, billing: Billing, catalog: Catalog
) -> HTMLResponse:
    """The pretend customer portal."""
    data = _data(token, settings)
    sub = await billing.dev_state(str(data["customer_id"]))
    back = (
        f"<p style='margin-top:16px'><a href='{escape(str(data['return_url']))}'>"
        "Back to the app</a></p>"
    )
    if sub is None or not sub.is_paid:
        return _page("Billing portal", "<p>No paid plan.</p>" + back)
    plan = catalog.get(sub.plan_id)
    state = "ends at the end of the period" if sub.cancel_at_period_end else "renews"
    name = plan.name if plan else str(sub.plan_id)
    body = f"<p>Plan: {escape(name)} ({escape(str(sub.status))}, {state}).</p>"
    if sub.cancel_at_period_end:
        body += _button(token, "resume", "Keep my plan")
    else:
        body += _button(token, "cancel_at_period_end", "Cancel at period end")
    body += _button(token, "cancel_now", "Cancel now")
    body += _button(token, "payment_failed", "Simulate a failed payment")
    return _page("Billing portal", body + back)


@router.post("/portal")
async def dev_portal_submit(
    request: Request, settings: AppSettings, billing: Billing
) -> RedirectResponse:
    """Apply a portal action, then show the portal again."""
    token, action = await _form(request)
    data = _data(token, settings)
    customer = str(data["customer_id"])
    sub = await billing.dev_state(customer)
    if sub is not None and sub.is_paid:
        common: dict[str, Any] = {"plan_id": sub.plan_id, "interval": sub.interval}
        if action == "cancel_now":
            await billing.dev_apply(sub.organization_id, customer, status="canceled", **common)
        elif action == "payment_failed":
            await billing.dev_payment_failed(sub.organization_id, customer)
        elif action in {"cancel_at_period_end", "resume"}:
            await billing.dev_apply(
                sub.organization_id,
                customer,
                status=str(sub.status),
                cancel_at_period_end=action == "cancel_at_period_end",
                **common,
            )
    return RedirectResponse(
        f"{settings.api_prefix}/billing/dev/portal?token={token}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/set-plan", status_code=status.HTTP_204_NO_CONTENT)
async def dev_set_plan(data: DevSetPlan, ctx: Owner, billing: Billing) -> Response:
    """Put the active workspace on a plan without paying (e2e tests, trying limits)."""
    await billing.dev_set_plan(ctx, data.plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
