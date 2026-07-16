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
