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
of Plan-05 (FK to `catalog.ProductVariant`). 33 backend tests green in CI.
**Next: Plan-05 (catalog) — opens by activating the pricing app; Plan-02 (VPS) still parked on Cloudflare.**

## Notes / limitations to record as we go

- Single locale (en) at launch; prices via `Intl.NumberFormat` per currency; hreflang omitted.
- US/CA sales-tax-by-state is out of MVP scope — flat configurable rate per country (`Country.tax_rate_percent`).
- `request.country` is set by `CountryMiddleware` from the `X-Country` header; missing → NG (default),
  unknown/inactive → ZZ (Rest of World). All price/tax context flows from this.
- Reports are per-currency (no FX consolidation) in the MVP.
