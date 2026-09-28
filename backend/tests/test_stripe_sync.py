"""`make stripe-sync` against a tiny in-memory Stripe (the real SDK, no network)."""

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.core.plans import DEFAULT_CATALOG, PlanCatalog
from app.scripts import stripe_sync
from app.scripts.stripe_sync import StripeSync


class MiniStripe(stripe.HTTPClient):
    """Just enough of Stripe for products, prices and portal configurations."""

    name = "mini"

    def __init__(self) -> None:
        super().__init__()
        self.products: dict[str, dict[str, Any]] = {}
        self.prices: dict[str, dict[str, Any]] = {}
        self.configs: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []

    @staticmethod
    def _flat(form: dict[str, list[str]]) -> dict[str, str]:
        return {k: v[0] for k, v in form.items()}

    def request(self, method: str, url: str, headers: Any, post_data: Any = None, **_: Any) -> Any:
        parts = urlsplit(url)
        path, query = parts.path, self._flat(parse_qs(parts.query))
        body = post_data.decode() if isinstance(post_data, bytes) else post_data or ""
        form = self._flat(parse_qs(body))
        status, payload = self._route(method.upper(), path, query, form)
        return json.dumps(payload), status, {}

    def _route(
        self, method: str, path: str, query: dict[str, str], form: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        seg = path.split("/")[2:]
        if seg[0] == "products":
            if method == "GET":
                found = self.products.get(seg[1])
                if not found:
                    return 404, {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "resource_missing",
                            "message": "x",
                        }
                    }
                return 200, found
            self.writes.append(f"{method} {path}")
            pid = form.get("id") or seg[1]
            product = self.products.setdefault(
                pid, {"id": pid, "object": "product", "active": True}
            )
            product.update({k: v for k, v in form.items() if "[" not in k and k != "id"})
            if "active" in form:
                product["active"] = form["active"] == "true"
            return 200, product
        if seg[0] == "prices":
            if method == "GET":
                key = query.get("lookup_keys[0]")
                matches = [p for p in self.prices.values() if p.get("lookup_key") == key]
                return 200, {
                    "object": "list",
                    "url": "/v1/prices",
                    "has_more": False,
                    "data": matches[:1],
                }
            self.writes.append(f"{method} {path}")
            if len(seg) > 1:  # update (archive)
                self.prices[seg[1]]["active"] = form.get("active") == "true"
                return 200, self.prices[seg[1]]
            if form.get("transfer_lookup_key") == "true":
                for old in self.prices.values():
                    if old.get("lookup_key") == form["lookup_key"]:
                        old["lookup_key"] = None
            price: dict[str, Any] = {
                "id": f"price_{len(self.prices) + 1}",
                "object": "price",
                "active": True,
                "product": form["product"],
                "currency": form["currency"],
                "unit_amount": int(form["unit_amount"]),
                "recurring": {"interval": form["recurring[interval]"]},
                "tax_behavior": form["tax_behavior"],
                "lookup_key": form["lookup_key"],
                "metadata": {"plan_id": form["metadata[plan_id]"], "app": form["metadata[app]"]},
            }
            self.prices[price["id"]] = price
            return 200, price
        if seg[:2] == ["billing_portal", "configurations"]:
            if method == "GET":
                return 200, {
                    "object": "list",
                    "url": "/v1/billing_portal/configurations",
                    "has_more": False,
                    "data": list(self.configs.values()),
                }
            self.writes.append(f"{method} {path}")
            cid = seg[2] if len(seg) > 2 else f"bpc_{len(self.configs) + 1}"
            config = self.configs.setdefault(
                cid, {"id": cid, "object": "billing_portal.configuration", "metadata": {}}
            )
            config["metadata"] = {"app": form["metadata[app]"]}
            config["products"] = sorted(
                v for k, v in form.items() if k.endswith("[prices][0]") or k.endswith("[prices][1]")
            )
            return 200, config
        raise AssertionError(f"unexpected call {method} {path}")

    def close(self) -> None:
        return None


def _sync(mini: MiniStripe, catalog: PlanCatalog = DEFAULT_CATALOG, **kw: Any) -> StripeSync:
    client = stripe.StripeClient("sk_test_1", http_client=mini)
    return StripeSync(
        client,
        catalog,
        prefix="foundation",
        app_name="Foundation",
        app_url="http://localhost:3000",
        **kw,
    )


def test_first_run_creates_everything_and_second_run_changes_nothing() -> None:
    mini = MiniStripe()
    report = _sync(mini).run()
    assert set(mini.products) == {"foundation_pro", "foundation_business"}  # free is not sold
    keys = sorted(p["lookup_key"] for p in mini.prices.values())
    assert keys == [
        "foundation_business_month",
        "foundation_business_year",
        "foundation_pro_month",
        "foundation_pro_year",
    ]
    pro_month = next(p for p in mini.prices.values() if p["lookup_key"] == "foundation_pro_month")
    assert (pro_month["unit_amount"], pro_month["currency"]) == (2900, "eur")
    assert pro_month["tax_behavior"] == "exclusive"  # plans.py: prices plus VAT
    assert [c["metadata"]["app"] for c in mini.configs.values()] == ["foundation"]
    assert len(mini.configs["bpc_1"]["products"]) == 4  # both plans, both intervals
    assert any("create price" in line for line in report.changes)

    mini.writes.clear()
    again = _sync(mini).run()
    assert [w for w in mini.writes if "configurations" not in w] == []
    assert not [c for c in again.changes if "portal" not in c]


def test_a_changed_price_gets_a_new_stripe_price_and_the_old_one_is_archived() -> None:
    from dataclasses import replace

    mini = MiniStripe()
    _sync(mini).run()
    old = next(p for p in mini.prices.values() if p["lookup_key"] == "foundation_pro_month")
    plans = tuple(
        replace(p, price_monthly=3900) if p.id == "pro" else p for p in DEFAULT_CATALOG.plans
    )
    report = _sync(mini, PlanCatalog(plans)).run()
    new = next(p for p in mini.prices.values() if p["lookup_key"] == "foundation_pro_month")
    assert new["id"] != old["id"] and new["unit_amount"] == 3900
    assert old["active"] is False and old["lookup_key"] is None
    assert any("archive old price" in line for line in report.changes)


def test_dry_run_writes_nothing() -> None:
    mini = MiniStripe()
    report = _sync(mini, dry_run=True).run()
    assert mini.writes == []
    assert any("create product foundation_pro" in line for line in report.changes)


def _settings(key: str | None) -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        stripe_secret_key=SecretStr(key) if key else None,
    )


def test_main_refuses_missing_and_live_keys(capsys: pytest.CaptureFixture[str]) -> None:
    assert stripe_sync.main([], _settings(None)) == 1
    assert "STRIPE_SECRET_KEY is empty" in capsys.readouterr().out
    assert stripe_sync.main([], _settings("sk_live_abc")) == 1
    assert "LIVE key" in capsys.readouterr().out


def test_main_prints_a_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mini = MiniStripe()
    real_client = stripe.StripeClient
    monkeypatch.setattr(
        stripe,
        "StripeClient",
        lambda key: real_client(key, http_client=mini),
    )
    assert stripe_sync.main(["--dry-run"], _settings("sk_test_abc")) == 0
    out = capsys.readouterr().out
    assert "Stripe (test mode), prefix 'foundation'" in out and "would" in out
    assert mini.writes == []
