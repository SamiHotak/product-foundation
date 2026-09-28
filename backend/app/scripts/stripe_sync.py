"""Create / update the Stripe products, prices and portal settings from app/core/plans.py.

    make stripe-sync            (inside Docker: python -m app.scripts.stripe_sync)
    make stripe-sync ARGS=--dry-run     only show what would change

Safe to run many times. What it does, for every public, self-service paid plan:
- product  "<STRIPE_PREFIX>_<plan id>"         name and description from plans.py
- prices   lookup keys "<prefix>_<plan>_month" and "<prefix>_<plan>_year"
           Stripe prices can't be edited. When a price in plans.py changed, a NEW price
           takes over the lookup key and the old one is archived. Existing subscribers keep
           their old price until they change plan (that is how Stripe works).
- portal   a customer portal configuration (card, invoices, VAT ID, switch plan, cancel at
           period end), marked with metadata app=<prefix> so checkout finds it.

It refuses live keys (sk_live_...) unless you add --live, so you can't change real prices
by accident.
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import stripe

from app.core.config import Settings, get_settings
from app.core.plans import (
    CURRENCY,
    DEFAULT_CATALOG,
    PRICES_INCLUDE_VAT,
    Interval,
    PlanCatalog,
    PlanDefinition,
)
from app.services.stripe_gateway import app_of, lookup_key, product_id

INTERVALS: tuple[Interval, ...] = ("month", "year")


@dataclass
class SyncReport:
    """What the sync did (or would do with --dry-run)."""

    changes: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    def change(self, text: str) -> None:
        """Something was (or would be) created or changed."""
        self.changes.append(text)

    def same(self, text: str) -> None:
        """Already correct."""
        self.unchanged.append(text)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class StripeSync:
    """Brings one Stripe account in line with plans.py. `client` is a stripe.StripeClient."""

    def __init__(
        self,
        client: Any,
        catalog: PlanCatalog,
        *,
        prefix: str,
        app_name: str,
        app_url: str,
        dry_run: bool = False,
    ) -> None:
        self._c = client.v1
        self._catalog = catalog
        self._prefix = prefix
        self._app_name = app_name
        self._app_url = app_url
        self._dry = dry_run
        self.report = SyncReport()

    def run(self) -> SyncReport:
        """Sync every sellable plan, then the portal configuration."""
        portal_products: list[dict[str, Any]] = []
        for plan in self._catalog.plans:
            if self._catalog.sellable(plan.id) is None:
                continue
            prod = self._product(plan)
            prices = [
                price_id
                for interval in INTERVALS
                if (price_id := self._price(plan, prod, interval)) is not None
            ]
            if prices:
                portal_products.append({"product": prod, "prices": prices})
        self._portal(portal_products)
        return self.report

    def _product(self, plan: PlanDefinition) -> str:
        pid = product_id(self._prefix, plan.id)
        wanted = {
            "name": f"{self._app_name} {plan.name}",
            "description": plan.description,
            "metadata": {"app": self._prefix, "plan_id": plan.id},
        }
        try:
            current = self._c.products.retrieve(pid)
        except stripe.InvalidRequestError as exc:
            if exc.code != "resource_missing":
                raise
            current = None
        if current is None:
            self.report.change(f"create product {pid}")
            if not self._dry:
                self._c.products.create(params={"id": pid, **wanted})
            return pid
        if (
            _get(current, "name") != wanted["name"]
            or _get(current, "description") != wanted["description"]
            or not _get(current, "active")
        ):
            self.report.change(f"update product {pid}")
            if not self._dry:
                self._c.products.update(pid, params={**wanted, "active": True})
        else:
            self.report.same(f"product {pid}")
        return pid

    def _price(self, plan: PlanDefinition, prod: str, interval: Interval) -> str | None:
        amount = PlanCatalog.price(plan, interval)
        if amount <= 0:
            return None  # e.g. no yearly option
        key = lookup_key(self._prefix, plan.id, interval)
        tax = "inclusive" if PRICES_INCLUDE_VAT else "exclusive"
        found = self._c.prices.list(params={"lookup_keys": [key], "limit": 1}).data
        current = found[0] if found else None
        if (
            current is not None
            and _get(current, "active")
            and _get(current, "unit_amount") == amount
            and _get(current, "currency") == CURRENCY
            and _get(_get(current, "recurring"), "interval") == interval
            and _get(current, "tax_behavior") == tax
            and _get(current, "product") == prod
        ):
            self.report.same(f"price {key} ({amount / 100:.2f} {CURRENCY})")
            return str(_get(current, "id"))
        self.report.change(f"create price {key} = {amount / 100:.2f} {CURRENCY} per {interval}")
        if self._dry:
            return f"(new {key})"
        created = self._c.prices.create(
            params={
                "product": prod,
                "currency": CURRENCY,
                "unit_amount": amount,
                "recurring": {"interval": interval},
                "tax_behavior": tax,
                "lookup_key": key,
                "transfer_lookup_key": True,
                "nickname": f"{plan.name} ({interval}ly)",
                "metadata": {"app": self._prefix, "plan_id": plan.id, "interval": interval},
            }
        )
        if current is not None and _get(current, "active"):
            self.report.change(f"archive old price {_get(current, 'id')}")
            self._c.prices.update(str(_get(current, "id")), params={"active": False})
        return str(_get(created, "id"))

    def _portal(self, products: list[dict[str, Any]]) -> None:
        params: dict[str, Any] = {
            "business_profile": {"headline": f"{self._app_name}: manage your plan"},
            "features": {
                "customer_update": {
                    "enabled": True,
                    "allowed_updates": ["email", "address", "name", "tax_id"],
                },
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                "subscription_update": {
                    "enabled": bool(products),
                    "default_allowed_updates": ["price"] if products else [],
                    "proration_behavior": "create_prorations",
                    "products": products,
                },
            },
            "metadata": {"app": self._prefix},
        }
        if self._app_url.startswith("https://"):  # Stripe wants public addresses here
            params["business_profile"]["privacy_policy_url"] = f"{self._app_url}/legal/privacy"
            params["business_profile"]["terms_of_service_url"] = f"{self._app_url}/legal/terms"
        configs = self._c.billing_portal.configurations.list(params={"active": True, "limit": 100})
        mine = [c for c in configs.data if app_of(_get(c, "metadata")) == self._prefix]
        if self._dry:
            self.report.change("update portal settings" if mine else "create portal settings")
            return
        if mine:
            self.report.change(f"update portal settings {_get(mine[0], 'id')}")
            self._c.billing_portal.configurations.update(str(_get(mine[0], "id")), params=params)
        else:
            self.report.change("create portal settings")
            self._c.billing_portal.configurations.create(params=params)


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    """Entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Sync plans.py to Stripe.")
    parser.add_argument("--dry-run", action="store_true", help="only show what would change")
    parser.add_argument("--live", action="store_true", help="allow a live (sk_live_) key")
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    if not settings.stripe_secret_key:
        print("STRIPE_SECRET_KEY is empty. Put your test key into backend/.env first.")
        return 1
    key = settings.stripe_secret_key.get_secret_value()
    if key.startswith("sk_live_") and not args.live:
        print("This is a LIVE key. Run again with --live if you really want to change prices.")
        return 1
    client = stripe.StripeClient(key)
    sync = StripeSync(
        client,
        DEFAULT_CATALOG,
        prefix=settings.stripe_prefix,
        app_name=settings.app_name,
        app_url=settings.app_url,
        dry_run=args.dry_run,
    )
    report = sync.run()
    mode = "LIVE" if key.startswith("sk_live_") else "test mode"
    print(f"Stripe ({mode}), prefix {settings.stripe_prefix!r}:")
    for line in report.unchanged:
        print(f"  ok       {line}")
    for line in report.changes:
        print(f"  {'would' if args.dry_run else 'done '}    {line}")
    if not report.changes:
        print("  Nothing to change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
