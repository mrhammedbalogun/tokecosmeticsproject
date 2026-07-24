# Plan-14b — Online Payments (Hybrid: Paystack + PayPal inline, Flutterwave redirect) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on the three online payment gateways on the storefront checkout in test mode — Paystack and PayPal collect money in an on-page pop-up, Flutterwave via redirect — and drive the deferred Plan-09 sandbox certification, with bank transfer remaining the fallback everywhere.

**Architecture:** The backend gateway adapters already exist and confirm money through the already-built `POST /api/v1/payments/{reference}/verify/`. This plan (1) makes three tiny backend contract changes so the client can drive inline SDKs and reactivates the gateways, then (2) builds the storefront collection layer — a per-gateway `PaymentLauncher` that opens Paystack's inline pop-up (`@paystack/inline-js`), PayPal's inline Buttons (`@paypal/react-paypal-js`), or redirects to Flutterwave's hosted page + a return page — all confirming via one authed BFF verify route.

**Tech Stack:** Django + DRF + pytest/respx (backend); Next.js (modified — see note) + React + TypeScript + vitest/@testing-library (storefront); `@paystack/inline-js`, `@paypal/react-paypal-js`.

**Design spec:** `docs/superpowers/specs/2026-07-24-plan-14b-online-payments-design.md` (read it first).

---

## ⚠️ Before you start

- **Branch/worktree:** this is a feature branch off `main`. If not already in an isolated worktree, create one (superpowers:using-git-worktrees).
- **This is NOT the Next.js you know** (`storefront/AGENTS.md`): before writing any `<Script>`, route handler, or page code, read the relevant guide in `storefront/node_modules/next/dist/docs/`. Don't assume App-Router APIs match public docs.
- **Test runners:** backend = `pytest` (run from `tokecosmetics-platform/backend`, e.g. `uv run pytest <path> -v`; if uv isn't wired, use the repo's `.venv` pytest). Storefront = `vitest` (run from `tokecosmetics-platform/storefront`, e.g. `npx vitest run <path>`).
- **Live production is NOT cut over.** All keys are test/sandbox; reactivating gateways on the preview site takes no real money. Live keys are a separate gated step (Plan-27).

## File structure (what this plan touches)

**Backend (create/modify):**
- Modify `backend/apps/payments/gateways/paypal.py` — expose `order_id` in `initiate()` result data.
- Modify `backend/config/settings/base.py` — add `STOREFRONT_BASE_URL`.
- Modify `backend/apps/checkout/services/checkout.py` — build + pass `return_url`.
- Modify `backend/apps/checkout/views.py` — add `payment.reference` to the 201 body.
- Create `backend/apps/payments/migrations/0008_reactivate_online_gateways.py` — reactivation data migration.
- Modify/create tests alongside each.

**Storefront (create):**
- `storefront/src/app/api/checkout/verify/route.ts` — authed BFF passthrough to the verify endpoint.
- `storefront/src/lib/payment-verify.ts` — client helper that calls the BFF verify route.
- `storefront/src/components/checkout/FlutterwaveLaunch.tsx` — redirect on mount.
- `storefront/src/components/checkout/PaystackLaunch.tsx` — inline pop-up.
- `storefront/src/components/checkout/PaypalLaunch.tsx` — inline Buttons.
- `storefront/src/components/checkout/PaymentLauncher.tsx` — dispatch + verify/route + failure fallback.
- `storefront/src/app/(shop)/checkout/return/page.tsx` — Flutterwave return + polling.
- **Modify** `storefront/src/components/checkout/ReviewStep.tsx` — dispatch to `PaymentLauncher` on a non-bank 201.
- Tests alongside each (`__tests__/`).

**Note:** `storefront/src/lib/payment-labels.ts` already has friendly labels for `paystack`/`flutterwave`/`paypal` — **no change needed.**

---

## Phase A — Backend enablement & contract

### Task 1: PayPal `initiate()` exposes the order id for inline Buttons

**Files:**
- Modify: `backend/apps/payments/gateways/paypal.py:121-122`
- Test: `backend/apps/payments/tests/test_paypal.py`

- [ ] **Step 1: Write the failing test** — append to `test_paypal.py`:

```python
@override_settings(**SETTINGS)
@respx.mock
def test_initiate_exposes_order_id_for_inline_buttons():
    """The PayPal JS SDK's createOrder() needs the order id client-side; it must ride
    back in the result data (not only as init.reference), because the checkout response
    forwards init.data verbatim as payment.data."""
    order, payment = _order_payment()
    _mock_token()
    respx.post(f"{BASE}/v2/checkout/orders").mock(
        return_value=httpx.Response(201, json={
            "id": "PAYPAL-ORDER-1",
            "links": [{"rel": "approve", "href": "https://paypal.com/approve/1"}],
        })
    )
    result = PayPalGateway().initiate(payment, order, return_url="https://shop/ret")
    assert result.data["order_id"] == "PAYPAL-ORDER-1"
    # The redirect_url stays for the (unused-in-inline) redirect path and existing tests.
    assert result.data["redirect_url"] == "https://paypal.com/approve/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/payments/tests/test_paypal.py::test_initiate_exposes_order_id_for_inline_buttons -v`
Expected: FAIL — `KeyError: 'order_id'`.

- [ ] **Step 3: Write minimal implementation** — in `paypal.py`, change the `initiate()` return:

```python
        return InitiateResult(action="redirect", reference=body["id"],
                              data={"redirect_url": approve, "order_id": body["id"]})
```

- [ ] **Step 4: Run the test + the full PayPal suite**

Run: `uv run pytest apps/payments/tests/test_paypal.py -v`
Expected: PASS (new test + all existing).

- [ ] **Step 5: Commit**

```bash
git add apps/payments/gateways/paypal.py apps/payments/tests/test_paypal.py
git commit -m "feat(payments): expose PayPal order_id in initiate data for inline Buttons"
```

---

### Task 2: Server-built `return_url` + `STOREFRONT_BASE_URL` setting

**Files:**
- Modify: `backend/config/settings/base.py:226` (after the gateway keys)
- Modify: `backend/apps/checkout/services/checkout.py:186-194`
- Test: `backend/apps/checkout/tests/test_return_url.py` (create)

- [ ] **Step 1: Add the setting** — in `base.py`, immediately after `PAYPAL_API_BASE`:

```python
# Storefront origin, used ONLY to build the gateway return URL (Flutterwave redirect).
# Never derived from a request — a client-supplied return URL is an open-redirect vector.
STOREFRONT_BASE_URL = env("STOREFRONT_BASE_URL", default="http://localhost:3000")
```

- [ ] **Step 2: Write the failing test** — create `backend/apps/checkout/tests/test_return_url.py`:

```python
"""_initiate_payment builds the gateway return URL server-side from a trusted setting +
the order's own reference, and passes it to the adapter. It must never come from request
data (open-redirect / tampering vector)."""
from decimal import Decimal

import pytest
from django.test import override_settings

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import InitiateResult, PaymentGateway

pytestmark = pytest.mark.django_db


class _CapturingGateway(PaymentGateway):
    code = "capret"
    supported_currencies = {"NGN"}
    seen_return_url = None

    def initiate(self, payment, order, return_url=""):
        type(self).seen_return_url = return_url
        return InitiateResult(action="redirect", reference=order.reservation_reference,
                              data={"redirect_url": "https://gw/pay"})


@pytest.fixture
def capret(monkeypatch):
    gw = _CapturingGateway()
    monkeypatch.setitem(registry._REGISTRY, "capret", gw)
    return gw


@override_settings(STOREFRONT_BASE_URL="https://preview.example.com")
def test_initiate_payment_passes_server_built_return_url(capret):
    from apps.checkout.services.checkout import _initiate_payment

    ng = Country.objects.get(code="NG")
    order = OrderFactory(number="TC-700001", country=ng, currency=ng.currency,
                         reservation_reference="TC-700001-1", grand_total="1000.00",
                         email="c@x.com")
    payment = PaymentFactory(order=order, currency=ng.currency, gateway="capret",
                             amount="1000.00")

    _initiate_payment(payment, order)

    assert _CapturingGateway.seen_return_url == (
        "https://preview.example.com/checkout/return?ref=TC-700001-1"
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest apps/checkout/tests/test_return_url.py -v`
Expected: FAIL — `seen_return_url` is `""` (current `_initiate_payment` passes no `return_url`).

- [ ] **Step 4: Write minimal implementation** — in `checkout.py`, edit `_initiate_payment`:

```python
def _initiate_payment(payment, order) -> None:
    """Call the gateway to start collecting money and persist what it returns. Raises
    GatewayError/GatewayNotConfigured on failure — the order stays pending_payment and
    the attempt is safely retryable (see the durable backstop above)."""
    # Server-built return URL: the trusted storefront origin + the order's OWN reference.
    # Never accept a return URL from the client (open-redirect / tampering). Only the
    # redirect gateway (Flutterwave) acts on it; the inline gateways ignore it.
    return_url = (
        f"{settings.STOREFRONT_BASE_URL.rstrip('/')}"
        f"/checkout/return?ref={order.reservation_reference}"
    )
    init = get_gateway(payment.gateway).initiate(payment, order, return_url=return_url)
    payment.gateway_reference = init.reference
    payment.raw_response = init.data
    payment.save(update_fields=["gateway_reference", "raw_response", "updated_at"])
    order._initiate = init  # stash for the view's response

    if init.action == "bank_details":
        transaction.on_commit(partial(enqueue_order_received, order.pk, init.data))
```

Ensure `from django.conf import settings` is imported at the top of `checkout.py` (it almost certainly already is — confirm).

- [ ] **Step 5: Run the test + the checkout suite**

Run: `uv run pytest apps/checkout/tests/test_return_url.py apps/checkout/tests/test_gateway_initiate_failure.py -v`
Expected: PASS. (The Flutterwave/Paystack adapters accept `return_url`; existing behaviour unchanged.)

- [ ] **Step 6: Commit**

```bash
git add config/settings/base.py apps/checkout/services/checkout.py apps/checkout/tests/test_return_url.py
git commit -m "feat(checkout): thread a server-built return_url into gateway initiate"
```

---

### Task 3: Checkout 201 body includes `payment.reference`

**Files:**
- Modify: `backend/apps/checkout/views.py:144-151`
- Test: `backend/apps/checkout/tests/test_checkout_response_reference.py` (create)

- [ ] **Step 1: Write the failing test** — create `backend/apps/checkout/tests/test_checkout_response_reference.py`:

```python
"""The checkout 201 body must carry payment.reference (= gateway_reference) so the
storefront's PaymentLauncher and the Flutterwave return page have the value the verify
endpoint keys on. Mirrors the setup in test_gateway_initiate_failure.py."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.payments.gateways.paystack import API_BASE
from apps.payments.models import CountryPaymentGateway
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


@override_settings(PAYSTACK_SECRET_KEY="sk_test_secret")
@respx.mock
def test_checkout_201_includes_payment_reference(django_user_model):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="paystack", defaults={"is_active": True})
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)

    respx.post(f"{API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(200, json={
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/xyz",
                     "access_code": "ac_123", "reference": "TC-ref-1"},
        })
    )

    user = django_user_model.objects.create_user(email="p@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    resp = client.post("/api/v1/checkout/",
                       {"cart_id": str(cart.id), "address_id": addr.id,
                        "delivery_option_id": opt.id, "payment_gateway": "paystack"},
                       format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k1")

    assert resp.status_code == 201, resp.data
    # The reference the verify endpoint keys on (gateway_reference), surfaced to the client.
    assert resp.data["payment"]["reference"] == "TC-ref-1"
    # access_code still flows for the Paystack inline pop-up.
    assert resp.data["payment"]["data"]["access_code"] == "ac_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/checkout/tests/test_checkout_response_reference.py -v`
Expected: FAIL — `KeyError: 'reference'` in the payment dict.

- [ ] **Step 3: Write minimal implementation** — in `views.py`, extend the response body:

```python
        init = getattr(result.order, "_initiate", None)
        body = {
            "order_number": result.order.number,
            "payment": {
                "gateway": result.payment.gateway,
                "action": init.action if init else "",
                "reference": result.payment.gateway_reference,
                "data": init.data if init else {},
            },
        }
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest apps/checkout/tests/test_checkout_response_reference.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/checkout/views.py apps/checkout/tests/test_checkout_response_reference.py
git commit -m "feat(checkout): include payment.reference in the place-order response"
```

---

### Task 4: Reactivation data migration

**Files:**
- Create: `backend/apps/payments/migrations/0008_reactivate_online_gateways.py`
- Test: `backend/apps/payments/tests/test_reactivate_gateways.py` (create)

**Context:** migration `0007` deactivated all networked gateways AND set `bank_transfer` to `sort_order=1` in every market. Reactivation must set `is_active` **and fix the sort order** so the menu reads correctly: NG → paystack(1)/flutterwave(2)/bank_transfer(3); GB/US/CA/ZZ → paypal(1)/bank_transfer(2). Stripe stays inactive (dropped in Plan-14).

- [ ] **Step 1: Write the failing test** — create `backend/apps/payments/tests/test_reactivate_gateways.py`:

```python
"""Reactivation (0008) turns on the three hybrid gateways with correct per-country sort,
leaves bank transfer active as the fallback, leaves Stripe off, and its reverse switches
the online gateways back off (reactivation is a human checkpoint, never a rollback side
effect)."""
import pytest

pytestmark = pytest.mark.django_db


def _offered(country):
    from apps.payments.gateways.registry import active_gateways_for
    return [(g["gateway"], g["sort_order"]) for g in active_gateways_for(country)]


def test_ng_menu_after_reactivation():
    from apps.core.models import Country
    ng = Country.objects.get(code="NG")
    assert _offered(ng) == [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)]


@pytest.mark.parametrize("code", ["GB", "US", "CA", "ZZ"])
def test_international_menu_after_reactivation(code):
    from apps.core.models import Country
    country = Country.objects.get(code=code)
    assert _offered(country) == [("paypal", 1), ("bank_transfer", 2)]


def test_stripe_stays_inactive():
    from apps.payments.models import CountryPaymentGateway
    assert not CountryPaymentGateway.objects.filter(gateway="stripe", is_active=True).exists()


def test_reverse_switches_online_gateways_off(transactional_db):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from apps.payments.models import CountryPaymentGateway

    MigrationExecutor(connection).migrate([("payments", "0007_launch_bank_transfer_only")])
    try:
        assert not CountryPaymentGateway.objects.filter(
            gateway__in=["paystack", "flutterwave", "paypal"], is_active=True
        ).exists()
        # bank transfer remains available everywhere after a rollback.
        assert CountryPaymentGateway.objects.filter(
            gateway="bank_transfer", is_active=True).count() >= 5
    finally:
        MigrationExecutor(connection).migrate([("payments", "0008_reactivate_online_gateways")])
```

Note: `active_gateways_for` returns active rows sorted by `sort_order` (as used in `test_launch_gateway_state.py`); confirm it exposes `sort_order` in each dict — if it returns model instances instead, adjust `_offered` to read attributes. Check `apps/payments/gateways/registry.py` before running.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/payments/tests/test_reactivate_gateways.py -v`
Expected: FAIL — the migration doesn't exist yet; NG offers only `bank_transfer` (sort 1).

- [ ] **Step 3: Write the migration** — create `0008_reactivate_online_gateways.py`:

```python
"""Reactivate the hybrid online gateways for Plan-14b test-mode certification.

0007 turned every networked gateway off and set bank_transfer to sort 1 everywhere. This
restores the real menu: Paystack/Flutterwave on NG, PayPal internationally, bank transfer
as the fallback. Stripe stays OFF (dropped in Plan-14). Safe: keys are test-mode and the
production storefront is not cut over — going live is a separate gated step (Plan-27).

Reverse switches the online gateways back off and restores bank_transfer to sort 1 (the
0007 end-state): reactivating a gateway is a human checkpoint, never a rollback side effect.
"""
from django.db import migrations

# (gateway, sort_order) per market. bank_transfer is already is_active=True from 0007.
MENU = {
    "NG": [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)],
    "GB": [("paypal", 1), ("bank_transfer", 2)],
    "US": [("paypal", 1), ("bank_transfer", 2)],
    "CA": [("paypal", 1), ("bank_transfer", 2)],
    "ZZ": [("paypal", 1), ("bank_transfer", 2)],
}
ONLINE = ["paystack", "flutterwave", "paypal"]


def reactivate(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    for code, rows in MENU.items():
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        for gateway, sort in rows:
            CPG.objects.update_or_create(
                country=country, gateway=gateway,
                defaults={"is_active": True, "sort_order": sort},
            )


def deactivate(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    CPG.objects.filter(gateway__in=ONLINE).update(is_active=False)
    # Restore the 0007 end-state: bank transfer sort 1 everywhere.
    for code in MENU:
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        CPG.objects.update_or_create(
            country=country, gateway="bank_transfer",
            defaults={"is_active": True, "sort_order": 1},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0007_launch_bank_transfer_only"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(reactivate, deactivate)]
```

- [ ] **Step 4: Apply the migration + run the test**

Run: `uv run python manage.py migrate payments` then `uv run pytest apps/payments/tests/test_reactivate_gateways.py apps/payments/tests/test_launch_gateway_state.py -v`
Expected: the reactivation tests PASS. **Note:** `test_launch_gateway_state.py::test_only_bank_transfer_is_offered` will now FAIL because the menu changed — that's correct. Update those launch-state assertions to the new menu (NG paystack/flutterwave/bank; others paypal/bank) in the same commit, OR mark them superseded per the repo's convention. Confirm with the spec's Menu section.

- [ ] **Step 5: Commit**

```bash
git add apps/payments/migrations/0008_reactivate_online_gateways.py apps/payments/tests/test_reactivate_gateways.py apps/payments/tests/test_launch_gateway_state.py
git commit -m "feat(payments): reactivate Paystack/Flutterwave/PayPal per country (test mode)"
```

- [ ] **Step 6: Full backend suite green**

Run: `uv run pytest -q`
Expected: PASS. Investigate any failure that references the gateway menu.

---

## Phase B — Storefront verify plumbing

### Task 5: BFF verify route

**Files:**
- Create: `storefront/src/app/api/checkout/verify/route.ts`
- Test: `storefront/src/app/api/checkout/__tests__/verify.test.ts`

- [ ] **Step 1: Write the failing test** — create `storefront/src/app/api/checkout/__tests__/verify.test.ts` (mirrors `place.test.ts`):

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { POST } from "@/app/api/checkout/verify/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (b: unknown) => new Request("http://localhost:3000/api/checkout/verify", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

describe("verify BFF", () => {
  it("forwards {reference} to the verify endpoint and returns the status body", async () => {
    const f = upstream(200, { order_number: "TC-1", order_status: "processing", payment_status: "succeeded" });
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ order_number: "TC-1", payment_status: "succeeded" });
    const [url] = f.mock.calls[0];
    expect(String(url)).toContain("/payments/TC-ref-1/verify/");
  });
  it("401 without a session, no upstream call", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(401); expect(f).not.toHaveBeenCalled();
  });
  it("400 when reference is missing, no upstream call", async () => {
    const f = upstream(200, {});
    const res = await POST(req({}));
    expect(res.status).toBe(400); expect(f).not.toHaveBeenCalled();
  });
  it("passes an upstream 404 straight through (order not the user's)", async () => {
    upstream(404, { detail: "Not found." });
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(404);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/app/api/checkout/__tests__/verify.test.ts`
Expected: FAIL — cannot import `@/app/api/checkout/verify/route`.

- [ ] **Step 3: Write minimal implementation** — create `storefront/src/app/api/checkout/verify/route.ts`:

```ts
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Re-verify a payment on customer return / inline callback (Plan-14b). Authed; the
 * backend scopes the payment to the requesting user's own orders (404 otherwise), so
 * a guessed reference can't leak another shopper's order. */
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  const reference = typeof body.reference === "string" ? body.reference : "";
  if (!reference) return json({ detail: "Missing reference." }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const out = await fetchWithAuth(
      `/payments/${encodeURIComponent(reference)}/verify/`,
      { method: "POST", country, body: {} },
    );
    return json(out, 200);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

Confirm `fetchWithAuth`'s signature accepts `{ method, country, body }` (it does in `src/app/api/checkout/route.ts`). If it requires a non-empty body differently, adjust.

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/app/api/checkout/__tests__/verify.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/api/checkout/verify/route.ts src/app/api/checkout/__tests__/verify.test.ts
git commit -m "feat(checkout): add authed BFF verify route"
```

---

### Task 6: `verifyPayment` client helper

**Files:**
- Create: `storefront/src/lib/payment-verify.ts`
- Test: `storefront/src/lib/__tests__/payment-verify.test.ts`

- [ ] **Step 1: Write the failing test** — create `storefront/src/lib/__tests__/payment-verify.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { verifyPayment } from "@/lib/payment-verify";

const orig = global.fetch;
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });

function mock(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
  ) as unknown as typeof fetch;
}

describe("verifyPayment", () => {
  it("maps a succeeded verify to ok + order details", async () => {
    mock(200, { order_number: "TC-9", order_status: "processing", payment_status: "succeeded" });
    const out = await verifyPayment("TC-ref-9");
    expect(out).toEqual({ ok: true, orderNumber: "TC-9", orderStatus: "processing", paymentStatus: "succeeded" });
  });
  it("returns ok:false on a non-2xx", async () => {
    mock(404, { detail: "Not found." });
    const out = await verifyPayment("nope");
    expect(out.ok).toBe(false);
  });
  it("returns ok:false on a network throw", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("boom")) as unknown as typeof fetch;
    const out = await verifyPayment("x");
    expect(out.ok).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/__tests__/payment-verify.test.ts`
Expected: FAIL — cannot import `@/lib/payment-verify`.

- [ ] **Step 3: Write minimal implementation** — create `storefront/src/lib/payment-verify.ts`:

```ts
/** Client-side helper: ask the BFF to re-verify a payment. Used by the inline pop-up
 * callbacks (Paystack/PayPal) and the Flutterwave return page. Never throws — every
 * failure resolves to { ok: false } so callers can show a calm retry/pending state. */
export interface VerifyOutcome {
  ok: boolean;
  orderNumber: string | null;
  orderStatus: string | null;
  paymentStatus: string | null;
}

export async function verifyPayment(reference: string): Promise<VerifyOutcome> {
  try {
    const res = await fetch("/api/checkout/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reference }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data) {
      return { ok: false, orderNumber: null, orderStatus: null, paymentStatus: null };
    }
    return {
      ok: true,
      orderNumber: data.order_number ?? null,
      orderStatus: data.order_status ?? null,
      paymentStatus: data.payment_status ?? null,
    };
  } catch {
    return { ok: false, orderNumber: null, orderStatus: null, paymentStatus: null };
  }
}
```

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/lib/__tests__/payment-verify.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/payment-verify.ts src/lib/__tests__/payment-verify.test.ts
git commit -m "feat(checkout): add verifyPayment client helper"
```

---

## Phase C — Storefront collection

### Task 7: Install gateway SDKs + client env

**Files:**
- Modify: `storefront/package.json` (via npm)
- Modify: `storefront/.env.local` (and document in `.env.example` if present)

- [ ] **Step 1: Install the SDKs** (from `tokecosmetics-platform/storefront`):

```bash
npm install @paystack/inline-js @paypal/react-paypal-js
```

- [ ] **Step 2: Add the client env var** — in `storefront/.env.local` (never committed):

```
NEXT_PUBLIC_PAYPAL_CLIENT_ID=<paypal sandbox client id>
```

Add the same key (with an empty/placeholder value) to `.env.example` if the repo keeps one, so the variable is discoverable.

- [ ] **Step 3: Verify the install builds/typechecks**

Run: `npx tsc --noEmit` (or the repo's typecheck script)
Expected: no new type errors from the added packages.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json .env.example
git commit -m "chore(storefront): add Paystack/PayPal inline SDK deps + PayPal client-id env"
```

---

### Task 8: `FlutterwaveLaunch` — redirect on mount

**Files:**
- Create: `storefront/src/components/checkout/FlutterwaveLaunch.tsx`
- Test: `storefront/src/components/checkout/__tests__/FlutterwaveLaunch.test.tsx`

- [ ] **Step 1: Write the failing test**:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { FlutterwaveLaunch } from "@/components/checkout/FlutterwaveLaunch";

const assign = vi.fn();
beforeEach(() => {
  assign.mockClear();
  Object.defineProperty(window, "location", { value: { assign }, writable: true });
});
afterEach(() => vi.restoreAllMocks());

describe("FlutterwaveLaunch", () => {
  it("redirects to the hosted page on mount", () => {
    render(<FlutterwaveLaunch data={{ redirect_url: "https://flw/pay/abc" }} />);
    expect(assign).toHaveBeenCalledWith("https://flw/pay/abc");
  });
  it("shows a retryable error and does not navigate when redirect_url is missing", () => {
    render(<FlutterwaveLaunch data={{}} />);
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/FlutterwaveLaunch.test.tsx`
Expected: FAIL — cannot import the component.

- [ ] **Step 3: Write minimal implementation**:

```tsx
"use client";
import { useEffect, useState } from "react";

/** Flutterwave uses a HOSTED page (not inline): redirect the browser to it. The customer
 * comes back to /checkout/return?ref=... which the server baked into the return URL. */
export function FlutterwaveLaunch({ data }: { data: Record<string, unknown> }) {
  const url = typeof data.redirect_url === "string" ? data.redirect_url : "";
  const [failed, setFailed] = useState(!url);

  useEffect(() => {
    if (url) window.location.assign(url);
    else setFailed(true);
  }, [url]);

  if (failed) {
    return (
      <p role="alert" className="text-sm text-red-700">
        We couldn&apos;t open the payment page. Please try again or choose another method.
      </p>
    );
  }
  return <p className="text-sm text-muted">Redirecting you to complete payment…</p>;
}
```

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/components/checkout/__tests__/FlutterwaveLaunch.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/checkout/FlutterwaveLaunch.tsx src/components/checkout/__tests__/FlutterwaveLaunch.test.tsx
git commit -m "feat(checkout): FlutterwaveLaunch redirects to the hosted page"
```

---

### Task 9: `PaystackLaunch` — inline pop-up

**Files:**
- Create: `storefront/src/components/checkout/PaystackLaunch.tsx`
- Test: `storefront/src/components/checkout/__tests__/PaystackLaunch.test.tsx`

> **Verify the SDK signature first:** open `storefront/node_modules/@paystack/inline-js` types and confirm the v2 default export and `resumeTransaction(accessCode, { onSuccess, onCancel, onError })` shape. The code below targets that shape; adjust names to the installed version if they differ (e.g. `PaystackPop` vs default export). Keep the callback contract (`onGatewaySuccess`/`onGatewayAbort`) identical so `PaymentLauncher` and the test stay valid.

- [ ] **Step 1: Write the failing test** — mocks the SDK to fire `onSuccess`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";

// Mock the Paystack SDK: constructing it yields an object whose resumeTransaction
// immediately invokes the success callback (the "customer paid" path).
const resumeTransaction = vi.fn((_code: string, cbs: { onSuccess: (t: unknown) => void }) => {
  cbs.onSuccess({ reference: "TC-ref-1" });
});
vi.mock("@paystack/inline-js", () => ({
  default: vi.fn().mockImplementation(() => ({ resumeTransaction })),
}));

import { PaystackLaunch } from "@/components/checkout/PaystackLaunch";

beforeEach(() => resumeTransaction.mockClear());
afterEach(() => vi.restoreAllMocks());

describe("PaystackLaunch", () => {
  it("opens the pop-up with the access code and calls onGatewaySuccess when paid", () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(
      <PaystackLaunch
        data={{ access_code: "ac_123" }}
        onGatewaySuccess={onGatewaySuccess}
        onGatewayAbort={onGatewayAbort}
      />
    );
    expect(resumeTransaction).toHaveBeenCalledWith("ac_123", expect.any(Object));
    expect(onGatewaySuccess).toHaveBeenCalled();
    expect(onGatewayAbort).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/PaystackLaunch.test.tsx`
Expected: FAIL — cannot import the component.

- [ ] **Step 3: Write minimal implementation**:

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import PaystackPop from "@paystack/inline-js";

interface Props {
  data: Record<string, unknown>;
  onGatewaySuccess: () => void;   // money taken at the gateway; parent then verifies
  onGatewayAbort: () => void;     // customer closed the pop-up / SDK error
}

/** Paystack inline pop-up. Uses the server-minted access_code (no public key needed).
 * The parent (PaymentLauncher) owns the verify + route step; this only drives the SDK. */
export function PaystackLaunch({ data, onGatewaySuccess, onGatewayAbort }: Props) {
  const accessCode = typeof data.access_code === "string" ? data.access_code : "";
  const opened = useRef(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (opened.current) return;    // StrictMode double-invoke guard — open exactly once
    opened.current = true;
    if (!accessCode) { setFailed(true); return; }
    try {
      const popup = new PaystackPop();
      popup.resumeTransaction(accessCode, {
        onSuccess: () => onGatewaySuccess(),
        onCancel: () => onGatewayAbort(),
        onError: () => onGatewayAbort(),
      });
    } catch {
      setFailed(true);
    }
  }, [accessCode, onGatewaySuccess, onGatewayAbort]);

  if (failed) {
    return (
      <p role="alert" className="text-sm text-red-700">
        We couldn&apos;t open the payment window. Please try again or choose another method.
      </p>
    );
  }
  return <p className="text-sm text-muted">Complete your payment in the pop-up…</p>;
}
```

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/components/checkout/__tests__/PaystackLaunch.test.tsx`
Expected: PASS. If it fails on the SDK export name, fix per the "Verify the SDK signature first" note and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/components/checkout/PaystackLaunch.tsx src/components/checkout/__tests__/PaystackLaunch.test.tsx
git commit -m "feat(checkout): PaystackLaunch inline pop-up via access_code"
```

---

### Task 10: `PaypalLaunch` — inline Buttons

**Files:**
- Create: `storefront/src/components/checkout/PaypalLaunch.tsx`
- Test: `storefront/src/components/checkout/__tests__/PaypalLaunch.test.tsx`

> **Verify the SDK option key:** confirm `@paypal/react-paypal-js`'s `PayPalScriptProvider` option name for the client id in the installed version (`clientId` in v8+, `"client-id"` earlier). Adjust if needed.

- [ ] **Step 1: Write the failing test** — mocks the SDK to expose pay/cancel buttons:

```tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock the React PayPal SDK: provider passes children through; Buttons renders two
// buttons wired to onApprove / onCancel so we can drive both paths deterministically.
vi.mock("@paypal/react-paypal-js", () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PayPalButtons: ({ onApprove, onCancel }: {
    onApprove: (d: unknown, a: unknown) => void; onCancel: () => void;
  }) => (
    <div>
      <button onClick={() => onApprove({}, {})}>pp-approve</button>
      <button onClick={() => onCancel()}>pp-cancel</button>
    </div>
  ),
}));

import { PaypalLaunch } from "@/components/checkout/PaypalLaunch";

afterEach(() => vi.restoreAllMocks());

describe("PaypalLaunch", () => {
  it("calls onGatewaySuccess when the buyer approves", () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(<PaypalLaunch data={{ order_id: "PP-1" }}
      onGatewaySuccess={onGatewaySuccess} onGatewayAbort={onGatewayAbort} />);
    fireEvent.click(screen.getByText("pp-approve"));
    expect(onGatewaySuccess).toHaveBeenCalled();
  });
  it("calls onGatewayAbort when the buyer cancels", () => {
    const onGatewaySuccess = vi.fn();
    const onGatewayAbort = vi.fn();
    render(<PaypalLaunch data={{ order_id: "PP-1" }}
      onGatewaySuccess={onGatewaySuccess} onGatewayAbort={onGatewayAbort} />);
    fireEvent.click(screen.getByText("pp-cancel"));
    expect(onGatewayAbort).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/PaypalLaunch.test.tsx`
Expected: FAIL — cannot import the component.

- [ ] **Step 3: Write minimal implementation**:

```tsx
"use client";
import { PayPalScriptProvider, PayPalButtons } from "@paypal/react-paypal-js";

interface Props {
  data: Record<string, unknown>;
  onGatewaySuccess: () => void;
  onGatewayAbort: () => void;
}

/** PayPal inline Buttons. createOrder returns the SERVER-created order id (from
 * payment.data.order_id) — the amount is fixed server-side, never sent from the client.
 * onApprove hands off to the parent's verify step, which captures + confirms. */
export function PaypalLaunch({ data, onGatewaySuccess, onGatewayAbort }: Props) {
  const clientId = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? "";
  const orderId = typeof data.order_id === "string" ? data.order_id : "";

  if (!clientId || !orderId) {
    return (
      <p role="alert" className="text-sm text-red-700">
        PayPal isn&apos;t available right now. Please try again or choose another method.
      </p>
    );
  }
  return (
    <PayPalScriptProvider options={{ clientId, currency: "USD", intent: "capture" }}>
      <PayPalButtons
        createOrder={() => Promise.resolve(orderId)}
        onApprove={() => { onGatewaySuccess(); return Promise.resolve(); }}
        onCancel={() => onGatewayAbort()}
        onError={() => onGatewayAbort()}
      />
    </PayPalScriptProvider>
  );
}
```

**Note on currency:** the SDK loads per-currency. `"USD"` is a safe default for the sandbox walkthrough; the plan's Open Item O3 (spec) is to confirm whether intl markets (GBP/CAD/EUR) need the provider re-keyed by the order's currency. If so, pass the order currency into `data` (extend the PayPal adapter/response) and thread it here. Not blocking for certification with a single sandbox currency.

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/components/checkout/__tests__/PaypalLaunch.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/checkout/PaypalLaunch.tsx src/components/checkout/__tests__/PaypalLaunch.test.tsx
git commit -m "feat(checkout): PaypalLaunch inline Buttons via server-created order id"
```

---

### Task 11: `PaymentLauncher` — dispatch + verify/route + fallback

**Files:**
- Create: `storefront/src/components/checkout/PaymentLauncher.tsx`
- Test: `storefront/src/components/checkout/__tests__/PaymentLauncher.test.tsx`

- [ ] **Step 1: Write the failing test** — mocks the three children + `verifyPayment` + router:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const verifyPayment = vi.fn();
vi.mock("@/lib/payment-verify", () => ({ verifyPayment: (r: string) => verifyPayment(r) }));

// Child stubs: each exposes a button to fire the gateway success/abort callbacks.
vi.mock("@/components/checkout/PaystackLaunch", () => ({
  PaystackLaunch: ({ onGatewaySuccess, onGatewayAbort }: {
    onGatewaySuccess: () => void; onGatewayAbort: () => void;
  }) => (<div><button onClick={onGatewaySuccess}>ps-ok</button><button onClick={onGatewayAbort}>ps-abort</button></div>),
}));
vi.mock("@/components/checkout/PaypalLaunch", () => ({
  PaypalLaunch: () => <div>paypal-child</div>,
}));
vi.mock("@/components/checkout/FlutterwaveLaunch", () => ({
  FlutterwaveLaunch: () => <div>flutterwave-child</div>,
}));

import { PaymentLauncher } from "@/components/checkout/PaymentLauncher";

beforeEach(() => { replace.mockClear(); verifyPayment.mockReset(); });
afterEach(() => vi.restoreAllMocks());

const launch = (gateway: string) => ({ gateway, reference: "TC-ref-1", data: {} });

describe("PaymentLauncher", () => {
  it("routes to confirmation when a Paystack success verifies as succeeded", async () => {
    verifyPayment.mockResolvedValue({ ok: true, orderNumber: "TC-77", paymentStatus: "succeeded", orderStatus: "processing" });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() => expect(verifyPayment).toHaveBeenCalledWith("TC-ref-1"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-77"));
  });

  it("shows a retry state (no navigation) when the buyer aborts", async () => {
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-abort"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/didn.t go through|not completed/i));
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a calm pending state when verify is not yet succeeded", async () => {
    verifyPayment.mockResolvedValue({ ok: true, orderNumber: "TC-77", paymentStatus: "pending", orderStatus: "pending_payment" });
    render(<PaymentLauncher launch={launch("paystack")} />);
    fireEvent.click(screen.getByText("ps-ok"));
    await waitFor(() => expect(screen.getByText(/confirming your payment/i)).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("renders the PayPal child for a paypal launch", () => {
    render(<PaymentLauncher launch={launch("paypal")} />);
    expect(screen.getByText("paypal-child")).toBeInTheDocument();
  });

  it("renders the Flutterwave child for a flutterwave launch", () => {
    render(<PaymentLauncher launch={launch("flutterwave")} />);
    expect(screen.getByText("flutterwave-child")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/PaymentLauncher.test.tsx`
Expected: FAIL — cannot import the component.

- [ ] **Step 3: Write minimal implementation**:

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { verifyPayment } from "@/lib/payment-verify";
import { PaystackLaunch } from "@/components/checkout/PaystackLaunch";
import { PaypalLaunch } from "@/components/checkout/PaypalLaunch";
import { FlutterwaveLaunch } from "@/components/checkout/FlutterwaveLaunch";

export interface LaunchInfo {
  gateway: string;
  reference: string;                 // = payment.gateway_reference (verify keys on it)
  data: Record<string, unknown>;     // payment.data from the 201
}

type Phase = "collecting" | "verifying" | "pending" | "failed";

/** Owns the money-collection UI once an order is placed with an online gateway. Delegates
 * SDK specifics to the per-gateway child, then verifies server-side and routes. Every
 * path reaches a terminal state — success, a retry prompt, or a calm "we'll email you". */
export function PaymentLauncher({ launch }: { launch: LaunchInfo }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("collecting");

  async function onGatewaySuccess() {
    setPhase("verifying");
    const out = await verifyPayment(launch.reference);
    if (out.ok && out.paymentStatus === "succeeded" && out.orderNumber) {
      router.replace(`/checkout/confirmation/${out.orderNumber}`);
      return;
    }
    // Money may be in flight (webhook will reconcile) or genuinely not taken. Either way,
    // don't spin: show a calm terminal state. The confirmation email lands when it clears.
    setPhase("pending");
  }

  function onGatewayAbort() {
    setPhase("failed");
  }

  if (phase === "failed") {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-red-700">
          Your payment didn&apos;t go through. You can try again or choose another method.
        </p>
        <a href="/checkout" className="text-sm underline">Choose another method</a>
      </div>
    );
  }
  if (phase === "pending") {
    return (
      <p className="text-sm text-muted">
        We&apos;re confirming your payment — you&apos;ll get an email as soon as it clears.
      </p>
    );
  }
  if (phase === "verifying") {
    return <p className="text-sm text-muted">Confirming your payment…</p>;
  }

  // phase === "collecting"
  switch (launch.gateway) {
    case "paystack":
      return <PaystackLaunch data={launch.data}
        onGatewaySuccess={onGatewaySuccess} onGatewayAbort={onGatewayAbort} />;
    case "paypal":
      return <PaypalLaunch data={launch.data}
        onGatewaySuccess={onGatewaySuccess} onGatewayAbort={onGatewayAbort} />;
    case "flutterwave":
      return <FlutterwaveLaunch data={launch.data} />;
    default:
      return (
        <p role="alert" className="text-sm text-red-700">
          That payment method isn&apos;t available right now. Please choose another.
        </p>
      );
  }
}
```

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/components/checkout/__tests__/PaymentLauncher.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/checkout/PaymentLauncher.tsx src/components/checkout/__tests__/PaymentLauncher.test.tsx
git commit -m "feat(checkout): PaymentLauncher dispatch + verify/route + fallback states"
```

---

### Task 12: Wire `ReviewStep` to dispatch on a non-bank 201

**Files:**
- Modify: `storefront/src/components/checkout/ReviewStep.tsx:180-214`
- Test: `storefront/src/components/checkout/__tests__/ReviewStep.test.tsx` (extend)

**Behaviour:** on a `201`, if `payment.action === "bank_details"` keep the current path (stash + `router.push` confirmation). Otherwise, render `<PaymentLauncher>` with `{gateway, reference, data}` from the response instead of navigating.

- [ ] **Step 1: Write the failing test** — append to `ReviewStep.test.tsx`. Mock `PaymentLauncher` at the top of the file (add near the other `vi.mock` calls):

```tsx
// (add with the other vi.mock calls at the top of the file)
vi.mock("@/components/checkout/PaymentLauncher", () => ({
  PaymentLauncher: ({ launch }: { launch: { gateway: string; reference: string } }) => (
    <div data-testid="launcher">{launch.gateway}:{launch.reference}</div>
  ),
}));
```

```tsx
// (add inside describe("ReviewStep", ...))
it("renders PaymentLauncher (not a redirect to confirmation) for an online gateway", async () => {
  const f = mockFetch({
    [QUOTE_URL]: {
      status: 200,
      body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
    },
    [PLACE_URL]: {
      status: 201,
      body: { order_number: "TC-200", payment: { gateway: "paystack", action: "redirect", reference: "TC-ref-1", data: { access_code: "ac_1" } } },
    },
  });
  renderHarness();
  await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: /place order/i }));
  await waitFor(() => expect(screen.getByTestId("launcher")).toHaveTextContent("paystack:TC-ref-1"));
  expect(push).not.toHaveBeenCalled();  // no confirmation redirect for the inline path
  void f;
});
```

The existing bank-transfer test (`"...then navigates + stashes bank details"`) must still pass — that path is unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/ReviewStep.test.tsx`
Expected: the new test FAILS (no launcher rendered); the bank-transfer test still passes.

- [ ] **Step 3: Write minimal implementation** — in `ReviewStep.tsx`:

Add the import and a `launch` state near the other hooks:

```tsx
import { PaymentLauncher, type LaunchInfo } from "@/components/checkout/PaymentLauncher";
```

```tsx
  const [launch, setLaunch] = useState<LaunchInfo | null>(null);
```

Change the `201` branch in `handlePlaceOrder`:

```tsx
      if (res.status === 201 && data?.order_number) {
        if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(COUPON_STORAGE_KEY);
        const payment = data.payment ?? {};
        if (payment.action === "bank_details") {
          if (payment.data) stashBankHandoff(data.order_number, payment.data);
          router.push(`/checkout/confirmation/${data.order_number}`);
          return;
        }
        // Online gateway: hand off to the launcher (inline pop-up / redirect). It owns
        // verify + routing to confirmation from here.
        setLaunch({
          gateway: payment.gateway,
          reference: payment.reference,
          data: payment.data ?? {},
        });
        return;
      }
```

Render the launcher when set — put this near the top of the returned JSX (before the review list), and short-circuit the rest so the customer sees only the payment step:

```tsx
  if (launch) {
    return (
      <div className="space-y-4">
        <PaymentLauncher launch={launch} />
      </div>
    );
  }
```

(Place this `if (launch)` block right after the existing `if (!addressId || ...)` guard.)

- [ ] **Step 4: Run the test + the whole ReviewStep suite**

Run: `npx vitest run src/components/checkout/__tests__/ReviewStep.test.tsx`
Expected: PASS (new test + all existing, including the bank-transfer path).

- [ ] **Step 5: Commit**

```bash
git add src/components/checkout/ReviewStep.tsx src/components/checkout/__tests__/ReviewStep.test.tsx
git commit -m "feat(checkout): dispatch to PaymentLauncher for online gateways on place-order"
```

---

### Task 13: Flutterwave return page + polling

**Files:**
- Create: `storefront/src/app/(shop)/checkout/return/page.tsx`
- Test: `storefront/src/components/checkout/__tests__/CheckoutReturn.test.tsx`

**Design:** client page reads `?ref` (the `gateway_reference` the server baked into the return URL), calls `verifyPayment(ref)`, and polls up to `MAX_POLLS` (5) with a short delay. `succeeded` → `router.replace(confirmation)`; a definitive non-pending failure → retry state; still pending after the last poll → "we'll email you". Extract the body into a testable `CheckoutReturn` component so we can drive it without Next's route/searchParams machinery.

- [ ] **Step 1: Write the failing test**:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const verifyPayment = vi.fn();
vi.mock("@/lib/payment-verify", () => ({ verifyPayment: (r: string) => verifyPayment(r) }));

import { CheckoutReturn } from "@/app/(shop)/checkout/return/page";

beforeEach(() => { replace.mockClear(); verifyPayment.mockReset(); });
afterEach(() => vi.restoreAllMocks());

describe("CheckoutReturn", () => {
  it("routes to confirmation once verify reports succeeded", async () => {
    verifyPayment.mockResolvedValue({ ok: true, orderNumber: "TC-88", paymentStatus: "succeeded", orderStatus: "processing" });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout/confirmation/TC-88"));
  });

  it("shows a retry state on a failed payment", async () => {
    verifyPayment.mockResolvedValue({ ok: true, orderNumber: "TC-88", paymentStatus: "failed", orderStatus: "pending_payment" });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/didn.t go through/i));
    expect(replace).not.toHaveBeenCalled();
  });

  it("falls back to an email-us message when still pending after the max polls", async () => {
    verifyPayment.mockResolvedValue({ ok: true, orderNumber: "TC-88", paymentStatus: "pending", orderStatus: "pending_payment" });
    render(<CheckoutReturn reference="TC-ref-88" pollDelayMs={0} maxPolls={3} />);
    await waitFor(() => expect(screen.getByText(/confirming your payment/i)).toBeInTheDocument());
    expect(verifyPayment).toHaveBeenCalledTimes(3);
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows an error when no reference is present", () => {
    render(<CheckoutReturn reference="" pollDelayMs={0} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(verifyPayment).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/checkout/__tests__/CheckoutReturn.test.tsx`
Expected: FAIL — cannot import `CheckoutReturn`.

- [ ] **Step 3: Write minimal implementation** — create `storefront/src/app/(shop)/checkout/return/page.tsx`:

> Read `storefront/node_modules/next/dist/docs/` for how this Next version passes `searchParams` to a page before finalizing the default export. The `CheckoutReturn` component below is the testable core; the page default export just extracts `ref` and renders it.

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { verifyPayment } from "@/lib/payment-verify";

type State = "polling" | "failed" | "pending" | "missing";

const DEFAULT_MAX_POLLS = 5;
const DEFAULT_POLL_DELAY_MS = 3000;

/** Where Flutterwave redirects back to. Bounded polling → always a terminal state:
 * confirmation, a retry prompt, or "we'll email you". Never an infinite spinner. */
export function CheckoutReturn({
  reference,
  maxPolls = DEFAULT_MAX_POLLS,
  pollDelayMs = DEFAULT_POLL_DELAY_MS,
}: {
  reference: string;
  maxPolls?: number;
  pollDelayMs?: number;
}) {
  const router = useRouter();
  const [state, setState] = useState<State>(reference ? "polling" : "missing");
  const started = useRef(false);

  useEffect(() => {
    if (!reference || started.current) return;
    started.current = true;
    let cancelled = false;

    (async () => {
      for (let attempt = 0; attempt < maxPolls; attempt++) {
        const out = await verifyPayment(reference);
        if (cancelled) return;
        if (out.ok && out.paymentStatus === "succeeded" && out.orderNumber) {
          router.replace(`/checkout/confirmation/${out.orderNumber}`);
          return;
        }
        if (out.ok && (out.paymentStatus === "failed" || out.paymentStatus === "cancelled")) {
          setState("failed");
          return;
        }
        if (attempt < maxPolls - 1 && pollDelayMs > 0) {
          await new Promise((r) => setTimeout(r, pollDelayMs));
        }
      }
      if (!cancelled) setState("pending");   // still pending after the last poll
    })();

    return () => { cancelled = true; };
  }, [reference, maxPolls, pollDelayMs, router]);

  if (state === "missing") {
    return (
      <p role="alert" className="text-sm text-red-700">
        We couldn&apos;t find your payment. Please return to checkout and try again.
      </p>
    );
  }
  if (state === "failed") {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-red-700">
          Your payment didn&apos;t go through. You can try again or choose another method.
        </p>
        <a href="/checkout" className="text-sm underline">Back to checkout</a>
      </div>
    );
  }
  if (state === "pending") {
    return (
      <p className="text-sm text-muted">
        We&apos;re confirming your payment — you&apos;ll get an email as soon as it clears.
      </p>
    );
  }
  return <p className="text-sm text-muted">Confirming your payment…</p>;
}

export default function CheckoutReturnPage({
  searchParams,
}: {
  searchParams: { ref?: string };
}) {
  const ref = typeof searchParams?.ref === "string" ? searchParams.ref : "";
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <CheckoutReturn reference={ref} />
    </div>
  );
}
```

**If this Next version delivers `searchParams` as a Promise** (per its docs), make the default export `async` and `await searchParams` before reading `ref` — the `CheckoutReturn` component and its tests are unaffected.

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/components/checkout/__tests__/CheckoutReturn.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "src/app/(shop)/checkout/return/page.tsx" src/components/checkout/__tests__/CheckoutReturn.test.tsx
git commit -m "feat(checkout): Flutterwave return page with bounded verify polling"
```

---

### Task 14: Full suites green + typecheck/build

- [ ] **Step 1: Backend suite**

Run (from `backend`): `uv run pytest -q`
Expected: PASS.

- [ ] **Step 2: Storefront suite + typecheck**

Run (from `storefront`): `npx vitest run` then `npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 3: Storefront production build** (catches App-Router / "use client" / env issues tests miss)

Run (from `storefront`): `npm run build`
Expected: build succeeds. Fix any RSC/client-boundary errors on the new pages/components.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test(checkout): green backend + storefront suites and production build for Plan-14b"
```

---

## Phase D — Test-mode certification (the deferred Plan-09 checkpoint — the real risk)

> This is a **manual** phase driven with Hammed on the preview site. No production keys. It closes the deferred Plan-09 sandbox certification. Do NOT mark Plan-14b done until every box here is checked.

### Task 15: Configure test-mode keys + document

- [ ] Populate backend `.env` (never committed) with test-mode values: `PAYSTACK_SECRET_KEY`, `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_SECRET_HASH`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `STOREFRONT_BASE_URL` (= preview URL). `PAYPAL_API_BASE` already defaults to sandbox.
- [ ] Populate storefront `.env.local`: `NEXT_PUBLIC_PAYPAL_CLIENT_ID` (sandbox).
- [ ] Confirm every value is test/sandbox — cross-check each gateway dashboard is in test mode.
- [ ] Deploy the branch to the preview environment.

### Task 16: Drive one test-mode payment per gateway through the real UI

- [ ] **Paystack (NG):** place an order → inline pop-up → Paystack **test card** → order flips to `processing`, stock commits, confirmation page shown, confirmation email sent.
- [ ] **PayPal (international market):** place an order → inline Buttons → **sandbox** buyer approves → capture → `processing` + email.
- [ ] **Flutterwave (NG):** place an order → redirect to hosted page → **test card** → return page → `processing` + email.
- [ ] **Bank transfer** still works as the fallback in NG and in an international market (unchanged path).
- [ ] Walk **mobile viewport** for at least Paystack (NG primary) and PayPal.
- [ ] **Cancel/close** a pop-up (Paystack and PayPal) and a hosted-page payment (Flutterwave) → the retry state appears; retrying the same order succeeds.

### Task 17: Prove each webhook signature path once

- [ ] For each gateway, deliver one signed webhook (gateway dashboard simulator or a temporary tunnel, e.g. cloudflared) and confirm it verifies and is idempotent against the return-verify (no double fulfilment, no error).
- [ ] Confirm an **amount/currency mismatch** still flags `needs_review` and does NOT fulfil (existing test proves the code; spot-check once live-style if feasible).

### Task 18: Hammed's checkpoint sign-off

- [ ] Hammed does a **test-mode** purchase himself on his phone through **each** of the three gateways on the preview site and sees the order confirm.
- [ ] Explicit sign-off that: (a) all three certify, (b) bank transfer still works as fallback, (c) he understands **no real money moves** until live keys at cutover (Plan-27).
- [ ] Record the sign-off in the memory entry for Plan-14b.

---

## Self-review notes (author)

- **Spec coverage:** backend changes #1–#4 (spec Architecture → Backend) = Tasks 1–4; verify BFF (spec Storefront) = Task 5; verify helper = Task 6; SDKs/env = Task 7; PaymentLauncher + children (spec Storefront) = Tasks 8–11; ReviewStep dispatch = Task 12; return page (spec Storefront) = Task 13; suites/build (spec Verification → Automated) = Task 14; certification (spec Verification → Manual + Checkpoint) = Tasks 15–18. Menu (spec) = Task 4. Config/settings (spec) = Tasks 2 & 7.
- **Payment labels:** spec said "add labels if missing" — verified already present in `payment-labels.ts`, so no task. Noted in File structure.
- **Open items:** O1 resolved (Task 3). O2 (Paystack npm vs CDN) resolved: npm package (Task 7/9). O3 (PayPal per-currency SDK) parked with a concrete note in Task 10 — non-blocking for single-currency sandbox certification; flagged for follow-up.
- **Type consistency:** `LaunchInfo` (Task 11) is the single type used by `PaymentLauncher` and imported by `ReviewStep` (Task 12); children use `{ data, onGatewaySuccess, onGatewayAbort }` uniformly (Tasks 8–11); `VerifyOutcome` fields (`ok`/`orderNumber`/`orderStatus`/`paymentStatus`) are consistent across Tasks 6, 11, 13.
