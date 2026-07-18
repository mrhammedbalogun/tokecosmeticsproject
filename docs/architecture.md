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
ledger-idempotent, so a double-run is safe. `RESERVATION_TTL_MINUTES` (default 30) sets the window —
**per-gateway since Plan-09b**: it tunes the card gateways, while bank transfer is fixed at 24h on the
gateway class.

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

**review_reason is orthogonal to status — and `needs_review` is not a status.**
*(Revised in Plan-10; Plan-09 originally shipped `needs_review` as a status.)*

"A human must look at this" is not a place in an order's life — it's a note pinned to an
order that is somewhere in its life anyway. `Order.review_reason` is the **single source
of truth** for it, written in *every* flag path, and the admin needs-attention filter is
simply `review_reason != ''`.

Making it a status was a category error, and the Plan-09 code testified against itself:
the double-payment case couldn't use the status (an order can't be `processing` *and*
`needs_review`), and a `_FULFILLED_STATES` guard existed solely to stop the status from
stomping real ones. Flagging now never touches status, so nothing is destroyed:

| Case | Status stays | Why |
|---|---|---|
| Amount/currency mismatch | `pending_payment` | Expiry still reclaims the stock; a later "fulfil it" replay lands on the `NOOP_EXPIRED` re-reserve path. |
| Late payment, can't re-reserve | `expired` | It genuinely did expire. We hold their money, not their goods — auto-refund territory. |
| Double payment | `processing` | The order really is processing. Only the *second* payment needs refunding. |
| Payment on cancelled order | `cancelled` | Terminal. The refund is against the Payment, not a lifecycle move. |

`transition()` **never** clears `review_reason`. Clearing requires an explicit admin
resolve action that writes its own `OrderEvent` — otherwise shipping a flagged order
would silently erase an unresolved double payment and nobody would refund the customer.

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

**Deferred, not dropped (Plan-09b, 2026-07-16).** All four gateways are now **deactivated**
(migration `0007_launch_bank_transfer_only`), which is what makes deferring this checkpoint safe:
code that cannot be reached takes no money. The checkpoint is now the **precondition for
reactivating any of them** — see *Manual payments (Plan-09b) → `is_active` gates*.

---

## Order lifecycle (Plan-10)

`apps/orders/state.py` is the **only** thing in the codebase that writes `order.status`.
Grep-verifiable, and worth keeping that way: the invariant is what makes the timeline
trustworthy.

### transition()

Two rules, both load-bearing:

1. **Every caller holds the row lock.** `transition()` asserts it's inside a transaction
   and assumes the caller has `select_for_update()`-ed the order, so it validates against
   the locked row. Otherwise an admin marking an order shipped can race a payment webhook
   and validate against a status that's already stale. `transition_by_id()` is the
   lock-acquiring wrapper for admin views; code already inside a locked block (payments,
   the expiry sweep) calls `transition()` directly. **There is no fast path that skips
   validation** — that's how "nothing sets status directly" quietly stops being true.
2. **Deferred effects run after commit.** Registering an `on_commit` callback is a pure
   in-memory append, so it's safe under the lock — which is precisely what lets
   `_fulfil_locked` route through `transition()` without smuggling a Redis round-trip into
   a `select_for_update`. The callback runs after the outermost block commits, so a worker
   can never read pre-commit state and email about an order the DB won't admit exists.

**Two effect lanes.** Deferred (`on_commit`: emails) and synchronous in-transaction (DB
work that must be atomic with the flip — `release()` on cancel). The latter stays in the
caller's locked block; `cancel_order` is the reference example.

`place_order` is a **creation, not a transition**: it opens the timeline with a `placed`
event rather than moving through the machine.

### The status vocabulary

```
pending_payment -> processing | expired | cancelled
expired         -> processing | cancelled          # processing = late-payment re-reserve
processing      -> shipped | on_hold | refunded
shipped         -> delivered | on_hold | refunded  # lost parcel -> full refund
delivered       -> completed | refunded
completed       -> refunded                        # post-completion return
on_hold         -> (almost anything)               # triage for migrated legacy orders
cancelled, refunded                                # terminal
```

**`cancelled` means no money was ever captured; a paid order exits via `refunded`.** So
`processing -> cancelled` is absent. This kills the "an admin cancelled a paid order —
where did the money go?" ambiguity, and means cancel never owes a refund. Plan-18's UI
therefore offers *Refund*, not *Cancel*, on a paid order.

**Cancelling MUST release the reservation**, and `cancel_order` is the only path that
does. `expire_pending_orders` sweeps `pending_payment` only, so a cancelled order that
kept its reservation would hold that stock away from real buyers forever with nothing
left in the system to reclaim it. `transition()` validates *before* `release()` runs, so
a refused cancel on a paid order can't free stock that was already sold.

**Not statuses, by design:** `needs_review` (orthogonal — see the Plan-09 section) and
`partially_refunded` (a payment-ledger fact; a shipped order can be partially refunded
and still needs delivering).

### Emails

Keyed on the **destination status, never the (from, to) pair** — keying on the pair is
exactly how the late-payment customer (`expired -> processing`) silently stops getting a
confirmation while the normal path keeps working. `on_hold` and `expired` mail nothing:
they're our words for our problems.

**Placement mails only for gateways that hand over payment instructions** —
`InitiateResult.action == "bank_details"`, which is `bank_transfer` today and a future
Paystack dedicated account tomorrow. That email is the customer's only durable copy of
the account number *and* of the order number they must quote as the transfer reference;
without it those live solely in the checkout response, and an un-referenced transfer is
exactly the kind you can't match to an order. An instant-gateway customer is mid-redirect
and owes nothing on paper, so they get nothing at placement and one mail at payment —
which is why there's no separate "payment received" template for them.

Keyed off the `action`, deliberately **not** an `is_instant` gateway flag: that one bit
conflates three orthogonal questions (needs-instructions-email? / can `verify()` be
called? / which TTL applies?), and a Paystack dedicated account breaks it — not instant,
but machine-confirmable. When Plan-18 needs the other axis, add
`confirmation: "gateway" | "manual"`.

> **Resolved by Plan-09b (2026-07-16).** This section previously warned that
> `bank_transfer` was seeded active but unfinished — nothing could confirm it, and a
> 30-minute TTL meant it always expired before the money landed. Plan-09b closed both
> (`confirm_manual_receipt`, a 24h per-gateway TTL) and made bank transfer the **only**
> live method at launch. The `confirmation` axis anticipated below now exists. See
> **Manual payments (Plan-09b)**.

The refund mail is enqueued explicitly rather than via the effect table: a partial refund
has no transition to hang an effect off, and the amount isn't derivable from a
destination status.

**All money renders through `format_money`, never `|floatformat`** — hardcoding two
decimals renders a zero-decimal currency 100x wrong in the customer's inbox, the same
trap the gateway adapters exist to avoid. Email `base.html` declares `<meta
charset="utf-8">`: without it, every ₦ becomes "â‚¦" in clients that trust the document
over the MIME header, and NGN is on nearly every mail we send.

### Invoices

**Generated on demand, never stored.** A PDF written to S3 at fulfilment keeps asserting
the original total long after a refund changed the commercial reality, and every future
invalidating event becomes something a human must remember to re-trigger. Rendering at
request time means the document can't go stale — it shows settled refunds and net paid,
dated at *render* time (dating from `placed_at` would claim a refund position was accurate
before any refund could have settled).

`render_invoice_html` holds the logic and runs anywhere; `render_invoice_pdf` is a thin
WeasyPrint wrapper. **WeasyPrint binds to Pango/cairo: `pip install` alone is not
enough.** `backend/Dockerfile` (Plan-02, not yet written) must apt-install
`libpango-1.0-0 libpangoft2-1.0-0` or every invoice download 500s with a *runtime*
ImportError. It cannot render on a Windows dev box at all — verify inside a Linux
container.

### Access control

- A stranger's order **404s, never 403s**. A 403 confirms the order exists, which is a
  free oracle for probing order numbers.
- **Tracking tokens** (`orders/tokens.py`) are `django.core.signing`, salted per scope,
  90-day expiry, nothing stored. The token **names its own order**; the URL's number is
  checked against it and never trusted, so one order's token can't open another's.
- Token holders get the **redacted** serializer — no address, phone or email. It's a
  bearer credential that lives in a forwardable inbox and turns up in access logs; it
  answers "where is my parcel?" and nothing that would hand a customer's home address to
  whoever the mail got passed along to.
- **`invoice.pdf` does not accept the token** — an invoice carries name, address and
  billing details. If guest invoices are ever needed, mint a separate invoice-scoped
  token; do not widen the tracking salt.
- `resolve-review` is the **only** thing that clears `review_reason`, and it writes its
  own event. Never a side-effect of a status change: shipping a double-payment order must
  not erase the reason someone still owes the customer a refund.

### Auto-complete

`complete_delivered_orders` (daily beat) closes orders whose return window has elapsed —
`RETURN_WINDOW_DAYS`, default 14. Staff can complete sooner from the admin; whichever
happens first wins. The clock runs from the **delivery event, not `placed_at`**: an order
that took three weeks to arrive hasn't had its return window eaten by shipping time. One
transaction per order, mirroring `expire_pending_orders`, so a poison order can't abort
the sweep.

---

## Manual payments (Plan-09b)

**We launch on bank transfer only.** The four networked gateways are code-complete but
their sandbox checkpoint (Plan-09's ⚠️ above) was never done — the test-mode keys never
arrived. Migration `payments/0007_launch_bank_transfer_only` deactivates all four and
activates `bank_transfer` in NG/GB/US/CA/ZZ. Deactivating them is what makes deferring
that checkpoint *safe* rather than reckless: uncertified code that cannot be reached takes
no money, so the checkpoint stops blocking every stage downstream of it.

The consequence is that manual bank transfer went from a fringe NG option to **the single
path every order in every market now takes** — NG/NGN, GB/GBP, US/USD, CA/CAD, ZZ→USD.
Plan-09b is what made it a complete method rather than a hole.

### bank_transfer was a dead end at both ends

Two independent breaks, each of which made the method unusable on its own:

| End | The break | What closed it |
|---|---|---|
| Confirm | `mark_paid()` was reachable *only* via `confirm_payment()` → `gateway.verify()`, which `bank_transfer` answers with `ManualVerificationOnly`. **Nothing could ever mark a transfer order paid** — the money landed, the sweep expired the order, the stock went back. | `confirm_manual_receipt()`: a second entry point to the same ladder. The staff member reading the bank statement **IS** the verification. |
| Refund | `bank_transfer.refund()` inherited `base.py`'s bare `NotImplementedError` — a `RuntimeError`, so `create_refund`'s `except GatewayError` did **not** catch it. | `ManualRefundOnly(GatewayError)` + `record_manual_refund()`. |

The refund end deserves the detail, because it was worse than a 500. `create_refund`
writes its `pending` Refund row in phase 1 *before* calling the gateway in phase 2. An
uncaught `NotImplementedError` escaped phase 2, so the request 500'd **and left the pending
row behind**. `refundable_amount` counts `succeeded + pending`, so that amount stayed
reserved forever: every later refund against that payment failed `amount_exceeds_remaining`.
**One 500 poisoned the payment permanently** — and the payment of a customer owed money is
the last thing that should be unrefundable. Raising in the gateway vocabulary means the
existing handler marks the row `failed` and frees the amount.

### `confirmation` vs `InitiateResult.action` — adjacent, not interchangeable

These two look like the same bit and are not. **Do not unify them.**

- **`action == "bank_details"`** answers *"did the customer leave checkout holding
  instructions?"* — which is why `_initiate_payment` keys the `order_received` email off
  it, and should keep doing so. That email is the customer's only durable copy of the
  account number and the reference they must quote.
- **`gateway.confirmation`** (`"gateway" | "manual"`) answers *"can this be `verify()`'d,
  and which TTL applies?"*

A future **Paystack dedicated account is not instant but IS machine-confirmable**: it
hands over bank details (so it wants the email) *and* has a webhook and a real `verify()`
(so it must not go near `confirm_manual_receipt`). One bit cannot serve both questions —
whichever way you collapse them, that gateway breaks one of the two. The next reader will
see two flags that agree on today's two gateways and "simplify"; this paragraph is why not.

### Amount discrepancies: explicit acceptance, mandatory reason

Any nonzero delta between the confirmed amount and the order total requires
`accept_discrepancy=True` **and** a non-blank reason. The asymmetry is deliberate:

- **Overpayment fulfils** (and flags the surplus for refund). They paid enough. Holding
  the goods hostage over a surplus is the wrong failure to pick — the flag is the thing
  that gets the surplus back to them.
- **An unexpected amount raises rather than fulfilling-and-flagging**, because the common
  cause is a **staff typo**, and with refunds manual the flag **is** the authorisation to
  wire real money out of the bank. Type `50000` for `5000` and a fulfil-and-flag would
  produce a flag instructing a human to send ₦45,000 to a customer who is owed nothing.
  **No gateway ledger will refuse it** — there is no gateway. The typo has to stop at the
  keyboard, because nothing downstream can catch it.
- **The mandatory reason is the anti-"staff always tick the box" control.** A checkbox
  alone becomes reflex; a free-text reason that lands in the order timeline under the
  confirmer's name does not.

A **refused** attempt writes an `OrderEvent` (`manual_receipt_refused`) and **no** review
flag. Nothing happened, the caller already has the numbers to show, and a flag would
outlive the corrected confirm that follows it thirty seconds later — leaving a permanent
"someone look at this" on an order that is now perfectly fine.

Shortfalls fulfil once accepted, recording who accepted: international wires legitimately
lose a slice to intermediary banks, and that is a real cost of doing business, not a fraud
signal.

### `_flag_review` appends; `resolve_review` is still the only clearing act

`_flag_review` appends to `Order.review_reason` (`"; "`-joined, deduped) rather than
assigning. One order can accumulate several unresolved facts, and an assign silently
erases whichever was written first. The motivating case: a cancelled order the customer
overpaid ₦12,000 against ₦10,000 — the verdict ladder writes *"refund it"* (the whole
payment; the goods never ship) and an assigning delta branch would overwrite it with
*"refund the difference"* (₦2,000). Staff wire ₦2,000, resolve the flag, **and the
customer is out ₦10,000 with nothing left in the system recording it.**

`resolve_review` still clears the whole string in one explicit act, so Plan-10's model —
only an admin resolve clears it, never a status transition — is untouched.

> **Note.** In the shipped code that exact scenario is stopped *twice*: the delta branch
> also returns early when `fulfilled` is false (see below), so it never writes on a
> cancelled order. The append is the deeper guard and the one to rely on — flags
> genuinely accumulate **across** confirms (two distinct payments each landing on the same
> cancelled order flag separately, and both must survive). `_flag_review`'s own docstring
> still describes the two-writers-in-one-request case as live; it is defence in depth, not
> a reachable path.
>
> **Uneven:** `_reserve_and_fulfil_after_expiry` writes `order.review_reason` by direct
> assignment in three branches rather than going through `_flag_review`, so it *can* still
> erase a pre-existing flag (an amount-mismatch flag raised while `pending_payment`, then
> the order expires, then a late payment fails to re-reserve). Pre-dates Plan-09b, narrow,
> and left alone here rather than changed under a docs-only stage — but it is the one place
> the append rule is not actually enforced.

### `_react_to_verdict` returns a bool

The verdict alone cannot say whether the goods shipped. `NOOP_EXPIRED` may or may not end
in fulfilment depending on whether `_reserve_and_fulfil_after_expiry` could re-reserve the
stock — same verdict, opposite outcomes. So the ladder reports what actually happened
(`payment.status == "succeeded"` ⟺ fulfilled, by the Plan-09 invariant) and
`confirm_manual_receipt` only writes a delta flag when the goods actually shipped.
Otherwise the delta flag appends noise to the ladder's own, more urgent instruction — or
worse, implies a fulfilment that never occurred.

### `is_active` gates the menu and `initiate()` — **never** `confirm_payment()`

`CountryPaymentGateway.is_active` filters the checkout menu (`active_gateways_for`) and
`place_order`'s gateway check. It is deliberately absent from the confirmation path: **a
customer who genuinely paid Paystack minutes before the deploy must stay fulfillable.**
Gating confirm on `is_active` would mean deactivating a gateway silently converts every
in-flight payment into money we took and goods we never shipped.

**Reactivation procedure — in this order, no shortcuts:**

1. Drive the deferred **Plan-09 sandbox checkpoint** first: one real test-mode payment per
   gateway, end to end (checkout → webhook → order `processing` + stock committed),
   demonstrated to Hammed. The suite mocks HTTP, so it encodes our *assumptions* about
   each API — field names, amount units, status enums — which is exactly where they are
   wrong.
2. *Then* flip `is_active` for that gateway.

Migration 0007's reverse is `RunPython.noop` **precisely so a rollback cannot do step 2
without step 1.** Reactivating a gateway is a human checkpoint, never a side effect of
`migrate` going backwards.

### The checkout phase-1 gate

`place_order` gates on a missing `BankAccount` **inside phase 1**, alongside the country
and coupon checks — not at `initiate()`. Phase 1 commits the order, reserves stock for 24h
and converts the cart; `_initiate_payment` only runs *after* that commit, outside the lock.
Gating at `initiate()` alone would leave **a day-long stock hold and a consumed cart behind
every failed attempt, and every retry would burn another** — a market with no bank account
configured would quietly eat its own inventory.

`initiate()` still refuses (`GatewayNotConfigured` → 503) when it finds no account, because
the row can be deactivated between the two phases. What it must never do is **render
blanks**: the old `SiteSetting.get_typed(..., "")` default would have shown a payment page
with an empty account number, and the customer wires into nowhere. **That money is
genuinely unrecoverable; a 503 only costs the sale.** Between an unrecoverable loss and a
lost sale, fail loudly.

### Per-gateway reservation TTL

Bank transfer holds stock for **24h** (`reservation_ttl_minutes = 1440`); cards keep the
30-minute default. A card resolves in seconds; a transfer waits on staff working hours,
and a 30-minute TTL guarantees the order expires before anyone reads the bank statement.

`reservation_ttl_minutes` is a **property on the ABC**, not a class attribute:
`= settings.RESERVATION_TTL_MINUTES` in a class body is evaluated at **import** and would
ignore `override_settings` and any env change without a restart. Subclasses shadow it with
a plain int. `RESERVATION_TTL_MINUTES` now tunes **card gateways only**.

The TTL is stamped at order creation from the already-validated gateway, whose `Payment`
row is created in the same transaction — nothing needs re-stamping at initiate time.

### The expiry sweep's poison isolation

`expire_pending_orders` derives its set of manual gateway codes **once, from the registry**
(`_manual_gateway_codes`), never `get_gateway()` per order. An order carrying a gateway code
the registry never heard of — and **879 migrated legacy NG orders arrive in Plan-21/23** —
would raise `UnknownGateway` inside the loop, kill the task run, and **starve every due
order behind it, every 5 minutes, forever**. Stock nobody can buy, silently, on a beat.

The per-order `try/except` is what finally makes the task docstring's long-standing promise
("a poison order can't roll back its siblings") true: until Plan-09b, nothing in the loop
could raise, so the promise was untested and the lookup would have broken it.

### ⚠️ Accounting caveat — `payment.amount` is not cash-in

On an **accepted discrepancy**, `payment.amount` stays the **order total**. The cash that
actually arrived lives in `payment.raw_response["manual_receipt"]`, keyed by bank
reference. Nothing rewrites `payment.amount` — the Plan-09 invariant ties it to the order
total asserted at Payment creation, and the amount check depends on that.

The consequence: refunding an overpayment surplus through the ledger reads as a **partial
refund of the order price**, not a return of a surplus. The books say the customer paid
₦10,000 and got ₦2,000 back; reality is they paid ₦12,000 and got the ₦2,000 that was
never owed. Net cash agrees; the story doesn't.

**Acceptable at launch** — the true figure is recorded, per reference, and reconcilable
against the statement. But it is a trap with a fuse on it: **`payment.amount` is NOT
cash-in, and Plan-20/28 reporting must not treat it as such.** Revenue must come from the
receipts, or from a real cash-received field if one is ever added.

### Known gaps — deliberate, not oversights

- **Duplicate-`bank_reference` TOCTOU.** `_find_duplicate_reference` and the
  `raw_response` write are not atomic: check-A → check-B → write-A → write-B lets **two
  different orders both fulfil and ship against ONE transfer**. Be precise about why the
  usual protection doesn't help — `mark_paid`'s row lock is **per-order** and gives
  **zero** cross-order protection, so the duplicate check IS the entire control. Low
  severity only because the window is two queries wide and needs two staff confirming
  *different* orders with the *same* reference inside it. The real fix is a DB unique
  constraint on `(gateway, bank_reference)` — most likely a dedicated `ManualReceipt` row,
  since **only the database can serialise across rows**. Application-level locking cannot
  close this.
- **`_find_duplicate_reference` is unindexed.** `raw_response__manual_receipt__has_key`
  scans the Payment table on every confirm. Fine at launch volume; wants a **GIN index**
  as the table grows. (A `ManualReceipt` table would settle this and the point above at
  once.)
- **`record_manual_refund` has no duplicate-reference guard at all.** It is bounded
  per-payment by `refundable_amount`, so it cannot over-refund one payment — but one
  statement line can be recorded against **two** payments.
- **`BankAccount.clean()` is not a DB constraint.** The country/currency match is
  validated by the model's `clean()`, which a shell or data-migration write bypasses
  entirely, persisting a mismatch. Django admin is the only write path at launch, and it
  calls `full_clean()`.

### Operating this at launch

- **Bank accounts are Django-admin CRUD** (`payments.BankAccount`) — one per country
  (`OneToOneField`), and the currency must match the country's. Per-market fields (sort
  code, routing number, IBAN, SWIFT) go in `extra`, whose keys **become the labels the
  customer reads**: an all-lowercase key is prettified (`sort_code` → "Sort code"), a key
  with any capital is passed through exactly as typed (write `IBAN`, not `iban`).
- **`payments.W002` warns at deploy** for any market with `bank_transfer` live and no
  active `BankAccount`. Customers there cannot check out at all — checkout now refuses the
  order outright rather than stranding it, so the market simply sells nothing until the
  row exists.
- **Every order needs a human.** Receipt confirmation is
  `POST /api/v1/admin/orders/{number}/confirm-payment/`; every refund is
  `POST /api/v1/admin/orders/{number}/manual-refund/`. Both are `IsAdminUser` today
  (Plan-16 owns fine-grained RBAC). **Plan-18 builds the UI over both** — they are API-only
  until then, which means launch-day fulfilment runs on someone posting JSON.
- The `amount_discrepancy` 400 carries `expected` and `received` so the UI can offer
  "accept and fulfil" with a reason box, rather than just failing at the operator.

> **The intended exit is Paystack dedicated accounts** — webhook-confirmed, a real
> `verify()`, no human in the loop. **So this manual flow must not grow features that
> assume it is permanent.** Every hour invested in making manual confirmation comfortable
> is an hour spent on scaffolding, and comfortable scaffolding is how a stopgap becomes
> the architecture. Fix the gaps that lose money; build nothing else here.

## Rest-of-World freight quotes (Plan-14a)

Closes the Plan-09b open question — *"a real Rest-of-World customer may not be able to
check out at all."* Two faults were tangled together and had to be cut in one change,
because fixing the first exposed the second: (a) `options_for_address` matched on the raw
`address.country_code`, so a `DE` customer matched no `Country`/`Region` row and got **zero**
delivery options — a silent dead end at checkout; and (b) once RoW customers *could* reach
checkout, we still had no shipping price for them, because worldwide freight isn't knowable
until the parcel is weighed and routed.

**The flow — pay for goods first, quote freight after.** A RoW delivery option is
`quote_required=True`: it carries a `disclaimer`, **not** a price.

1. Customer checks out and pays the **goods-only** total (a `quote_required` option
   contributes nothing to `shipping_total`).
2. Placement creates a `ShippingQuote` in status `awaiting_quote`, bound to the order.
3. Staff weigh/route the parcel and **quote** the freight (`quote_freight`) — an amount in
   the order's currency. Re-quoting overwrites the live figure and **appends** to an
   audit `note`; the history is the note, never a silent overwrite.
4. Customer transfers the freight; staff **record the receipt** (`record_freight_receipt`),
   which creates a `Payment(purpose="freight")` and moves the quote to `paid`.
5. The order is now `is_shippable`. Nothing before this releases goods.

Alternatively staff can **waive** freight (a gift/absorbed cost) — but only *after* a quote
exists (waive-without-quote is a `400`), so the forgiven amount is always a real figure on
the record, never a blank.

**`Payment.purpose` (`goods` | `freight`), defaulting to `goods`.** Goods and freight are
two separate transfers, in currencies that may differ (NGN goods, USD freight). The three
manual-confirm/refund call sites that pick "the payment" are all scoped to
`purpose="goods"`, so freight never gets mistaken for the goods leg and vice-versa
(`ConfirmManualReceiptView` still selects the goods payment on an order that also has a
freight payment — regression-tested).

### The money rules — read these before writing any report (Plan-20/28)

- **Cash-in is `sum(Payment) grouped by currency`, filtered by `purpose` when goods and
  freight must be told apart — never a single scalar.** NGN goods + USD freight added into
  one number is a confident wrong answer. There is no FX consolidation in the MVP; a total
  that crosses currencies is a bug, not a convenience.
- **`quote.amount` is NOT cash.** It is what we *asked for*. `payment.amount`
  (`purpose="freight"`) is what *landed* — and the two normally differ by correspondent-bank
  fees. Reporting must take freight revenue from the **freight payment**, never from the
  quote. (This is the same trap as the Plan-09b caveat that `payment.amount` is not cash-in
  on an accepted discrepancy — a different field, the identical mistake.)
- **Waived freight is its own reporting line** — e.g. *"freight waived: 6 orders, $340 of
  quoted value."* Silent waiving is exactly the off-books hole this design closed, so
  surfacing it is a **requirement on Plan-20**, not a nice-to-have.
- **An order awaiting freight is `sold`, not `reserved`.** Plan-20's reserved-vs-sold split
  must count it as sold — the goods money is in the bank.

### Traps that look like bugs and are not

- **Every RoW goods payment lands short and routes through `accept_discrepancy`.** Under the
  default SHA fee terms a correspondent bank takes its cut from the wire in flight, so the
  customer sends 40 and 32 arrives. This is the **routine** RoW path, expected and
  documented — **not** a fraud signal. Do **not** widen the amount-matching tolerance to
  "make it stop"; that would blind the goods leg to genuine shortfalls in every market. The
  `order_received` email mitigates it by asking non-default-market customers to send with
  **OUR** charges (Task 12) — a template string that reduces how often the discrepancy
  fires, never a guarantee it won't.
- **The freight reference (`TC-100001-F`) is a dedup control, not an identification
  mechanism.** It keeps goods and freight references from colliding on the
  `(gateway, gateway_reference)` unique constraint. But SWIFT narration is routinely
  truncated by intermediaries, so real-world matching is the owner's eyes on a statement
  (amount + date + name), not the reference. A second order reusing a `bank_reference`
  is a `409` — that constraint is the freight leg's real serialization, unlike the goods
  leg's still-open JSON-key check (see *Known gaps* above).
- **No TTL on the freight wait — ever.** Once real goods money is against an order we
  **never** auto-cancel or auto-release it. The decline path (a quote the customer won't
  pay) is a deliberate staff action to a single terminal state, with the goods refund handled
  manually; there is no automated money movement here.

### The storefront contract (Plan-14 must honour this)

A `quote_required` delivery option serializes as `price: null` + `quote_required: true` +
a `disclaimer` string. The storefront **must render the disclaimer** and must **never**
show "Free", "—", or do arithmetic on the null. There is no storefront yet, so this is
recorded as a contract with a **required test** on Plan-14, not built here. The customer-facing
"Awaiting shipping cost" order state is likewise Plan-14's to build.

### Accepted risks (carried forward)

- **A derived `is_shippable` gate has no teeth of its own** — it is computed from
  `{paid, waived}`, not a stored flag, so anything that dispatches goods must *check* it.
  A ship queue that forgets to is the accepted risk of a derived gate; the alternative
  (a stored, separately-mutated status) is a worse class of bug (drift).
- **The goods-leg duplicate-`bank_reference` TOCTOU** (Plan-09b) is still open and still
  carries most of the money. The freight leg now has the real `(gateway, gateway_reference)`
  DB constraint the goods leg wants; the cheap fix is to move the goods reference onto it
  (or a `ManualReceipt` row). Tracked in *Known gaps* above.
- **`_find_duplicate_reference`'s unindexed JSON scan** runs on every manual confirm — fine
  at launch volume, wants a GIN index as the table grows.
