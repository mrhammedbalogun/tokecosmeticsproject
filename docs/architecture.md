# Architecture

Living overview of the Tokecosmetics platform. Source of truth for decisions is
`master-tokerebuild.md`; this file stays current as the build progresses.

## Goal

Replace two WordPress/WooCommerce stores (NG + international) with **one** global
e-commerce platform: a Next.js storefront and admin portal on Vercel, backed by a
Django REST API on the Namecheap VPS. Country/currency behaviour is **data-driven** —
adding a country = adding rows, never code.

## Target architecture

```
 Cloudflare (DNS/proxy, TLS)
   ├── tokecosmetics.com (storefront, after cutover)      → Vercel
   ├── next.tokecosmetics.com (storefront UAT)            → Vercel
   ├── backend.tokecosmetics.com (admin portal)           → Vercel
   └── api.tokecosmetics.com (Django REST API)            → VPS

 VPS (203.161.38.201) — Docker Compose under /opt/tokecosmetics:
   django-web (gunicorn) · celery-worker · celery-beat · postgres:16 · redis:7 · meilisearch
   (+ the existing live WP stack, until cutover)

 External: AWS S3 (media) · Mailgun (+SES fallback) · Paystack/Flutterwave/Stripe/PayPal
```

## Tech stack (pinned)

- **Backend:** Python 3.12, Django 5.2 LTS, DRF, SimpleJWT, drf-spectacular, Celery+Redis,
  django-anymail (Mailgun/SES), django-storages (S3), Meilisearch. Managed with **uv**.
- **Frontend:** Next.js (App Router, TypeScript), Tailwind, shadcn/ui, TanStack Query,
  React Hook Form + Zod. BFF pattern — tokens live in httpOnly cookies, never in the browser.
- **Infra:** Docker Compose on the VPS; Vercel for both Next.js apps; GitHub Actions CI/CD.

## Monorepo layout

```
backend/     Django project (config/ + apps/*), uv-managed
storefront/  Next.js customer site   → Vercel
admin/       Next.js admin portal    → Vercel (backend.tokecosmetics.com)
infra/       docker-compose.prod.yml, proxy config, deploy scripts   (Plan-02)
docs/        audit.md, architecture.md, runbooks, plans
.github/     CI workflows
docker-compose.dev.yml   local dev services (postgres/redis/meilisearch)
```

## Key decisions (from master guide §4 — do not relitigate)

1. **MVP scope = Plans 00–27.** Deferred (not forgotten): accounting, loyalty/points,
   referrals, gift cards, abandoned-cart *emails*, blog, recommendations, bundles,
   subscriptions, social login, staff 2FA, carrier APIs (DHL/GIG).
2. **One database, data-driven countries.** `Country`/`Currency` are rows. NG/GB/US/CA seeded
   + a "Rest of World" (`ZZ`) context (USD, can check out worldwide).
3. **Explicit prices per currency** (NGN/GBP/USD/CAD) — no auto FX at launch. Sale + scheduled
   prices supported. One `resolve_price` service is the only way any code gets a price.
4. **One inventory, multiple warehouses.** Stock is per-warehouse; each warehouse declares the
   countries it serves; per-country availability is computed. Checkout **reserves** stock
   (row-level locks), payment **commits**, expiry **releases** — kills overselling.
5. **Auth = SimpleJWT** (15-min access / 30-day rotating refresh + blacklist), BFF httpOnly
   cookies. **Checkout requires an account** (inline 30-second signup in checkout step 1).
6. **Payments:** Paystack + Flutterwave (NGN), Stripe (+Apple/Google Pay) + PayPal (intl),
   bank transfer (NG). Gateway-per-country is admin-managed data.
7. **Delivery:** region tree per country (NG seeded with 36 states + FCT + 774 LGAs); admin
   delivery options cover any tree level (mixed granularity). Carrier APIs are post-launch stubs.
8. **Order numbers:** new `TC-<seq>` from 100001; migrated orders keep their legacy number.
9. **Toke ID:** every user gets a public `TK-XXXXXX` id (unambiguous alphabet).
10. **Deploys:** GitHub Actions → SSH → `git pull && docker compose up -d --build`.

## Plan-00 audit deltas (things that changed the plan — see docs/audit.md)

- **Order migration has THREE sources**, not two: current NG (`wp481.wp_`, 2,789), **old NG**
  (`wp481.wp8n_`, 879, 2023–2025 — newly found), intl (`usawp100.wp8n_`, 119).
- **SKUs barely exist** (NG 1, intl 0) → generate SKUs for all variants. **Stock barely tracked**
  → Lagos + UK warehouse counts entered **manually**; no reliable WP stock to import.
- **Coupons: start fresh** (Hammed) — migrate none; ~13k existing are bulk-generated junk.
- **Loyalty points: not preserved** (Hammed) — balances lapse; loyalty starts at zero (Plan-29).
- **No SEO plugin** existed → Plan-13 SEO is net-new. Permalinks `/%postname%/`,
  product base `/product`, category base `/product-category`.
- Product write-ups are **Elementor**-built; ingredients/directions/warnings may need manual
  re-entry into structured fields.
- Passwords are all `$wp$`/`$P$` → the WordPress hasher (Plan-22) covers 100% of users.

## Current status

Plan-00 (audit) ✅ · Plan-01 (scaffold) ✅ · Plan-03 (django-core) ✅ — custom User + Toke ID,
Region/Address, SimpleJWT auth (register/login/refresh/logout/me/password-reset), email via
Resend (sole provider, no fallback), Celery, S3/whitenoise storage, prod security baseline,
OpenAPI at `/api/docs/`.
Real smokes done 2026-07-15: live Resend email delivered + live S3 upload round-trip — both green.

Plan-04 (countries-pricing) ✅ — Currency/Country + seed (NG default, ZZ Rest of World),
X-Country middleware (`request.country`), public `/api/v1/meta/countries/`. Pricing app written
(`Price` + `resolve_price`) but its DB migration + full resolution tests are deferred to the start
of Plan-05 (FK to `catalog.ProductVariant`).

Plan-05a (catalog foundation) ✅ — catalog models (Category/Brand/Tag/Collection, Product,
ProductVariant, ProductImage/Video), pricing app ACTIVATED (`Price` migrated, full `resolve_price`
DB tests green), factory_boy factories, Django-admin registration.

Plan-05b (catalog read APIs) ✅ — public country-aware product list (filters/ordering/sellability),
product detail (per-country variant prices), categories tree / brands / collection detail, 60s
response cache with version-bump invalidation, N+1 budget (5 queries / 24-product page). Stubs
pending later plans: stock/`in_stock` (Plan-06), full-text search (Plan-07), `best_selling`
order (Plan-10). 65 backend tests green in CI.

Plan-05c (catalog admin write) ✅ — staff-only CRUD for all catalog + price models, product image
upload to S3, product CSV export + import (Celery job with row-level error report). Public read
cache auto-invalidates on admin writes via the existing signals. **Plan-05 (catalog) COMPLETE.**
74 backend tests green in CI. **Next: Plan-06 (inventory).**

Plan-06 (inventory) ✅ — Warehouse/StockItem/StockMovement with an oversell `CHECK` constraint,
seeded Lagos HQ + UK Warehouse, race-safe `reserve`/`release`/`commit_sale`/`adjust` services
(pk-ordered locks, ledger-idempotent), **Postgres concurrency test** (two threads, last unit,
exactly one wins), admin stock API (list/adjust-with-reason+note/history), hourly low-stock digest,
and real `in_stock` wired into the storefront (stock writes bust the catalog cache). Reservation
design reviewed with Fable 5.

Plan-06b (stock CSV) ✅ — admin stock CSV export + import (imports mutate stock only via the
ledgered `adjust()` service).

Plan-07 (search) ✅ — Postgres trigram product search + autocomplete (`/api/v1/search/`,
`/search/suggest/`), typo-tolerant, country-aware filters (category/brand/price/in_stock),
results reuse the product-list card shape, throttled. Structured behind `get_backend()` so
Meilisearch is a drop-in later (Plan-07b, deferred for RAM). Design reviewed with Fable 5.
103 backend tests green. **Next: Plan-08 (cart/checkout).**

### Decisions (2026-07-15)
- **Test DB = PostgreSQL** for the whole suite (dev via docker-compose, CI via service container).
  SQLite's `select_for_update` is a no-op, so the Plan-06 stock-reservation race test is only
  meaningful on Postgres. Plan-06 opens by switching the test DB. (Advice validated with Fable 5.)
- **Cloudflare (Plan-02) is NOT a blocker** — approach settled: Hammed drives the Cloudflare
  dashboard with step-by-step guidance from Claude (add `api` A record → VPS proxied, Origin CA
  cert, SSL Full-strict, origin-port rule). Done as a guided step *inside* Plan-02 execution, when
  the Docker API stack is up (pointing DNS before the server listens would just 5xx). Plan-02 can be
  scheduled whenever Hammed wants to go live with the API; it no longer waits on anything.

## Notes / limitations to record as we go

- Single locale (en) at launch; prices via `Intl.NumberFormat` per currency; hreflang omitted.
- US/CA sales-tax-by-state is out of MVP scope — flat configurable rate per country (`Country.tax_rate_percent`).
- `request.country` is set by `CountryMiddleware` from the `X-Country` header; missing → NG (default),
  unknown/inactive → ZZ (Rest of World). All price/tax context flows from this.
- Reports are per-currency (no FX consolidation) in the MVP.

## Coupons & Totals (Plan-08c)

New independent domain app `apps.checkout` holds pure logic (no HTTP, no URLs, no import of
carts/delivery/orders). It is the single source of truth for order money.

**`compute_totals(items, country, delivery_amount=0, coupon=None) -> Totals`** — the ONLY place
money is calculated (cart display, checkout, and order creation all call it, so they can never
disagree). `items` is an iterable of `(ProductVariant, qty)`. Order of operations:

1. **Subtotal** — each line is re-resolved via `pricing.services.resolve_price` (snapshots are
   display-only, never trusted), rounded **half-up per line** (`q2()`, `ROUND_HALF_UP`, 2dp),
   then summed. An unpriced line raises `ValueError`.
2. **Discount** — applied to the subtotal; `free_shipping` discounts nothing here; a discount
   never exceeds the subtotal (fixed coupons are capped at subtotal → grand total floors at 0).
3. **Delivery** — the caller-resolved `delivery_amount` (via `apps.delivery`); a `free_shipping`
   coupon zeroes it.
4. **Tax** — computed on `subtotal − discount`. If `country.prices_include_tax` the tax is the
   **extracted** portion already inside the price (`taxable − taxable/(1+r)`; grand total does not
   add it again). Otherwise tax is **added on top** (`taxable × r`).

**Coupon validation** — `validate_coupon(...) -> CouponValidation(ok, error_code, coupon)` is a
separate gate that never raises for normal invalid cases; it returns a typed `error_code` the API
maps to 400. Codes: `not_found`, `inactive`, `not_started`, `expired`, `min_not_met`,
`wrong_currency`, `exhausted`, `user_exhausted`, `not_valid_for_items`. `compute_totals` consumes
an already-valid coupon so totals and validation can never diverge. Coupon codes are stored
uppercased and looked up case-insensitively (CI unique constraint).

**Documented simplifications / deviations (Fable-approved):**
- `Coupon.applies_to_products` / `applies_to_categories` act as an **eligibility gate** — the cart
  must contain ≥1 matching item — and the discount then applies to the whole subtotal. Per-line
  targeted discounts are a post-launch refinement.
- `CouponRedemption.order_number` is a soft `CharField` reference, **not** an FK to `orders.Order`
  (built in 08d), so `apps.checkout` stays independent. The Order→Coupon link lives on
  `Order.coupon` (Plan-10).
- **Known last-use race (not a bug):** usage limits read the redemption ledger, so two concurrent
  checkouts on a coupon's final use can both pass. The ledger records the truth and admin can see
  overuse; tighten with a locked counter post-launch if needed.

## Delivery & Regions (Plan-08b)

New independent domain app `apps.delivery`. It owns delivery options and the region tree matcher,
and imports **nothing** from `apps.carts` — the matcher is pure and reusable by cart display and by
checkout's server-side re-check (never trust the client's option list).

**Mixed-granularity coverage.** A `DeliveryOption` can cover whole countries (M2M `countries`) and/or
any node of the region tree (M2M `regions`) at any level — a whole state ("Lagos State Flat") or a
single LGA ("Ikeja Same-Day"). Both styles coexist on one option set.

**`options_for_address(address, lines, subtotal) -> list[dict]`** (`apps.delivery.services`) is the
matcher. `address` is duck-typed (`country_code`, `state_region`, `area_region` — no Cart/Address
import); `lines` is an iterable of `(ProductVariant, qty)`; `subtotal` is in the order currency (for
`free_over`). It returns the active options serving the address, each with a computed `price` and ETA,
ordered by `(sort, name)`.

- **Ancestor-walk match.** The address's `area_region` and `state_region` plus every parent are
  collected; an option matches if it covers the address's country **or** any of those region ids. So
  "Lagos State" coverage automatically serves every Lagos LGA (zone-style), while picking individual
  LGAs is the detailed style.
- **Pricing (`_price_for`).** If the option has `DeliveryOptionRate` rows, the tier whose
  `[min_weight_g, max_weight_g]` band contains the cart's total weight is used (over the top tier →
  the highest tier's price); otherwise the flat `price`. `free_over` zeroes the price once `subtotal`
  meets the threshold. Amounts quantized to 2dp.

**Region tree** lives in `core.Region` (`country_code`, `name`, `level`, self-FK `parent`). Seeded from
the bundled fixture `apps/core/fixtures/ng_regions.json` (a `{ "State": ["LGA", …] }` map) by data
migration `delivery/0002_seed_ng_regions` → **37 states (36 + FCT) + 774 LGAs**. Fixture provenance:
the widely-mirrored `devhammed` public NG states-and-LGAs dataset; counts verified against the
36+FCT / 774 canonical totals. Other countries add rows later with no code change.

**Browse API** `GET /api/v1/meta/regions/?country=<CC>` → top-level (state) regions;
`?parent=<id>` → that region's children (LGAs). Public (`AllowAny`), unpaginated (short dropdown
lists), each row carries `has_children` so address forms know whether to drill down.

**`Country.area_label`** (Plan-03, landed here) names the finest region level per country — "LGA" (NG),
"Borough" (GB), "County" (US) — surfaced on `/api/v1/meta/countries/` for address-form labelling.

**Deferred:** `kind="carrier"` + `carrier_code` fields exist for Plan-32 carrier-API rates; at launch
every option is `kind="manual"`. Admin CRUD is Plan-19.

**Seed rates are PLACEHOLDERS.** `delivery/0003_seed_delivery_options` seeds a documented placeholder
option set (NG "Nationwide"/"Lagos Delivery"; GB/US/CA/ZZ standard) guarded on country/currency
presence. **Replace with the real audited rates (Plan-00 audit items 10–11) before the checkpoint.**

## Carts (Plan-08a)

Guest + authenticated shopping carts (`apps.carts`) with live per-country pricing.

**Identity model.** A `Cart` is keyed by UUID. Authenticated requests resolve to the user's single
active `standard` cart (get-or-created; a partial unique constraint `uniq_active_cart_per_user_kind`
enforces one active cart per `(user, kind)`). Guests carry the cart UUID in an `X-Cart-Id` header
(the storefront BFF keeps it in an httpOnly cookie) and may hold many carts (they're exempt from the
constraint — their identity *is* the UUID). `get_or_create_cart(request, kind)` in `services.py` is
the single place that decides which cart a request owns, so views stay thin.

**Live re-pricing (never trust the client / the snapshot).** Every cart response is fully re-priced
at read time via `pricing.services.resolve_price` for `request.country`. `CartItem.unit_price_snapshot`
is stored on add/update for **display-drift detection only** — it is never the charge basis. Checkout
(Plan-08d) recomputes totals from scratch. A variant with no price for the country stays in the cart
but is surfaced as `unavailable: true` and contributes 0 to the subtotal.

**Stock cap.** Quantities are clamped to `inventory.services.available_for_country(variant, country)`
on every add/set (a cart never holds more than exists). `set_quantity(..., 0)` removes the line.

**Endpoints** (all `AllowAny`; identity is user-or-`X-Cart-Id`; throttle scope `cart` = 120/min):
`GET /api/v1/cart/`, `POST /api/v1/cart/items/`, `PATCH|DELETE /api/v1/cart/items/{variant_id}/`,
and `POST /api/v1/cart/merge/` (auth-required).

**Merge on login.** `POST /cart/merge/ {cart_id}` folds an unclaimed guest cart's lines into the
caller's active standard cart (summing quantities, capped at stock), then marks the guest cart
`converted`. Foreign/claimed/missing guest ids are ignored (returns the user's cart unchanged);
idempotent. The BFF calls this right after storing the new access cookie — cleaner than mutating the
SimpleJWT token view.

**Express cart.** `kind="express"` is a separate single-per-user cart for Buy Now; the standard cart
flow never touches it. The field + constraint exist here; the Buy Now *upsert* is Plan-08d.

**Abandoned flagging.** The `abandon_stale_carts` Celery beat task (every 30 min) flags active carts
untouched for >3h as `status="abandoned"` so the data accrues. **Deferred:** recovery *emails*
(Plan-30) and `status="converted"` on real checkout (Plan-08d does that under a row lock).

## Checkout & Orders/Payments scaffolding (Plan-08d)

Authenticated `POST /api/v1/checkout/` turns a cart into a `pending_payment` `Order` with reserved
stock and an `initiated` `Payment`. The `orders` and `payments` apps are introduced here with the
**full** Plan-10/09 model field list (`Order`, `OrderItem`, `Payment`, `CountryPaymentGateway`) so
checkout writes real tables now; Plan-09/10 add only *new* tables (`Refund`, `WebhookEvent`,
`OrderEvent`) — the money tables stay append-only. `bank_transfer` is the first working gateway.

**Two-phase checkout (no HTTP under a DB lock).** Phase 1 is one DB transaction: lock the cart
(`select_for_update`), re-validate every line (`sellable_in` + `resolve_price`), server-side re-match
the delivery option via `delivery.options_for_address` (never trust the client's option list or price),
check the gateway is active for the country, validate any coupon, compute money via
`checkout.services.totals.compute_totals` (never the client, never a snapshot), reserve stock, create
the `Order` + snapshot `OrderItem`s, create the `Payment(initiated)`, and convert the cart. **Commit.**
Phase 2 runs *after* commit with no lock held: `gateway.initiate()` → store `gateway_reference`. For
bank transfer `initiate()` is local (returns merchant bank details from `SiteSetting`), but the shape
is built now so Plan-09's networked gateways drop in cleanly behind the same `PaymentGateway` ABC.

**Attempt-suffixed `reservation_reference`.** `Order.reservation_reference` starts equal to the order
number (`TC-100042`) and gains a `/2` suffix on any re-reserve (Plan-09's late-payment path). This is
load-bearing: `inventory.reserve()` is **idempotent by reference**, so re-reserving after an
expiry-release under the *same* reference would silently reserve nothing. Commit/release always use
`order.reservation_reference`, so the reference is the single ledger key for the order's stock.

**Order row is the single serialization point.** Every status change (`place_order`, `mark_paid`,
`expire_pending_orders`) locks the `Order` row and re-checks `status` under the lock, so the
expiry-vs-payment race resolves deterministically — whichever grabs the lock first wins, and the loser
sees the changed status and no-ops. `expire_pending_orders` (Celery beat, every 5 min) runs **one
transaction per order** (a poison order can't roll back its siblings) and `release()` is
ledger-idempotent, so a double-run is safe. `RESERVATION_TTL_MINUTES` (default 30) sets the window.

**Idempotency.** `POST /checkout/` requires an `Idempotency-Key` header. A two-phase Redis record
(Django cache) is the fast path: `begin()` reserves the key (`in_progress`), `finish()` stores the
`(status, body)` for a 24h replay window; same key + different payload → 422; same key still in flight
→ 409. The `Payment.idempotency_key` UNIQUE column is the **durable backstop** that survives Redis
eviction — `place_order` replays from the stored `Payment` if the key already produced one.

**Insufficient stock fully rolls back.** Reservation runs inside phase 1's transaction, so an
`InsufficientStock` (mapped to 409 `insufficient_stock`) rolls back the order, items, payment, and cart
conversion together — the ledger records zero movements.

**Deferred seams.** To **Plan-09**: Paystack/Flutterwave/Stripe/PayPal gateways, webhooks, `verify()`,
refunds (`Refund`, `WebhookEvent`), the attempt-2 re-reserve on late payment, and the *full* `mark_paid`
with amount/currency equality checks (08d ships a minimal `mark_paid` used by tests + the bank-transfer
manual-confirm path). To **Plan-10**: `OrderEvent` + a `state.py` state machine (08d sets `order.status`
directly in exactly two places, both to be refactored through `transition()` later), order emails,
invoices, and the customer/admin order APIs.


---

## Payments (Plan-09)

Four gateways behind one interface, signature-verified idempotent webhooks, refunds.
Architectural rulings on this stage came from a Fable 5 consult (2026-07-15); the ones
that constrain future changes are recorded here so they aren't relitigated.

**The one law: webhooks are a trigger, never a source of truth.** No inbound payload is
ever trusted for money. Every fulfilment goes through `payments.services.confirm_payment()`,
which calls `gateway.verify()` — a server-side, authenticated re-read — and compares the
verified amount+currency against the Payment before anything is committed.

**Three layers** (`apps/payments/services.py`), so recovery logic never pollutes the
fulfilment primitive:

| Layer | Holds the order lock? | Job |
|---|---|---|
| `_fulfil_locked(order, payment)` | caller must | commit stock, snapshot fulfilment, redeem coupon, flip statuses. Pure DB. |
| `mark_paid(payment) -> MarkPaidResult` | yes | fulfil iff `pending_payment`; otherwise REPORT (`NOOP_EXPIRED`/`NOOP_CANCELLED`/`NOOP_ALREADY_PROCESSED`) rather than silently no-op |
| `confirm_payment(payment)` | no (verify is a network call) | verify → amount check → `mark_paid` → react to the verdict |

**Invariant:** `payment.status == "succeeded"` is written *only* by `_fulfil_locked`. So
"payment succeeded ⟺ the order was fulfilled (or explicitly recovered)". An amount
mismatch leaves the payment `pending` and flags the order — it never fulfils.

**`gateway.verify()` is NEVER called while holding a row lock.** A 15s gateway timeout
inside `select_for_update` would serialize every payment and the expiry task behind one
slow HTTP call. Verify first, then open the transaction. Same discipline in refunds.

**needs_review vs review_reason.** `needs_review` is a *status* (pre-fulfilment flags:
amount mismatch, expired-and-couldn't-re-reserve). `Order.review_reason` is the orthogonal
**single source of truth for "a human must look"** and is written in *every* flag path.
The double-payment case can't use the status (an order can't be `processing` AND
`needs_review`), so it sets `review_reason` only. Admin needs-attention filter =
`status == 'needs_review' OR review_reason != ''`. Plan-10's `transition()` must clear
`review_reason` when the flag is resolved.

**Money units.** `apps/payments/money.py` owns the *arithmetic* (reading
`Currency.decimal_places`) and REFUSES to round money it can't represent. Each adapter owns
its gateway's *convention* — they genuinely differ, and this is the 100x-overcharge trap:

| Gateway | Amount on the wire | Idempotency on initiate | Webhook event id |
|---|---|---|---|
| Paystack | **kobo** (minor) | the `reference` param itself | derived `event:txn_id` |
| Stripe | minor, zero-decimal aware | `Idempotency-Key` header | native `evt_…` |
| Flutterwave | **MAJOR** (plain NGN) | `tx_ref` | **none — derived** `sha256(tx_ref:event:status)` |
| PayPal | **major decimal string** `"10.99"` | order id | native `WH-…` |

**Webhook pipeline.** `POST /api/v1/webhooks/{gateway}/` — no auth (the signature *is* the
auth, checked over the RAW request bytes; DRF parsers are disabled on the view so the body
is never re-serialized), throttled **generously** (gateways treat non-2xx incl. 429 as a
delivery failure and retry — a tight throttle turns a retry burst into a storm). Flow:
verify signature → upsert `WebhookEvent(gateway, event_id)` (the unique constraint IS the
dedupe; duplicate ⇒ 200 immediately) → enqueue Celery → 200 fast. Unmatched/unknown events
are recorded and **acked 200** — never make a gateway retry something we'll never process.

**Event routing.** Each adapter classifies its own events (`ParsedEvent.kind`:
payment|refund|other). This is load-bearing, not tidiness: routing a refund event through
`confirm_payment` would re-verify an already-refunded payment and mis-flag it as a double
payment. Refund events go to `refunds.advance_refund_from_event` instead.

**Customer return endpoint** — `POST /api/v1/payments/{reference}/verify/`. The buyer
returns from the redirect *before* the webhook lands; this runs the same `confirm_payment`,
so the UI doesn't stare at "pending" for 5–30s. Webhook-vs-return is a benign idempotent
race: whichever verifies first fulfils, the other no-ops.

**Late payment after expiry.** `NOOP_EXPIRED` → re-reserve under a **bumped attempt suffix**
(`TC-100042` → `/2`; `inventory.reserve()` is reference-idempotent, so re-reserving under the
old reference would silently reserve nothing). `reserve()` is per-item, so a failure on item
N leaves 1..N-1 reserved — the failure branch `release(new_ref)` cleans up the partial set
before flagging. The new reference is written **before** `_fulfil_locked` reads it.

**Gateway 5xx on initiate** → 502 `gateway_error` (distinct from the 400 `gateway_unavailable`,
which means "not offered in this country"). The order stays `pending_payment` and the
inflight idempotency marker is cleared, so the SAME `Idempotency-Key` retries and **resumes**
the existing order via the durable Payment backstop (re-attempting initiate) — no duplicate
order, no double reservation.

**Refunds.** Two-phase like confirm: under the payment lock, compute remaining from a DB
aggregate of `succeeded + pending` refunds and write a `pending` Refund row — that row
*reserves* the amount, so two admins can't both pass an `amount <= remaining` check. The
gateway call happens outside the lock; a failed refund frees its amount automatically
(the aggregate only counts succeeded+pending). Refunds are **async** on Paystack/Flutterwave/
PayPal, settled later by a refund-completion webhook. Restock is restricted to **full**
refunds and driven by the `fulfillment_warehouses` snapshot — per-item partial restock needs
a UI that can ask which lines (Plan-19).

**Keys are read lazily**, never at import: all gateways register unconditionally, and an
unconfigured one raises `GatewayNotConfigured` → 503 at call time. That fails safe when a
gateway is activated per-country before its keys ship, and keeps migrations/tests trivial.
`manage.py check` warns (`payments.W001`) for any gateway missing keys.

**⚠️ PENDING CHECKPOINT — real test-mode e2e.** Every gateway is **code-complete but
unverified against a sandbox**: the suite mocks HTTP (respx / SDK monkeypatch) and computes
signatures in-test, so it encodes *our assumptions* about each API — and that's exactly where
assumptions are wrong (field names, amount units, status enums). Plan-09 is NOT done until
one real test-mode payment per gateway (Paystack card, Flutterwave card, Stripe 4242…,
PayPal sandbox) runs checkout → webhook → order `processing` + stock committed. **Blocked on
test-mode API keys from Hammed.**
