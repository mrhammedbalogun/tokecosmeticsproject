# Plan-14 — Storefront checkout (cart → 5-step → bank transfer → confirmation) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Plan-12 cart/checkout skeletons into a real purchase flow — a cart page and an Amazon-style 5-step checkout wired end-to-end to **bank transfer** (the only live method), with inline guest signup, order confirmation, and a correct totals/coupon preview — shippable and verifiable with no external payment gateway.

**Architecture:** Server Components render the page shells; client islands own the interactive parts (the step accordion + its shared checkout state, the cart editors, the coupon field). Every Django read/write goes through the existing `lib/api.ts` server client or a same-origin BFF Route Handler (`fetchWithAuth`) — the browser never holds a JWT. Money is **never** computed in the storefront: a new read-only `POST /checkout/quote/` endpoint returns authoritative totals + coupon validation. The place-order call is idempotent (client-generated `Idempotency-Key`). Bank-transfer account details ride back in the placement response and are handed to the confirmation page via `sessionStorage`.

**Tech Stack:** Django 5 + DRF (one additive endpoint, Task 1) · Next.js 16.2.10 App Router · React 19.2 · TanStack Query (existing `useCart`) · Tailwind v4 tokens · Vitest + RTL (storefront) · pytest (Task 1). Reuses Plan-08/09/09b/11/12/13 code; **no other backend changes**.

**Spec:** `docs/superpowers/specs/2026-07-23-plan-14-storefront-checkout-design.md` (approved 2026-07-23). **Branch:** `plan-14-storefront-checkout` (already cut off `main`).

---

## ⚠️ Read this first

- **Next.js 16 is not older Next.** `cookies()`/`headers()` are async; `params`/`searchParams` are Promises; middleware is `src/proxy.ts`. If unsure, read the bundled docs under `storefront/node_modules/next/dist/docs/01-app/` — they win over any snippet here.
- **Never compute money client-side.** Display API strings verbatim; totals come only from `/cart` (subtotal) and the new `/checkout/quote/` (everything else). The one arithmetic allowed is the free-shipping *progress bar percentage*, which is display-only and never shown as a money value.
- **The browser never sees a JWT.** Authed calls go through `fetchWithAuth` (Server Components / Route Handlers). Tests assert 401 without a session.
- **wp-cli/root ownership gotcha does not apply here** — this is the rebuild platform, not the live WP server.

## Backend contracts (verified against code — do not re-derive from memory)

- `GET /api/v1/cart/` → `{id, kind, status, country, currency, items:[{id, variant_id, sku, name, variant_name, quantity, unit_price, line_total, unavailable}], subtotal, has_unavailable}` (see `apps/carts/serializers.py`). **subtotal only** — no discount/tax/delivery/total.
- `compute_totals(items, country, delivery_amount, coupon) -> Totals(subtotal, discount, delivery, tax, grand_total, currency)` and `validate_coupon(...) -> CouponValidation(ok, coupon, error_code)` (`apps/checkout/services/{totals,coupons}.py`) — server-side, **not yet HTTP-exposed** (Task 1 exposes a read-only quote).
- `GET /api/v1/checkout/payment-methods/?country=NG` (**AllowAny**) → `[{gateway, sort_order}]`. Bank transfer is the only active row now (gateway code `bank_transfer`).
- `GET /api/v1/checkout/delivery-options/?address_id=&cart_id=` (**IsAuthenticated**) → `[{id, name, price|null, eta_min_days, eta_max_days, quote_required, ...}]` (see `apps/delivery/services.py::options_for_address`; `price` is a money string or null when `quote_required`).
- `POST /api/v1/checkout/` (**IsAuthenticated**, header **`Idempotency-Key`** required) body `{cart_id, address_id, billing_address_id?, delivery_option_id, coupon_code?, payment_gateway, notes?, expected_total?}` → `201 {order_number, payment:{gateway, action, data}}`. For bank transfer: `action="bank_details"`, `data={bank_name, account_name, account_number, ...extra, display:{...}, reference, instructions}`. Errors: `CheckoutError` → `{error, detail, ...extra}` at `exc.http`; `409 {error:"idempotency_in_progress"}`; `422 {error:"idempotency_key_reused"}`.
- `GET /api/v1/orders/<number>/` (**IsAuthenticated**, owner) → `OrderSerializer`: `{number, status, placed_at, email, phone, currency, subtotal, discount_total, shipping_total, tax_total, grand_total, grand_total_display, delivery_option_name, shipping_address, billing_address, customer_note, tracking_carrier, tracking_number, items:[{product_name, variant_name, sku, quantity, unit_price, line_total, unit_price_display, line_total_display, image_url}]}`.
- Addresses (Plan-11): `GET/POST /api/v1/me/addresses/`, `AddressSerializer` fields `{id, label?, line1, line2, country_code, state_region, area_region, city_text, state_text, postcode, is_default_shipping, is_default_billing}`; required fields per country via `required_fields_for(country)`; `state_region`/`area_region` are Region FK ids. Regions: `GET /api/v1/regions/?country=NG` (states) and `?parent=<id>` (LGAs) → `[{id, name, ...}]` (`apps/delivery/views.py::RegionBrowseView`).
- Auth BFF (Plan-12) `POST /api/auth/[action]`: `login`, `register` (creates account **then** logs in — Django register returns no tokens), `logout`, `refresh`, `me`. Register body `{email, password, first_name, last_name?, phone?, marketing_consent?}`.

## Existing storefront to build on (do not re-plan)

- `src/lib/api.ts` `apiFetch<T>`; `src/lib/session.ts` `fetchWithAuth<T>` / `getAccessToken`; `src/lib/country.ts` `formatMoney(amount, code, symbol)` / `symbolFor` / `DEFAULT_COUNTRY` / `COUNTRY_COOKIE`; `src/lib/auth.ts` cookie names.
- `src/lib/cart-types.ts` `Cart`/`CartLine`/`EMPTY_CART`; `src/hooks/useCart.ts` (`cart`, `addItem`, `setQty` optimistic); `src/lib/cart-ui.ts` (`openCartDrawer`); `src/components/layout/CartDrawer.tsx`.
- BFF: `src/app/api/cart/[[...path]]/route.ts`, `src/app/api/auth/[action]/route.ts`, `src/app/api/checkout/buy-now/route.ts` (Plan-12/13). `BUYNOW_INTENT_KEY = "toke-buynow-intent"` in `src/components/product/BuyButtons.tsx`.
- Design tokens in `globals.css` (`bg-surface/beige/accent/accent-strong`, `text-muted/gold`, `--radius-card`, `font-display`). Skeleton pages this plan **replaces**: `(shop)/cart/page.tsx`, `(shop)/checkout/page.tsx`. New: `(shop)/checkout/confirmation/[number]/page.tsx`.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `backend/apps/checkout/services/quote.py` | pure `quote(...)` assembling Totals + coupon result (+ delivery) | 1 |
| `backend/apps/checkout/views.py` (+`urls.py`) | `QuoteView` (POST, authed, read-only) | 1 |
| `backend/apps/checkout/serializers.py` | `QuoteRequestSerializer` (input validation) | 1 |
| `backend/apps/checkout/tests/test_quote_api.py` | pytest for the quote endpoint | 1 |
| `storefront/src/lib/checkout.ts` | typed fetchers: `getPaymentMethods`, `getDeliveryOptions`, `getQuote`, `getOrder`; types `Totals`/`DeliveryOption`/`PaymentMethod`/`OrderDetail` | 2 |
| `storefront/src/app/api/checkout/quote/route.ts` (+test) | BFF → `/checkout/quote/` (authed; guest cart-only path for cart page returns subtotal-only) | 3 |
| `storefront/src/app/api/checkout/route.ts` (+test) | BFF → `POST /checkout/` (authed, generates `Idempotency-Key`, passes it through) | 3 |
| `storefront/src/components/checkout/OrderSummary.tsx` | totals box (subtotal, discount, delivery, tax, grand total) — reused cart + checkout | 4 |
| `storefront/src/components/checkout/CartView.tsx` + `(shop)/cart/page.tsx` | cart line editors, coupon field (inline errors), free-ship bar, trust badges | 4 |
| `storefront/src/lib/coupon-messages.ts` (+test) | map `error_code` → specific human message | 4 |
| `storefront/src/components/checkout/CheckoutContext.tsx` | shared checkout state (step machine + selections) | 5 |
| `storefront/src/components/checkout/StepShell.tsx` (+test) | one collapsible step (open/complete/summary/Change) | 5 |
| `storefront/src/components/checkout/CheckoutFlow.tsx` + `(shop)/checkout/page.tsx` | flow assembly + gate (empty cart → redirect) | 5 |
| `storefront/src/components/checkout/SignInStep.tsx` + `src/lib/buynow-intent.ts` (+test) | inline signup/login + Buy-Now resume | 6 |
| `storefront/src/components/checkout/AddressStep.tsx` + `RegionSelect.tsx` | address book + per-country add-new form | 7 |
| `storefront/src/components/checkout/DeliveryStep.tsx` | delivery options for chosen address | 8 |
| `storefront/src/components/checkout/PaymentStep.tsx` | payment methods (bank transfer) | 9 |
| `storefront/src/components/checkout/ReviewStep.tsx` + `BankDetails.tsx` + `src/lib/bank-handoff.ts` | review, place order, bank-details screen | 10 |
| `storefront/src/app/(shop)/checkout/confirmation/[number]/page.tsx` | confirmation (order detail + handed-off bank details) | 11 |
| verification | suites, build, Lighthouse, Playwright walkthrough, checkpoint | 12 |

**Task order is a dependency chain:** quote endpoint (1) → fetchers/types (2) → BFF (3) → cart page (4) → flow shell (5) → sign-in (6) → address (7) → delivery (8) → payment (9) → review/place (10) → confirmation (11) → verification (12).

---

### Task 0: Confirm branch

- [ ] **Step 1: Verify branch**

```bash
cd tokecosmetics-platform
git branch --show-current      # must print: plan-14-storefront-checkout
git status --short             # spec commits only; no stray edits
```

---

### Task 1: Backend — `POST /checkout/quote/` (read-only totals + coupon preview)

**Why:** the storefront may not compute money, and no totals/coupon preview endpoint exists (D4-revised). This exposes the existing `compute_totals` + `validate_coupon` (+ optional delivery) as one read-only endpoint. It mutates nothing.

**Files:** Create `apps/checkout/services/quote.py`, `apps/checkout/serializers.py` (if absent), `apps/checkout/tests/test_quote_api.py`; Modify `apps/checkout/views.py`, `apps/checkout/urls.py`.

- [ ] **Step 1: Write the failing test**

Read `apps/checkout/tests/` for the established fixture style first (how a priced, in-stock cart for a user is built). `apps/checkout/tests/test_quote_api.py`:

```python
"""Plan-14: read-only quote endpoint. Reuses compute_totals + validate_coupon; mutates nothing."""
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
class TestQuoteApi:
    def test_requires_auth(self, priced_cart):  # fixture: (user, cart) with >=1 priced line, NG
        res = APIClient().post("/api/v1/checkout/quote/", {"cart_id": str(priced_cart[1].id)}, format="json")
        assert res.status_code in (401, 403)

    def test_returns_totals_for_a_cart(self, priced_cart):
        user, cart = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": str(cart.id)}, format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        t = res.data["totals"]
        assert set(t) == {"subtotal", "discount", "delivery", "tax", "grand_total", "currency"}
        assert t["discount"] == "0.00" and t["delivery"] == "0.00"
        assert res.data["coupon"] == {"ok": True}   # no code supplied → trivially ok

    def test_invalid_coupon_reports_error_code_without_failing(self, priced_cart):
        user, cart = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/",
                     {"cart_id": str(cart.id), "coupon_code": "NOPE"}, format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        assert res.data["coupon"]["ok"] is False and res.data["coupon"]["error_code"] == "not_found"
        assert res.data["totals"]["discount"] == "0.00"   # invalid coupon discounts nothing

    def test_empty_or_foreign_cart_is_404(self, priced_cart):
        user, _ = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": "00000000-0000-0000-0000-000000000000"},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 404
```

If no `priced_cart` fixture exists, add it to `apps/checkout/tests/conftest.py` mirroring the setup in `test_checkout*.py` (active user, active cart with one priced+in-stock variant line in NG).

- [ ] **Step 2: Run to verify failure**

```bash
cd tokecosmetics-platform/backend
uv run pytest apps/checkout/tests/test_quote_api.py -q
```
Expected: FAIL — 404 route / no `quote` view.

- [ ] **Step 3: Implement the pure service**

`apps/checkout/services/quote.py`:

```python
"""Read-only pricing preview for the storefront (Plan-14). Reuses compute_totals +
validate_coupon (+ optional delivery). Places nothing, mutates nothing."""
from __future__ import annotations

from decimal import Decimal

from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals


def _lines(cart):
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


def quote(cart, country, *, user=None, coupon_code="", delivery_amount=Decimal("0.00")):
    """Return {"totals": {...string money...}, "coupon": {"ok": bool, "error_code"?: str}}."""
    lines = _lines(cart)
    # Subtotal first — validate_coupon's min-spend (min_not_met) check needs it.
    base = compute_totals(lines, country)  # no coupon, no delivery
    coupon = None
    coupon_result = {"ok": True}
    if coupon_code:
        v = validate_coupon(code=coupon_code, subtotal=base.subtotal, country=country, user=user, lines=lines)
        if v.ok:
            coupon = v.coupon
        else:
            coupon_result = {"ok": False, "error_code": v.error_code}
    totals = compute_totals(lines, country, delivery_amount=delivery_amount, coupon=coupon)
    return {
        "totals": {
            "subtotal": str(totals.subtotal),
            "discount": str(totals.discount),
            "delivery": str(totals.delivery),
            "tax": str(totals.tax),
            "grand_total": str(totals.grand_total),
            "currency": totals.currency,
        },
        "coupon": coupon_result,
    }
```

> **Before implementing:** open `apps/checkout/services/coupons.py` and confirm `validate_coupon`'s exact keyword signature (the test above assumes `code=/subtotal=/country=/user=/lines=`). If it differs, match the real signature here and in the service call — the bundled code wins.

- [ ] **Step 4: Implement the serializer + view + route**

`apps/checkout/serializers.py` (create or append):

```python
from rest_framework import serializers


class QuoteRequestSerializer(serializers.Serializer):
    cart_id = serializers.CharField()
    coupon_code = serializers.CharField(required=False, allow_blank=True, default="")
    address_id = serializers.IntegerField(required=False)
    delivery_option_id = serializers.IntegerField(required=False)
```

In `apps/checkout/views.py` add (reusing imports already present — `Cart`, `get_object_or_404`, `options_for_address`, `Address`, `compute_totals`):

```python
from apps.checkout.serializers import QuoteRequestSerializer
from apps.checkout.services.quote import quote as quote_service
from decimal import Decimal


class QuoteView(APIView):
    """Read-only totals + coupon preview (Plan-14). Never mutates."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = QuoteRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = get_object_or_404(Cart, pk=v["cart_id"], user=request.user, status="active")
        delivery_amount = Decimal("0.00")
        if v.get("address_id") and v.get("delivery_option_id"):
            address = get_object_or_404(Address, pk=v["address_id"], user=request.user)
            lines = _cart_lines(cart)
            totals = compute_totals(lines, request.country)
            opts = options_for_address(address, lines, totals.subtotal, request.country)
            chosen = next((o for o in opts if o["id"] == v["delivery_option_id"] and o["price"] is not None), None)
            if chosen:
                delivery_amount = Decimal(chosen["price"])
        return Response(quote_service(
            cart, request.country, user=request.user,
            coupon_code=v.get("coupon_code", ""), delivery_amount=delivery_amount,
        ))
```

`apps/checkout/urls.py` — add before `checkout/`:

```python
    path("checkout/quote/", QuoteView.as_view(), name="checkout-quote"),
```
(add `QuoteView` to the import from `apps.checkout.views`).

- [ ] **Step 5: Run the test → green**

```bash
uv run pytest apps/checkout/tests/test_quote_api.py -q
```
Expected: 4 passed.

- [ ] **Step 6: Full backend suite (regression gate)**

```bash
uv run pytest -q
```
Expected: green (was 511 passed / 1 skipped before; now +4).

- [ ] **Step 7: Commit**

```bash
git add apps/checkout/services/quote.py apps/checkout/serializers.py apps/checkout/views.py apps/checkout/urls.py apps/checkout/tests/test_quote_api.py apps/checkout/tests/conftest.py
git commit -m "feat(backend): read-only POST /checkout/quote/ totals+coupon preview (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Storefront — typed checkout fetchers + types (`lib/checkout.ts`)

**Why:** one typed module for every checkout read, mirroring `lib/catalog.ts`. Server-side (uses `apiFetch`/`fetchWithAuth`); pages/BFF import from here.

**Files:** Create `storefront/src/lib/checkout.ts`.

- [ ] **Step 1: Implement (types + fetchers)**

`storefront/src/lib/checkout.ts`:

```ts
import { apiFetch } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface Totals {
  subtotal: string; discount: string; delivery: string;
  tax: string; grand_total: string; currency: string;
}
export interface QuoteResult { totals: Totals; coupon: { ok: boolean; error_code?: string } }
export interface DeliveryOption {
  id: number; name: string; price: string | null;
  eta_min_days: number; eta_max_days: number; quote_required: boolean;
}
export interface PaymentMethod { gateway: string; sort_order: number }
export interface OrderItem {
  product_name: string; variant_name: Record<string, string>; sku: string;
  quantity: number; unit_price: string; line_total: string;
  unit_price_display: string; line_total_display: string; image_url: string | null;
}
export interface OrderDetail {
  number: string; status: string; placed_at: string; currency: string;
  subtotal: string; discount_total: string; shipping_total: string; tax_total: string;
  grand_total: string; grand_total_display: string; delivery_option_name: string | null;
  shipping_address: Record<string, unknown> | null; billing_address: Record<string, unknown> | null;
  customer_note: string; items: OrderItem[];
}

/** Public (AllowAny) — safe with apiFetch + country. */
export async function getPaymentMethods(country: string) {
  return apiFetch<PaymentMethod[]>(`/checkout/payment-methods/?country=${country}`, {
    country, cache: "no-store",
  });
}
/** Authed. */
export async function getDeliveryOptions(addressId: number, cartId: string, country: string) {
  return fetchWithAuth<DeliveryOption[]>(
    `/checkout/delivery-options/?address_id=${addressId}&cart_id=${cartId}`,
    { country, cache: "no-store" });
}
export async function getOrder(number: string, country: string) {
  return fetchWithAuth<OrderDetail>(`/orders/${number}/`, { country, cache: "no-store" });
}
```

- [ ] **Step 2: Typecheck**

```bash
cd tokecosmetics-platform/storefront && npx tsc --noEmit -p tsconfig.json 2>&1 | grep checkout.ts || echo "no errors in checkout.ts"
```
Expected: no errors in `checkout.ts` (pre-existing unrelated test-file debt may print — ignore anything not in `src/lib/checkout.ts`).

- [ ] **Step 3: Commit**

```bash
git add src/lib/checkout.ts
git commit -m "feat(storefront): typed checkout fetchers + types (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Storefront BFF — `/api/checkout/quote` + `/api/checkout` (place order)

**Why:** the browser calls these same-origin routes; they attach the Bearer server-side. The place-order route generates the `Idempotency-Key`.

**Files:** Create `src/app/api/checkout/quote/route.ts` (+ `__tests__/quote.test.ts`), `src/app/api/checkout/route.ts` (+ `__tests__/place.test.ts`).

- [ ] **Step 1: Quote BFF — failing test first**

`src/app/api/checkout/__tests__/quote.test.ts` (mirror the `buy-now.test.ts` mock exactly — same `next/headers` cookie mock, `upstream()` helper):

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { POST } from "@/app/api/checkout/quote/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (b: unknown) => new Request("http://localhost:3000/api/checkout/quote", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

describe("quote BFF", () => {
  it("forwards to /checkout/quote/ with Bearer + country and returns totals", async () => {
    const f = upstream(200, { totals: { grand_total: "100.00" }, coupon: { ok: true } });
    const res = await POST(req({ cart_id: "c1", coupon_code: "SAVE" }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/quote/");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
  });
  it("401 without a session", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(req({ cart_id: "c1" }));
    expect(res.status).toBe(401); expect(f).not.toHaveBeenCalled();
  });
});
```

`src/app/api/checkout/quote/route.ts`:

```ts
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(d: unknown, s = 200) {
  return new Response(JSON.stringify(d), { status: s, headers: { "content-type": "application/json" } });
}
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) return json({ detail: "Not authenticated." }, 401);
  const body = await req.json().catch(() => ({}));
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    return json(await fetchWithAuth("/checkout/quote/", { method: "POST", country, body }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

Run red → green: `npm run test -- --run src/app/api/checkout/__tests__/quote.test.ts`.

- [ ] **Step 2: Place-order BFF — failing test first**

`src/app/api/checkout/__tests__/place.test.ts` (same mock harness). Assert: forwards to `/checkout/` with an `Idempotency-Key` header present and non-empty; forwards the body; returns the upstream body/status; 401 without session; passes through a `CheckoutError` body+status (e.g. 409).

```ts
// ...same imports + mock as quote.test.ts...
import { POST } from "@/app/api/checkout/route";
// happy path:
it("attaches an Idempotency-Key and forwards the order body", async () => {
  const f = upstream(201, { order_number: "TC-1", payment: { gateway: "bank_transfer", action: "bank_details", data: {} } });
  const res = await POST(req({ cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer" }));
  expect(res.status).toBe(201);
  const [, init] = f.mock.calls[0];
  const h = new Headers((init as RequestInit).headers);
  expect(h.get("Idempotency-Key")).toBeTruthy();
});
it("passes a CheckoutError status/body straight through", async () => {
  upstream(409, { error: "idempotency_in_progress" });
  const res = await POST(req({ cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer" }));
  expect(res.status).toBe(409);
});
```

`src/app/api/checkout/route.ts`:

```ts
import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(d: unknown, s = 200) {
  return new Response(JSON.stringify(d), { status: s, headers: { "content-type": "application/json" } });
}
/** Place order (Plan-14). Authed; generates the Idempotency-Key server-side so a
 * double-click can't double-charge. Bank-transfer details ride back in payment.data. */
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) return json({ detail: "Not authenticated." }, 401);
  const body = await req.json().catch(() => ({}));
  if (!body.cart_id || !body.address_id || !body.delivery_option_id || !body.payment_gateway) {
    return json({ detail: "Missing checkout fields." }, 400);
  }
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const out = await fetchWithAuth("/checkout/", {
      method: "POST", country, body,
      headers: { "Idempotency-Key": randomUUID() },
    });
    return json(out, 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

> **Before implementing:** confirm `ApiFetchOptions` in `src/lib/api.ts` forwards a `headers` field to the upstream fetch. If it does not, add a minimal `headers?: Record<string,string>` passthrough in `apiFetch` (merged after `X-Country`/`Authorization`) — this is the only change allowed to `api.ts` and must not alter existing behavior; add a one-line test if you touch it.

Run red → green: `npm run test -- --run src/app/api/checkout`.

- [ ] **Step 3: Commit**

```bash
git add src/app/api/checkout/quote src/app/api/checkout/route.ts src/app/api/checkout/__tests__ src/lib/api.ts
git commit -m "feat(storefront): checkout BFF — quote + idempotent place-order proxies (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Cart page — line editors, coupon field, totals, free-shipping bar

**Why:** the `/cart` destination. Reuses `useCart` for line mutations; totals + coupon come from the quote BFF (no client money math).

**Files:** Create `src/lib/coupon-messages.ts` (+`__tests__/coupon-messages.test.ts`), `src/components/checkout/OrderSummary.tsx`, `src/components/checkout/CartView.tsx`; Modify `src/app/(shop)/cart/page.tsx`.

- [ ] **Step 1: Coupon messages — failing test first**

`src/lib/__tests__/coupon-messages.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { couponMessage } from "@/lib/coupon-messages";

describe("couponMessage", () => {
  it("maps known codes to specific copy", () => {
    expect(couponMessage("not_found")).toMatch(/isn.t a valid code|not.*valid/i);
    expect(couponMessage("expired")).toMatch(/expired/i);
    expect(couponMessage("min_not_met")).toMatch(/minimum/i);
  });
  it("has a safe fallback for unknown codes", () => {
    expect(couponMessage("something_new")).toMatch(/couldn.t apply|try again/i);
  });
});
```

`src/lib/coupon-messages.ts`:

```ts
/** Specific, human coupon errors (backend error_code -> copy). Keep in sync with
 * validate_coupon's codes: not_found, inactive, not_started, expired, min_not_met,
 * wrong_currency, exhausted, user_exhausted, not_valid_for_items. */
const MESSAGES: Record<string, string> = {
  not_found: "That isn't a valid code.",
  inactive: "That code isn't active.",
  not_started: "That code isn't active yet.",
  expired: "That code has expired.",
  min_not_met: "Your bag doesn't meet this code's minimum spend.",
  wrong_currency: "That code isn't valid in your currency.",
  exhausted: "That code has been fully redeemed.",
  user_exhausted: "You've already used that code.",
  not_valid_for_items: "That code doesn't apply to the items in your bag.",
};
export function couponMessage(code: string): string {
  return MESSAGES[code] ?? "We couldn't apply that code — please try again.";
}
```

Run red → green.

- [ ] **Step 2: OrderSummary (totals box)**

`src/components/checkout/OrderSummary.tsx` — presentational; takes a `Totals | null` and renders rows (Subtotal / Discount (−) / Delivery / Tax / Grand total), each via `formatMoney(value, totals.currency, symbolFor(totals.currency))`. When `totals` is null show a subtotal-only fallback from the cart. Discount row hidden when `discount === "0.00"`. No arithmetic.

```tsx
import { formatMoney, symbolFor } from "@/lib/country";
import type { Totals } from "@/lib/checkout";

export function OrderSummary({ totals, fallbackSubtotal, currency }: {
  totals: Totals | null; fallbackSubtotal: string; currency: string;
}) {
  const sym = symbolFor(currency);
  const Row = ({ label, value, strong = false, neg = false }: { label: string; value: string; strong?: boolean; neg?: boolean }) => (
    <div className={`flex justify-between ${strong ? "font-medium text-base" : "text-sm text-muted"}`}>
      <span>{label}</span><span>{neg ? "−" : ""}{formatMoney(value, currency, sym)}</span>
    </div>
  );
  if (!totals) return <div className="space-y-2"><Row label="Subtotal" value={fallbackSubtotal} /></div>;
  return (
    <div className="space-y-2">
      <Row label="Subtotal" value={totals.subtotal} />
      {totals.discount !== "0.00" && <Row label="Discount" value={totals.discount} neg />}
      <Row label="Delivery" value={totals.delivery} />
      <Row label="Tax" value={totals.tax} />
      <div className="mt-2 border-t border-line pt-2"><Row label="Total" value={totals.grand_total} strong /></div>
    </div>
  );
}
```

- [ ] **Step 3: CartView (client) + `/cart` page**

`src/components/checkout/CartView.tsx` (`"use client"`): uses `useCart()` for lines + `setQty` (qty editors, remove via qty 0); a coupon `<input>` + Apply that POSTs `/api/checkout/quote` with `{cart_id, coupon_code}` and shows `couponMessage(error_code)` on failure or the discounted `OrderSummary` on success; a free-shipping progress bar **only** when a `free_over` signal exists (derive from a successful quote where `delivery==="0.00"` is not enough — instead show the bar when the cart page has a `free_over` value; since the cart has no address yet, show the bar only if the quote's delivery info exposes it — if not available without an address, omit the bar on the cart page and show it in the DeliveryStep instead). Trust badges row (static). "Proceed to checkout" → `/checkout`. Empty cart → friendly empty state + link to `/products`.

> **Scope note:** `free_over` is a per-delivery-option field and needs an address to resolve. On the **cart page** (no address yet) show subtotal + coupon + a "Delivery & taxes calculated at checkout" line; the free-shipping progress bar and full totals live in the **checkout DeliveryStep/summary**, where an address exists. This keeps the cart page honest and avoids client money math. (Update the spec's cart bullet to match if a reviewer flags it.)

`src/app/(shop)/cart/page.tsx`:

```tsx
import type { Metadata } from "next";
import { CartView } from "@/components/checkout/CartView";
export const metadata: Metadata = { title: "Your bag", robots: { index: false } };
export default function CartPage() {
  return <section className="mx-auto max-w-5xl px-4 py-10"><h1 className="font-display text-3xl">Your bag</h1><CartView /></section>;
}
```

- [ ] **Step 4: Unit test the coupon interaction**

`src/components/checkout/__tests__/CartView.test.tsx` — render with a mocked `useCart` (one line) and a mocked `fetch` for `/api/checkout/quote`; type an invalid code → Apply → assert the specific message renders; a valid code → assert the discount row appears. (Mirror the RTL setup used in existing component tests, e.g. `src/components/product/__tests__/`.)

- [ ] **Step 5: Run + commit**

```bash
npm run test -- --run src/lib/__tests__/coupon-messages.test.ts src/components/checkout
git add src/lib/coupon-messages.ts src/lib/__tests__/coupon-messages.test.ts src/components/checkout/OrderSummary.tsx src/components/checkout/CartView.tsx src/components/checkout/__tests__ "src/app/(shop)/cart/page.tsx"
git commit -m "feat(storefront): cart page — line editors, coupon (server-validated), totals box (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Checkout flow shell — context, StepShell, gate

**Why:** the state machine every step plugs into. One open step at a time; completing a step collapses it to a summary with "Change" and opens the next.

**Files:** Create `src/components/checkout/CheckoutContext.tsx`, `StepShell.tsx` (+`__tests__/StepShell.test.tsx`), `CheckoutFlow.tsx`; Modify `src/app/(shop)/checkout/page.tsx`.

- [ ] **Step 1: CheckoutContext**

`CheckoutContext.tsx` (`"use client"`): a context holding `{ currentStep, completed:Set<number>, open(step), complete(step), selections }` where `selections = { user?, addressId?, deliveryOptionId?, paymentGateway?, note }`. Steps: `1 SignIn, 2 Address, 3 Delivery, 4 Payment, 5 Review`. `complete(n)` marks n done and sets currentStep to the next incomplete step; `open(n)` reopens n (used by "Change"). Delivery selection resets when `addressId` changes (clear `deliveryOptionId` + step-3 completion).

- [ ] **Step 2: StepShell — failing test first**

`__tests__/StepShell.test.tsx`: renders a shell with title + children; when not current and not complete → body hidden, no Change; when complete → shows the one-line `summary` + a "Change" button that calls `onChange`; when current → body visible. (RTL.)

Implement `StepShell.tsx` accordingly (semantic: numbered heading, `aria-expanded`, keyboard-focusable Change button).

- [ ] **Step 3: CheckoutFlow + page gate**

`CheckoutFlow.tsx` (`"use client"`): wraps the 5 step components in `CheckoutContext`; renders `OrderSummary` in a sticky aside (desktop) / collapsible (mobile). On mount, if the cart (from `useCart`) is empty → render an empty state linking to `/products` (do not hard-redirect; a just-placed order also empties the cart and we don't want a flash — gate on "empty AND no order in flight").

`src/app/(shop)/checkout/page.tsx`:

```tsx
import type { Metadata } from "next";
import { CheckoutFlow } from "@/components/checkout/CheckoutFlow";
export const metadata: Metadata = { title: "Checkout", robots: { index: false } };
export default function CheckoutPage() {
  return <section className="mx-auto max-w-6xl px-4 py-10"><h1 className="sr-only">Checkout</h1><CheckoutFlow /></section>;
}
```

- [ ] **Step 4: Run + commit**

```bash
npm run test -- --run src/components/checkout/__tests__/StepShell.test.tsx
git add src/components/checkout/CheckoutContext.tsx src/components/checkout/StepShell.tsx src/components/checkout/CheckoutFlow.tsx src/components/checkout/__tests__/StepShell.test.tsx "src/app/(shop)/checkout/page.tsx"
git commit -m "feat(storefront): checkout flow shell — step machine + StepShell + gate (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Step 1 — sign-in / inline signup + Buy-Now resume

**Why:** the authed backend forces a logged-in user before placement. Logged-in users skip; guests create an account silently.

**Files:** Create `src/lib/buynow-intent.ts` (+`__tests__`), `src/components/checkout/SignInStep.tsx`.

- [ ] **Step 1: Buy-Now intent lib — failing test first**

`src/lib/__tests__/buynow-intent.test.ts`: `readBuyNowIntent()` returns the parsed `{variant_id, quantity}` from `sessionStorage["toke-buynow-intent"]` and `clearBuyNowIntent()` removes it; survives corrupt JSON (returns null). Implement `src/lib/buynow-intent.ts` using `BUYNOW_INTENT_KEY` (import the constant from `@/components/product/BuyButtons` or re-declare the literal with a comment — pick re-export to keep one source of truth).

- [ ] **Step 2: SignInStep**

`SignInStep.tsx` (`"use client"`): on mount check `/api/auth/me` (via a light fetch) → if logged in, mark step complete with a "Signed in as <email>" summary. Otherwise render email + first name + password; submit → `POST /api/auth/register` (which auto-logs-in). If register returns an "email exists" error → flip to email + password and submit `POST /api/auth/login`. On success: if a Buy-Now intent exists, POST it to `/api/checkout/buy-now` then `clearBuyNowIntent()`, and refetch the cart (TanStack invalidate) so the item is present; complete the step.

> Reuse the exact register/login error shapes from the Plan-11 auth flow — read `src/app/(auth)/register/page.tsx` and `login/page.tsx` for the field-error rendering pattern and copy it; do not invent new error UI.

- [ ] **Step 3: Run + commit**

```bash
npm run test -- --run src/lib/__tests__/buynow-intent.test.ts
git add src/lib/buynow-intent.ts src/lib/__tests__/buynow-intent.test.ts src/components/checkout/SignInStep.tsx
git commit -m "feat(storefront): checkout step 1 — inline signup/login + Buy-Now resume (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Step 2 — delivery address (book + per-country add-new)

**Why:** placement needs an owned `address_id`; delivery options key off it.

**Files:** Create `src/components/checkout/AddressStep.tsx`, `src/components/checkout/RegionSelect.tsx`.

- [ ] **Step 1: RegionSelect**

`RegionSelect.tsx` (`"use client"`): given a `country`, fetches states via the BFF/`apiFetch` proxy for `/regions/?country=<CC>` and, on state pick, LGAs via `/regions/?parent=<id>`. Two dependent `<select>`s labelled by the country's `area_label` (NG: State / LGA). Emits `{ state_region, area_region }` ids. (If no `/api/regions` BFF exists, add a tiny `src/app/api/regions/route.ts` GET proxy — public data, no auth — mirroring the newsletter route shape.)

- [ ] **Step 2: AddressStep**

`AddressStep.tsx` (`"use client"`): fetch `/me/addresses/` (through a BFF or a server action — reuse the Plan-11 address list mechanism if one exists; otherwise add `GET` to an `/api/addresses` BFF). Render saved addresses as selectable cards (radio); "Add new address" reveals the structured form: `line1`, `line2?`, `city_text`/`state_text` per `required_fields_for(country)`, `RegionSelect` for NG, country locked to the shopping country with the "changing country restarts pricing" note. Submit → `POST /me/addresses/` (via BFF), select the new address, `complete(2)`. Selecting any address sets `selections.addressId` and completes the step (which resets any step-3 selection).

> Reuse Plan-11's address form/validation if components exist under `src/components/account/` — read that dir first and extend rather than duplicate.

- [ ] **Step 3: Commit** (no new unit test if it's thin glue over reused components; otherwise add an RTL test for the add-new happy path)

```bash
git add src/components/checkout/AddressStep.tsx src/components/checkout/RegionSelect.tsx src/app/api/regions src/app/api/addresses 2>/dev/null
git commit -m "feat(storefront): checkout step 2 — address book + per-country add-new form (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Step 3 — delivery options

**Files:** Create `src/components/checkout/DeliveryStep.tsx`.

- [ ] **Step 1: DeliveryStep**

`"use client"`: when `selections.addressId` is set, fetch delivery options via a BFF proxy `GET /api/checkout/delivery-options?address_id=&cart_id=` (add `src/app/api/checkout/delivery-options/route.ts` mirroring the quote BFF — authed passthrough). Render radio cards: name, price (`formatMoney`) or "Calculated after checkout" when `quote_required`, ETA ("`eta_min`–`eta_max` days"). Selecting one sets `selections.deliveryOptionId` and completes the step. Re-fetches whenever `addressId` changes (and the context already cleared the old selection).

- [ ] **Step 2: Commit**

```bash
git add src/components/checkout/DeliveryStep.tsx src/app/api/checkout/delivery-options
git commit -m "feat(storefront): checkout step 3 — delivery options for the chosen address (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Step 4 — payment method

**Files:** Create `src/components/checkout/PaymentStep.tsx`, `src/lib/payment-labels.ts`.

- [ ] **Step 1: payment labels**

`src/lib/payment-labels.ts`: map gateway code → display name/subtitle, e.g. `bank_transfer → { name: "Bank transfer", note: "Pay by transfer; we confirm your order once received." }`, plus `paystack/flutterwave/paypal` entries ready for 14b (rendered only if they appear from the API).

- [ ] **Step 2: PaymentStep**

`"use client"`: fetch `/checkout/payment-methods/?country=` (public — can go through `apiFetch` in a small `/api/checkout/payment-methods` BFF, or directly if a public proxy exists). Render active methods as radio cards using `payment-labels`. Only `bank_transfer` is active now → it renders as the single option and is preselected. Selecting sets `selections.paymentGateway` and completes the step.

- [ ] **Step 3: Commit**

```bash
git add src/components/checkout/PaymentStep.tsx src/lib/payment-labels.ts src/app/api/checkout/payment-methods 2>/dev/null
git commit -m "feat(storefront): checkout step 4 — payment method (bank transfer live) (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Step 5 — review, place order, bank-details screen

**Why:** the terminal step. Shows the authoritative quote (with chosen delivery), places the order idempotently, then shows the bank details and hands them to the confirmation page.

**Files:** Create `src/lib/bank-handoff.ts` (+`__tests__`), `src/components/checkout/BankDetails.tsx`, `src/components/checkout/ReviewStep.tsx`.

- [ ] **Step 1: bank-handoff lib — failing test first**

`src/lib/__tests__/bank-handoff.test.ts`: `stashBankHandoff(number, data)` writes to `sessionStorage["toke-bank-handoff"]` keyed by number; `readBankHandoff(number)` returns it (and null for a different/absent number, and on corrupt JSON). Implement `src/lib/bank-handoff.ts`.

- [ ] **Step 2: BankDetails (presentational)**

`BankDetails.tsx`: renders the `payment.data` bank block — the `display` map (Bank / Account name / Account number / any extra), the `reference`, `instructions`, and the exact amount (`grand_total` passed in, `formatMoney`). A copy-to-clipboard button per value is a nice-to-have (keyboard accessible).

- [ ] **Step 3: ReviewStep**

`"use client"`: on becoming current, POST `/api/checkout/quote` with `{cart_id, address_id, delivery_option_id, coupon_code}` to get the authoritative `Totals`; render the full summary (items from cart, address summary, delivery name, `OrderSummary` with these totals), an optional note field, and a single **Place order** button. On click → POST `/api/checkout` with `{cart_id, address_id, delivery_option_id, payment_gateway, coupon_code, notes, expected_total: totals.grand_total}`. On `201`: `stashBankHandoff(order_number, payment.data)`, then `router.push('/checkout/confirmation/' + order_number)`. On error: map `error` codes to messages — `409 idempotency_in_progress` → "Still processing your last attempt…"; `CheckoutError` (e.g. out-of-stock line) → show `detail` and point back to the cart; reservation-expired code → "Your reserved items expired — your bag is intact; please review and try again" and reopen step 5. Disable the button while in flight (no double-submit; the server key also guards it).

- [ ] **Step 4: Run + commit**

```bash
npm run test -- --run src/lib/__tests__/bank-handoff.test.ts
git add src/lib/bank-handoff.ts src/lib/__tests__/bank-handoff.test.ts src/components/checkout/BankDetails.tsx src/components/checkout/ReviewStep.tsx
git commit -m "feat(storefront): checkout step 5 — review, idempotent place order, bank details (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Confirmation page

**Files:** Create `src/app/(shop)/checkout/confirmation/[number]/page.tsx`, `src/components/checkout/ConfirmationView.tsx`.

- [ ] **Step 1: Page (server) + client view**

Page (server component): `params` is a Promise (`await`); fetch the order via `getOrder(number, country)` server-side (authed). If it 404s (not the owner / not logged in) → `notFound()`. `robots: { index:false }`. Render order number, status, items (with `line_total_display`), totals from the order fields (`subtotal`, `discount_total`, `shipping_total`, `tax_total`, `grand_total_display`), delivery name, shipping address, a "what happens next" note, and a `<ConfirmationView number=… />` client island that reads `readBankHandoff(number)` and renders `BankDetails` when present (fresh placement). For a guest who just signed up, a "your account is ready — you can track this order in your account" note.

- [ ] **Step 2: Commit**

```bash
git add "src/app/(shop)/checkout/confirmation"
git commit -m "feat(storefront): order confirmation page + handed-off bank details (Plan-14)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Verification checkpoint 🚦

**Why:** prove the whole flow on a production build, then Hammed places a real bank-transfer order. **No new feature code.**

- [ ] **Step 1: Suites + lint + builds**

```bash
cd tokecosmetics-platform/storefront && npm run test -- --run && npm run lint && npm run build
cd ../backend && uv run pytest -q
```
All green; build clean.

- [ ] **Step 2: Production server + backend (seeded)**

Terminal A: `cd backend && uv run python manage.py runserver 0.0.0.0:8000`. Terminal B: `cd storefront && npm start`. Ensure a `BankAccount` is active for NG (Plan-09b seed / admin) so bank-transfer initiation returns details.

- [ ] **Step 3: Driven walkthrough (Playwright MCP — the hydrating browser; NOT the preview pane)**

Record each: (a) NEW customer — add to cart → `/checkout` → inline signup → add NG address (State→LGA) → pick delivery → bank transfer → review shows correct grand total incl. tax → Place order → bank details screen → confirmation shows order number + bank details; confirm a pending order exists in the backend (`manage.py shell` or admin). (b) Returning customer checkout. (c) Buy-Now while logged out → `/login?next=/checkout` → signup → item still in the bag → complete. (d) Invalid coupon on the cart shows the specific message; valid coupon shows the discount row. (e) Mobile 375px: no horizontal scroll on cart + checkout. (f) A UK address shows UK delivery options vs NG's LGA-based ones.

- [ ] **Step 4: Lighthouse (mobile) on cart + checkout**

```bash
npx --yes lighthouse http://localhost:3000/cart --form-factor=mobile --screenEmulation.mobile --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lighthouse-cart.json
```
Gate: performance ≥ 90, accessibility ≥ 95 (checkout carries no 3rd-party JS in this plan). Record scores. Commit the JSON artefacts.

- [ ] **Step 5: 🚦 CHECKPOINT — Hammed places a real bank-transfer order on his phone**

Present the walkthrough recording + Lighthouse. **Hammed does the new-customer inline-signup purchase himself**, reaches confirmation with bank details shown, and confirms the pending order in the backend. Blocks merge. On sign-off: use superpowers:finishing-a-development-branch to merge `plan-14-storefront-checkout` → `main` (no push without his say-so). Then Plan-14b (gateways).

---

## Self-review

- **Spec coverage:** cart page (Task 4), 5-step checkout (5–10), inline signup + Buy-Now resume (6), address per-country (7), delivery options (8), payment/bank transfer (9), review+place+bank details (10), confirmation + bank handoff (11), quote endpoint / D4 (1), no client money math (OrderSummary + quote), verification incl. Hammed test purchase (12). Deferred-by-spec: customer cancel + persistent bank re-show (Plan-15) — intentionally absent. Free-shipping bar relocated cart→checkout where an address exists (noted in Task 4; reconcile the spec's cart bullet during review).
- **Placeholder scan:** every code step carries real code or names the exact file to mirror (auth error UI, Plan-11 address components, RTL setup) with what must hold true — deliberate, matching Plan-13's style for reused patterns.
- **Type consistency:** `Totals`/`DeliveryOption`/`PaymentMethod`/`OrderDetail` defined in Task 2 and used verbatim in 3/4/8/9/10/11; `selections` keys (`addressId`/`deliveryOptionId`/`paymentGateway`) consistent across 5–10; BFF routes return upstream status/body unchanged; `Idempotency-Key` generated once in the place BFF (Task 3) and asserted in its test.
- **Backend footprint:** exactly one additive read-only endpoint (Task 1) + at most a `headers` passthrough in `api.ts` (Task 3, gated on a check). No other backend edits.
