# master-tokerebuild.md — Tokecosmetics Complete Rebuild: Master Implementation Guide

> **You are the implementing engineer.** This document was prepared by a senior architect after auditing the live systems. Follow it stage by stage. Do not skip stages, do not reorder them unless a stage explicitly says it can run in parallel, and do not improvise architecture decisions that are already made here.
>
> **REQUIRED WORKFLOW PER STAGE:** Before implementing any `Plan-*` stage, expand it into bite-sized TDD tasks using the `superpowers:writing-plans` skill, then execute with `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Every stage ends with a **CHECKPOINT** — stop, verify the acceptance criteria, show Hammed the result, and get his go-ahead before starting the next stage.

**Goal:** Replace two slow, insecure WordPress/WooCommerce stores (tokecosmetics.com for Nigeria, tokecosmeticsintl.com for international) with ONE global e-commerce platform: Next.js storefront on Vercel, Django REST API on the existing Namecheap VPS, Next.js admin portal at backend.tokecosmetics.com. Migrate products (NG site), order history (both sites), and customer accounts that have orders. Launch on next.tokecosmetics.com, then cut over to tokecosmetics.com.

**Architecture:** API-first. Django + DRF + PostgreSQL + Redis + Celery + Meilisearch in Docker on the VPS, exposed at `api.tokecosmetics.com`. Two Next.js apps (storefront + admin) deployed on Vercel from one monorepo. Country/currency awareness is data-driven (no code duplication per country).

**Tech stack (pinned decisions — do not substitute):**
- Backend: Python 3.12, Django 5.2 (LTS), Django REST Framework, djangorestframework-simplejwt, drf-spectacular, celery[redis], django-anymail[resend], django-storages[s3], django-filter, django-cors-headers, psycopg[binary], gunicorn, pytest + pytest-django + factory_boy
- Frontend: Next.js (latest stable, App Router), TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form + Zod
- Infra: Docker Compose on VPS (PostgreSQL 16, Redis 7, Meilisearch, Django web, Celery worker, Celery beat), Vercel for both Next.js apps, GitHub + GitHub Actions for CI/CD
- Email: Resend, sole provider (via django-anymail). Sending domain mg.tokecosmetics.com. [Decision 2026-07-15: dropped the earlier Mailgun-primary/Amazon-SES-fallback design — single provider, no fallback.]
- Media: AWS S3 (client's existing bucket) via django-storages
- Search: Meilisearch (typo-tolerant, synonyms, facets)

---

## 0. How to use this document

1. Stages are named `Plan-NN-<slug>` and MUST be executed in numeric order (parallel-safe stages are marked).
2. Each stage lists: **Objective, Depends on, Files, Specification, Verification, Checkpoint.**
3. "Verification" means actually running the thing — dev server up, request made, response inspected, tests green. Never declare a stage done on a successful typecheck alone.
4. Commit style: conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Commit small and often. Never commit `.env*` files or any secret.
5. When a stage requires a credential you don't have (Paystack keys, Resend API key, S3 keys, Cloudflare access, GitHub repo creation, Vercel account), STOP and ask Hammed for it. Never invent or hardcode placeholder secrets into committed code — use `.env` + documented variable names (Appendix A).
6. Hammed is a non-developer CTO. Explain what you did in plain language at every checkpoint. Show, don't tell (URLs to click, screenshots, test output).

## 1. Non-negotiable ground rules (live production environment)

The VPS you will deploy to **currently serves the live, revenue-generating WordPress stores**. Until cutover:

- **READ-ONLY on everything WordPress.** Migration scripts read the MySQL/MariaDB databases and copy files. They never UPDATE/DELETE WP tables, never edit WP files, never deactivate plugins.
- Anything destructive on the VPS (config edits, service restarts, package installs): show Hammed the exact command and back up the affected file first (`cp file file.bak-YYYYMMDD`).
- SSH access: `ssh tokecosmetics "<command>"` (alias for root@203.161.38.201, key-based, defined in `C:\Users\Hammed\.ssh\config`).
  **PowerShell quoting gotcha:** PowerShell does not escape `$` with backslash. Wrap remote commands that contain `$VAR` or `$(...)` in **single quotes**.
- Server RAM is 6 GB total, ~4 GB available, shared with the live WP stack (Apache, MariaDB, Exim, BIND). Set explicit memory limits on every Docker container (Plan-02). If the server becomes slow, the live store loses money — check `free -h` before and after starting services.
- The site was hacked and cleaned on 2026-06-17 (WP malware). Treat any unexpected PHP file with suspicion, but note: hash-named `*.php` files containing `BVUNTAR2` in the docroots are legitimate BlogVault backup-plugin helpers — leave them alone.
- `wp-cli` gotcha (if you ever must use it, read-only): `wp ... --allow-root` leaves root-owned files; `chown -R tokecosm:tokecosm` anything touched.

## 2. Verified facts (audited 2026-07-12 — trust these, but re-verify counts in Plan-00)

**Server (Namecheap "Quasar" VPS):** Ubuntu 22.04.5 · 4 vCPU · 5.8 GB RAM · 118 GB disk (50% used) · Webuzo panel · Apache (ports 80/443) · PHP 8.1 · MariaDB on 3306 · Exim/Dovecot · BIND. Both domains are proxied through **Cloudflare** (orange-cloud), so public DNS and origin-port routing are managed in the Cloudflare dashboard.

**NG store — tokecosmetics.com** (docroot `/home/tokecosm/public_html`):
- MySQL DB `tokecosm_wp481`, table prefix `wp_`
- WooCommerce with **HPOS enabled** → orders live in `wp_wc_orders` (+ `wp_wc_order_addresses`, `wp_wc_order_operational_data`, `wp_woocommerce_order_items`, `wp_woocommerce_order_itemmeta`), **NOT** in `wp_posts`
- 69 published products, 81 product variations, 40 product categories
- 2,765 orders, all NGN, dated 2025-11-24 → 2026-07-12 (statuses: 797 completed, 1,464 on-hold, 494 cancelled, 2 processing, 8 trash)
- 1,211 WP users, 5,219 coupons (almost certainly bulk-generated — audit before migrating), 0 product reviews
- Media: 6.4 GB in `wp-content/uploads`

**International store — tokecosmeticsintl.com** (docroot `/home/tokecosm/tokecosmeticsintl.com`, **same VPS**):
- MySQL DB `tokecosm_usawp100`, table prefix `wp8n_`, HPOS enabled (`wp8n_wc_orders`)
- 94 published products, 120 orders in USD/GBP/CAD/NGN, dated 2024-04-19 → 2026-06-27, 51 users
- Media: 1.1 GB

**Open questions Plan-00 must answer:** (a) NG order history only starts 2025-11-24 — check the `old.tokecosmetics.com` subdomain docroot and the `wpstg0_`-prefixed staging tables for an older order archive; (b) whether the 5,219 coupons are one-off generated codes (migrate only active, unexpired ones); (c) reconcile `tokecosmetics_customers.csv` (sitting in this project folder) against `wp_users`.

**DB credentials:** read them from the wp-config files on the server; never write them into the repo:
`grep DB_ /home/tokecosm/public_html/wp-config.php` and `grep DB_ /home/tokecosm/tokecosmeticsintl.com/wp-config.php`.

## 3. Target architecture

```
                        ┌─────────────── Cloudflare DNS/proxy ───────────────┐
                        │                                                     │
  tokecosmetics.com ────┤ (after cutover; next.tokecosmetics.com until then)  │
        │               │                                                     │
        ▼               │                                                     ▼
  ┌───────────────┐     │   ┌────────────────────┐          ┌─────────────────────────────┐
  │ VERCEL        │     │   │ VERCEL             │          │ NAMECHEAP VPS 203.161.38.201│
  │ storefront/   │     │   │ admin/             │          │  Docker Compose:            │
  │ Next.js (SSR/ │─────┼──▶│ Next.js portal     │─────────▶│   django-web (gunicorn)     │
  │ ISR, SEO)     │   api.tokecosmetics.com (HTTPS)         │   celery-worker             │
  └───────────────┘         └────────────────────┘          │   celery-beat               │
                            backend.tokecosmetics.com       │   postgres:16               │
                                                            │   redis:7                   │
   AWS S3 (product media, uploads)                          │   meilisearch               │
   Resend (email, sole provider)                            │  + existing WP stack (live  │
   Paystack/Flutterwave/Stripe/PayPal (payments)            │    until cutover)           │
                                                            └─────────────────────────────┘
```

**Domain plan:**

| Domain | Serves | Where |
|---|---|---|
| `api.tokecosmetics.com` | Django REST API (`/api/v1/...`), Django admin fallback (`/django-admin/`, IP-restricted) | VPS |
| `backend.tokecosmetics.com` | Next.js admin portal | Vercel |
| `next.tokecosmetics.com` | Next.js storefront (testing/UAT) | Vercel |
| `tokecosmetics.com` | Storefront after cutover (Plan-27); until then, live WP | WP → Vercel |
| `tokecosmeticsintl.com` | After cutover: 301-redirects to tokecosmetics.com (Plan-24) | Cloudflare rule |

**Monorepo layout (single GitHub repo `tokecosmetics-platform`):**

```
tokecosmetics-platform/
├── backend/                  # Django project
│   ├── config/               # urls.py, celery.py, asgi/wsgi
│   │   └── settings/         # base.py, dev.py, prod.py
│   ├── apps/
│   │   ├── core/             # Country, Currency, SiteSetting, Redirect, base models/utils
│   │   ├── accounts/         # User, Address, auth, WP password hasher
│   │   ├── catalog/          # Product, Variant, Category, Brand, Collection, Tag, media
│   │   ├── pricing/          # Price rows, price resolution service, sale/scheduled prices
│   │   ├── inventory/        # Warehouse, StockItem, StockMovement, reservations
│   │   ├── carts/            # Cart, CartItem
│   │   ├── checkout/         # shipping zones/methods/rates, tax, coupons, checkout orchestration
│   │   ├── orders/           # Order, OrderItem, fulfillment, invoices
│   │   ├── payments/         # gateway abstraction, Paystack/Flutterwave/Stripe/PayPal, webhooks
│   │   ├── reviews/          # product reviews & ratings
│   │   ├── wishlist/
│   │   ├── cms/              # HomepageSection, Banner, Page, MenuItem
│   │   ├── notifications/    # email templates + senders (Celery tasks)
│   │   ├── analytics/        # report queries, dashboard aggregates
│   │   ├── searchsync/       # Meilisearch index sync
│   │   └── migration_wp/     # WooCommerce importers (management commands)
│   ├── manage.py
│   ├── pyproject.toml        # managed with uv
│   ├── Dockerfile
│   └── pytest.ini
├── storefront/               # Next.js customer site
├── admin/                    # Next.js admin portal
├── infra/
│   ├── docker-compose.prod.yml
│   ├── proxy/                # api vhost config (Plan-02 decides Apache include vs nginx container)
│   └── deploy/               # deploy.sh, backup.sh, restore.sh
├── docs/                     # audit.md, architecture.md, runbooks, ADRs
└── .github/workflows/        # ci-backend.yml, deploy-backend.yml
```

## 4. Decisions already made (with reasons — do not relitigate)

1. **MVP-first (Hammed approved).** Cutover scope = Plans 00–27. Explicitly deferred to post-launch (Plans 28+ or backlog — deferred, NOT forgotten; dev_prompt.txt remains the requirement source): accounting module, loyalty points/rewards, referrals, store credits, gift cards, abandoned-cart *emails*, SMS campaigns, push notifications, blog, personalized recommendations, product bundles/combos, pre-order/backorder, digital products, subscriptions, social login (Google/Apple/Facebook), staff 2FA, carrier API integrations — DHL/GIG rates, booking, labels, live tracking (Plan-32; manual delivery options cover launch). (Multi-warehouse is NOT deferred — Lagos + UK stock is live reality, see decision 10. Guest checkout is not deferred either — it is REMOVED, see decision 7.)
2. **Admin = separate Next.js app on Vercel (Hammed approved),** consuming the same DRF API with staff-scoped JWT + RBAC. Django Admin remains enabled at `api.tokecosmetics.com/django-admin/` as a low-level fallback, IP-restricted.
3. **Payments (all four approved):** Paystack + Flutterwave (NGN) and Stripe (+ Apple Pay/Google Pay via Stripe Payment Element) + PayPal (international). One `payments.gateways.base.PaymentGateway` interface; each gateway is a subclass. Nigerian bank transfer = Paystack dedicated account / manual "awaiting payment confirmation" flow.

   > **[2026-07-16 — SUPERSEDED FOR LAUNCH. Hammed's decision: LAUNCH ON BANK TRANSFER ONLY.]**
   > The four networked gateways stay **code-complete but DEACTIVATED** — their test-mode
   > API keys never arrived and Plan-09's mandatory sandbox checkpoint was blocking
   > everything behind it. Deactivating them retires that blocker: uncertified code that
   > cannot be reached takes no money. They are switched back on, per country, only after
   > the sandbox checkpoint is actually done — **that checkpoint is deferred, not
   > cancelled** (see Plan-09).
   >
   > **Bank transfer becomes the only live method, enabled per country, and each enabled
   > country supplies its own bank account details.** This inverts the risk profile of the
   > whole build: what was a fringe NG option is now the single path every order takes, so
   > the manual-confirmation work that Plan-18 owned is now the critical path — without it
   > **no order can ever be fulfilled, in any country**. It is pulled forward into
   > **Plan-09b** (below); Plan-18 keeps only the UI.
   >
   > Trade-off Hammed accepted knowingly: every order needs a human to confirm the money
   > arrived. That is a staffing cost per order and it does not scale — the intended exit
   > is Paystack dedicated accounts (webhook-confirmed, a real `verify()`), which is why
   > the manual flow must not grow features that assume it is permanent.
4. **Email:** Resend, sole provider via anymail (sending domain mg.tokecosmetics.com). The send wrapper sends via the single default backend; there is no provider fallback — transient failures are retried by the Celery task. **Media:** client's AWS S3 bucket via django-storages; Next/Image handles resizing on Vercel (add the S3 hostname to `images.remotePatterns`).
5. **One database, data-driven countries.** `Country` and `Currency` are rows, not code branches. Nigeria/UK/US/Canada seeded; adding a country = adding rows (currency, shipping zone, payment gateway mapping, tax rule). No code duplication per country — this is the core requirement.
6. **Currency & pricing:** every sellable variant has explicit prices per active currency (NGN, GBP, USD, CAD). NO automatic FX conversion at launch (NGN rates too volatile; merchant sets prices deliberately). Schema supports country-specific overrides, sale prices and scheduled prices from day one.
7. **Auth pattern:** SimpleJWT. Access token 15 min, refresh 30 days with rotation + blacklist. Browsers never store tokens in localStorage: both Next.js apps proxy auth through Route Handlers that keep tokens in **httpOnly, Secure, SameSite=Lax cookies** (BFF pattern). Social login (Google/Apple/Facebook) is post-MVP. **Checkout REQUIRES an account (Hammed, 2026-07-12 — this supersedes the guest-checkout line in dev_prompt.txt):** anonymous visitors can browse and fill a cart, but placing an order needs login. To protect conversion, checkout step 1 is an INLINE signup (email + name + password, account created silently) — a 30-second step inside checkout, never a detour to a separate register page. Every order therefore belongs to a user with a Toke ID.
8. **Search:** Meilisearch container (~200 MB RAM cap). If VPS memory pressure proves too high in Plan-02 verification, fallback is Postgres full-text search behind the same `/search` API contract — the API consumer never knows.
9. **Order numbers:** new orders `TC-<seq>` starting at 100001. Migrated orders keep their WooCommerce number in `legacy_number` + `source` (`legacy_ng` / `legacy_intl`) and display it everywhere.
10. **Stock (updated 2026-07-12 after Hammed's clarification):** ONE inventory system, MULTIPLE physical warehouses — stock physically sits in **Lagos and the UK today**, more countries later. Stock is tracked **per warehouse, never per country**: each warehouse declares which countries it serves (`serves_countries`), and "stock available in country X" = sum of available stock across warehouses serving X. Admin sets stock per warehouse; the per-country availability number is computed. Never split one physical stock pile into per-country quotas — that manufactures artificial stockouts. Checkout **reserves** stock (row-level `select_for_update`) from serving warehouses in priority order, payment success **commits** it, expiry/failure releases it. This kills overselling races. Seed warehouses: "Lagos HQ" (serves NG; RoW backup) and "UK Warehouse" (serves GB, US, CA, Rest of World) — mapping editable in admin.
11. **VPS deploy:** everything new lives in Docker under `/opt/tokecosmetics`, isolated from Webuzo. Deploys = GitHub Actions → SSH → `git pull && docker compose up -d --build`. Rollback = `git checkout <previous-tag> && docker compose up -d --build`.
12. **Toke ID (Hammed approved):** every user gets a permanent public customer ID, format `TK-` + 6 chars from the unambiguous alphabet `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (no 0/O/1/I/L) — e.g. `TK-7X4KQZ`. ~1.5 billion combinations, random (leaks nothing), readable over the phone. Shown in the account area, order emails, and admin; searchable in admin. Migrated customers get one at import.
13. **Delivery = region-based options, mixed granularity (Hammed approved):** a `Region` tree per country (Nigeria seeded with all 36 states + FCT and their 774 LGAs from a bundled fixture; other countries can add cities/areas later as pure data). Admin-created **delivery options** carry name + price + covered regions, where coverage can point at ANY tree level — one option may cover "Lagos State" wholesale (zone-style) while another covers 3 specific LGAs; both can coexist, even in Nigeria. Countries without region detail use whole-country coverage (today's intl flat/weight rates). **DHL/GIG API integrations are post-launch (Plan-32)** — at launch they exist as manually-priced options; the carrier interface is stubbed so plugging APIs in later changes no checkout code.
14. **Amazon-pattern buying UX (Hammed approved):** PDP has a buy box with BOTH "Add to Cart" and "Buy Now" (Buy Now jumps straight into checkout with just that item); checkout is the Amazon sequence — sign in (inline signup) → choose delivery address from the address book → delivery options priced FOR that address → payment → review & place order.

## 5. API conventions (all backend stages follow these)

- Base path `https://api.tokecosmetics.com/api/v1/`. Version in URL; breaking changes → `/api/v2/`.
- OpenAPI schema auto-generated by drf-spectacular at `/api/schema/`, Swagger UI at `/api/docs/` (staff-only in prod).
- Pagination: DRF `PageNumberPagination`, `page_size=24`, max 100, response shape `{count, next, previous, results}`.
- Errors: DRF default shape; always JSON, never HTML errors on `/api/`.
- Country/currency context: every storefront request carries `X-Country: NG|GB|US|CA|ZZ` (set by the storefront from the user's choice / GeoIP). `ZZ` = "Rest of World" — visitors from any country that isn't an active market get USD pricing and CAN check out (worldwide shipping, Hammed approved). Prices in responses are already resolved for that context — the storefront NEVER does price math.
- Write endpoints that create money-things (orders, payments) accept an `Idempotency-Key` header; the backend stores key→response for 24h in Redis and replays the stored response on retry.
- Throttling: DRF throttles — anon 60/min, user 120/min, auth endpoints 10/min per IP (tighter rules in Plan-25).
- All list endpoints filterable via django-filter and ordered deterministically (always a stable `ordering`).

## 6. Stage index

| Stage | What | Blocks |
|---|---|---|
| Plan-00-audit | Deep audit of both WP stores, written to docs/audit.md | everything |
| Plan-01-scaffold | GitHub monorepo, Django + 2 Next.js apps boot locally | everything |
| Plan-02-vps-provision | Docker stack on VPS, api.tokecosmetics.com live over HTTPS | deploys |
| Plan-03-django-core | Settings, custom User, JWT, S3, email, Celery, health checks | all backend |
| Plan-04-countries-pricing | Country/Currency models + price resolution service | catalog, checkout |
| Plan-05-catalog | Products/variants/categories/brands APIs | storefront, admin |
| Plan-06-inventory | Warehouses, stock, reservations | checkout |
| Plan-07-search | Meilisearch indexing + /search API | storefront |
| Plan-08-cart-checkout | Carts, region/LGA delivery options, coupons, auth-only checkout, Buy Now | payments |
| Plan-09-payments | 4 gateways + webhooks + refunds — **code-complete, DEACTIVATED at launch; sandbox checkpoint deferred** | orders |
| Plan-09b-manual-payments | **Bank transfer as the only live method**: per-country bank accounts, currency enforcement, admin confirm-receipt API, manual-gateway TTL | **launch** |
| Plan-10-orders | Order lifecycle, emails, invoices | admin, migration |
| Plan-11-accounts | Registration/login/addresses/wishlist/reviews APIs | storefront account |
| Plan-12-storefront-foundation | Design system, layout, country switcher | 13–15 |
| Plan-13-storefront-catalog-seo | Home/PLP/PDP/search + full SEO | UAT |
| Plan-14-storefront-checkout | Cart → checkout → pay UX | UAT |
| Plan-15-storefront-account | Login, dashboard, order history | UAT |
| Plan-16-admin-foundation | Admin app auth + RBAC + layout | 17–20 |
| Plan-17-admin-catalog-inventory | Product & stock management UI | UAT |
| Plan-18-admin-orders-customers | Order & customer management UI | UAT |
| Plan-19-admin-marketing-cms | Coupons, banners, homepage, pages UI | UAT |
| Plan-20-admin-dashboard-reports | KPIs + reports + CSV/Excel export | UAT |
| Plan-21-migration-products | NG catalog + images → new platform | 22–24 |
| Plan-22-migration-customers | Customers with orders, WP password compat | 23 |
| Plan-23-migration-orders | Order history from BOTH stores | UAT |
| Plan-24-migration-seo-redirects | Slug preservation, 301 map, redirect middleware | cutover |
| Plan-25-qa-hardening | Security, performance, accessibility, test sweep | UAT |
| Plan-26-staging-uat | next.tokecosmetics.com live, UAT checklist with Hammed | cutover |
| Plan-27-cutover | DNS switch runbook, delta order sync, monitoring | launch |
| Plan-28-accounting | Post-launch: lightweight Sage-like module | — |
| Plan-29-loyalty-referrals | Post-launch | — |
| Plan-30-marketing-automation | Post-launch: abandoned cart, campaigns, SMS | — |
| Plan-31-blog-content | Post-launch | — |
| Plan-32-carrier-integrations | Post-launch: DHL + GIG Logistics APIs (rates, booking, tracking) | — |

---
# PHASE A — FOUNDATIONS

## Plan-00-audit

**Objective:** Produce `docs/audit.md` — a complete, verified picture of both WP stores so migration stages have zero surprises. **Read-only. No writes to anything WordPress.**

**Depends on:** nothing.

**Specification — answer every one of these in docs/audit.md:**
1. Re-verify the counts in Section 2 (products, variations, orders, users, coupons, media sizes) with the exact SQL used.
2. **Old NG orders:** inspect `old.tokecosmetics.com` docroot (find it in `/usr/local/apps/apache2/etc/conf.d/webuzoVH.conf`) and any DB it points to; inspect `wpstg0_`-prefixed tables in `tokecosm_wp481`. Report whether pre-Nov-2025 orders exist anywhere and how many. If yes, they join the Plan-23 scope.
3. **Product shape:** list all product types in use (`simple`, `variable`), all attributes (`wp_terms` where taxonomy LIKE `pa_%`), brands taxonomy if any, sample 3 full products with all postmeta (`_price`, `_regular_price`, `_sale_price`, `_sku`, `_stock`, `_stock_status`, `_weight`, images `_thumbnail_id` / `_product_image_gallery`).
4. **Order shape (HPOS):** dump 3 full sample orders from each store: `wp_wc_orders` row + addresses + operational data + `wp_woocommerce_order_items` + itemmeta. Document which payment gateways appear (`payment_method` column distinct values) and what statuses map to what.
5. **Customers:** how many of the 1,211 NG users have ≥1 order (join `wp_wc_orders.customer_id`)? Same for intl. How many distinct guest-checkout emails (orders with `customer_id=0`)? Password hash formats present in `wp_users.user_pass` (`$P$`, `$2y$`, `$wp$2y$` — count each with SQL LIKE). Reconcile against `tokecosmetics_customers.csv` in the project root.
6. **Coupons:** of the 5,219, how many are unexpired and how many were ever used (`_used_by` meta / `usage_count`)? Recommend a migrate list (expect: only active + historically-referenced ones).
7. **SEO:** which SEO plugin (Yoast/RankMatch — check `wp_options` for `wpseo%` / `rank_math%`), permalink structure (`permalink_structure` option), export the full list of live product/category/page URLs for both sites (`wp post list` alternatives via SQL on `post_name`), current sitemap URLs.
8. **Plugins in use** on both sites (read `wp_options.active_plugins`) — flag any feature the new build must replicate (e.g. currency switcher plugin on intl, points/rewards, subscriptions).
9. **Payment configs** currently live (Paystack/others) — gateway IDs in `wp_options` `woocommerce_*_settings` keys (do NOT copy secret keys into the doc; note only which gateways are configured).
10. Shipping zones/methods/rates currently configured (`wp_woocommerce_shipping_zones`, `..._zone_methods` + options) for both stores — these become the seed data for Plan-08, including whatever international/worldwide rates the intl store charges today (basis for the Rest-of-World zone).
11. Intl-store stock levels per SKU (`_stock` postmeta in `tokecosm_usawp100`) and how they overlap with NG SKUs — this seeds the **UK warehouse** in Plan-21 (stock physically sits in both Lagos and the UK, per Hammed 2026-07-12).

**Verification:** every claim in audit.md carries the SQL/command that produced it. Someone else could re-run it.

**CHECKPOINT:** present audit.md summary to Hammed; explicitly confirm (a) the coupon migrate list, (b) whether older NG orders were found, (c) the shipping rate table interpretation.

---

## Plan-01-scaffold

**Objective:** Monorepo on GitHub; Django backend and both Next.js apps run locally with one command each; CI runs backend tests on every push.

**Depends on:** Plan-00. **Needs from Hammed:** GitHub account/org choice, repo creation (or a PAT), Vercel account connected to the repo.

**Files:** the entire Section-3 monorepo skeleton.

**Specification:**
1. `git init` in `C:\Users\Hammed\Desktop\TokeCosmeticsDev\tokecosmetics-platform`, push to GitHub as private repo `tokecosmetics-platform`, default branch `main`. Root `.gitignore` covers Python, Node, `.env*`, `*.bak-*`.
2. Backend: `uv init` in `backend/`, Python 3.12, Django 5.2. Create `config/settings/{base,dev,prod}.py` (dev = SQLite fallback allowed for pure-local hacking, but default dev DB = the docker-compose Postgres below). Add `docker-compose.dev.yml` at repo root running Postgres 16 + Redis 7 + Meilisearch for local dev. `python manage.py runserver` boots; `/healthz/` returns `{"status": "ok", "db": true, "redis": true}`.
3. Storefront: `npx create-next-app@latest storefront` — TypeScript, Tailwind, App Router, `src/` dir. Install shadcn/ui, TanStack Query, react-hook-form, zod. Home page renders "Toke Cosmetics — coming soon".
4. Admin: same scaffold in `admin/`, renders a login placeholder page.
5. CI: `.github/workflows/ci-backend.yml` — on push/PR: uv sync, ruff check, pytest (with Postgres service container). Frontends: `next build` job for each app (Vercel will do real deploys via its Git integration later).
6. Write `docs/architecture.md` = condensed Section 3 + 4 of this file, kept current from now on.

**Verification:** fresh clone → `docker compose -f docker-compose.dev.yml up -d` → backend `pytest` green (with at least one real test: healthz endpoint) → both `npm run dev` apps load in a browser. CI green on GitHub.

**CHECKPOINT:** show Hammed the repo URL and green CI badge.

---

## Plan-02-vps-provision

**Objective:** Production runtime on the VPS: Docker Compose stack under `/opt/tokecosmetics`, `https://api.tokecosmetics.com/healthz/` returns 200 through Cloudflare, automated DB backups, WITHOUT disturbing the live WP stack.

**Depends on:** Plan-01. **Needs from Hammed:** Cloudflare dashboard access (DNS + SSL settings), confirmation before each system-level install.

**Specification:**
1. Install Docker Engine + compose plugin on the VPS (official apt repo). Confirm with Hammed first (system-level change on a production box).
2. `/opt/tokecosmetics/` = git clone of the repo (deploy key, read-only). `.env.prod` lives here (never in git), owner root, chmod 600.
3. `infra/docker-compose.prod.yml` services (all bound to 127.0.0.1 only — NOTHING except the reverse proxy is publicly reachable):
   - `postgres:16-alpine` — volume `/opt/tokecosmetics/data/pg`, `mem_limit: 1g`, port 127.0.0.1:5433
   - `redis:7-alpine` — `mem_limit: 256m`, `--maxmemory 200mb --maxmemory-policy allkeys-lru`, port 127.0.0.1:6380
   - `getmeili/meilisearch:v1.x` — volume for index, `mem_limit: 512m`, `MEILI_MASTER_KEY` from env, port 127.0.0.1:7700
   - `web` — build `backend/Dockerfile`, gunicorn `config.wsgi` with 3 workers, `mem_limit: 768m`, port 127.0.0.1:8001
   - `worker` — same image, `celery -A config worker -c 2`, `mem_limit: 512m`
   - `beat` — same image, `celery -A config beat`, `mem_limit: 128m`

   > **[2026-07-16, Plan-10] `backend/Dockerfile` MUST apt-install WeasyPrint's native
   > libraries or every invoice download 500s:** `libpango-1.0-0 libpangoft2-1.0-0`
   > (Debian/Ubuntu base). WeasyPrint is a pip dep but is a binding over Pango/cairo —
   > `pip install` alone is NOT enough, and the failure is an ImportError at *runtime*,
   > not at build. Verified rendering on `python:3.12-slim` + those two packages.
   > `web` needs them (invoices render on demand in the request path, per Plan-10);
   > `worker` does not, but it's the same image so it gets them anyway.
   > Note this is why invoices cannot be rendered on a Windows dev box — there is no
   > Pango. Local verification path: run the render inside a Linux container.
4. **Exposing the API (decision tree — try (a); if Webuzo overwrites it, use (b)):**
   (a) Preferred: add an Apache vhost include for `api.tokecosmetics.com` proxying to `127.0.0.1:8001` (`ProxyPass / http://127.0.0.1:8001/`, `ProxyPreserveHost On`, websocket not needed). Webuzo manages `webuzoVH.conf` — put the vhost in a separate conf file loaded via the main httpd.conf `IncludeOptional` if available, and verify it survives a Webuzo settings save.
   (b) Fallback: run an `nginx:alpine` container listening on host port **8443** with a **Cloudflare Origin CA certificate** (valid 15 years, issued in dashboard) proxying to `web:8000`; in Cloudflare create A record `api → 203.161.38.201` (proxied) + an **Origin Rule** rewriting the destination port for `api.tokecosmetics.com` to 8443. Cloudflare handles public TLS.
   Either way: force HTTPS, set `SECURE_PROXY_SSL_HEADER`, restrict `/django-admin/` by IP allowlist (Hammed's IP) at the proxy level.
5. Cloudflare DNS (with Hammed at the dashboard): `api` A → VPS (proxied). SSL mode "Full (strict)" for that hostname.
6. Backups: `infra/deploy/backup.sh` — nightly cron: `pg_dump` to `/opt/tokecosmetics/backups/` (keep 14), then `aws s3 cp` to the client S3 bucket under `backups/postgres/`. Test a restore once (`restore.sh` into a scratch DB) and document it in `docs/runbooks/restore.md`.
7. Deploy pipeline: `.github/workflows/deploy-backend.yml` — on push of tag `backend-v*`: SSH to VPS, `cd /opt/tokecosmetics && git fetch && git checkout <tag> && docker compose -f infra/docker-compose.prod.yml up -d --build && docker compose exec -T web python manage.py migrate --noinput && docker compose exec -T web python manage.py collectstatic --noinput`. Store the SSH private key as a GitHub Actions secret (generate a NEW deploy-only keypair; do not reuse Hammed's personal key).
8. Resource guardrail: after `up -d`, record `free -h` and `docker stats --no-stream` in the checkpoint report. Total new-stack RSS must stay under ~3 GB.

**Verification:** `curl -s https://api.tokecosmetics.com/healthz/` → `{"status":"ok",...}` from the outside world; live WP store still loads fast; backup file appears and restore test passes.

**CHECKPOINT:** show Hammed the healthz URL, `docker stats` output, and the backup in S3. Get explicit sign-off that the WP site feels unaffected.

---

## Plan-03-django-core

**Objective:** Backend foundation every later stage builds on: settings, custom user, JWT auth endpoints, S3 media, Resend email (sole provider), Celery wired, OpenAPI docs, security headers.

**Depends on:** Plan-01 (deployable after Plan-02).

**Files:** `backend/config/settings/*`, `backend/apps/core/`, `backend/apps/accounts/`, `backend/config/celery.py`.

**Specification:**
1. **Custom user (do this before ANY migration is created — hard to change later):**
```python
# apps/accounts/models.py
class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)          # USERNAME_FIELD
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    toke_id = models.CharField(max_length=9, unique=True, editable=False)   # public customer id, e.g. "TK-7X4KQZ"
    marketing_consent = models.BooleanField(default=False)
    legacy_source = models.CharField(max_length=20, blank=True)   # "", "legacy_ng", "legacy_intl"
    legacy_wp_id = models.IntegerField(null=True, blank=True)
    USERNAME_FIELD = "email"

TOKE_ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # no 0/O/1/I/L — phone-friendly

def generate_toke_id() -> str:
    """'TK-' + 6 random chars. Called by the User manager on create inside a
    small retry loop (regenerate on the rare unique-constraint collision)."""
    import secrets
    return "TK-" + "".join(secrets.choice(TOKE_ID_ALPHABET) for _ in range(6))
```
   Plus, in `apps/core/models.py`, the geographic `Region` tree (defined now so `Address` can reference it; SEEDED in Plan-08):
```python
class Region(models.Model):
    country_code = models.CharField(max_length=2, db_index=True)   # ISO code — any country, not only active markets
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=10, choices=[("state","State/Region"),("city","City"),("area","LGA/Area")])
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    is_active = models.BooleanField(default=True)
    class Meta:
        unique_together = [("country_code", "parent", "name")]
```
   `Country` gets `area_label = models.CharField(max_length=30, default="Area")` — the local name for the finest level: "LGA" for NG, "Borough/District" for GB, "County" for US, etc. Admin and storefront labels read this field (Hammed: "make room for what LGA is called for other countries").

   `Address` model — **structured per country** (Hammed requires it; the checkout address form adapts):
```python
class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=40, blank=True)            # "Home", "Office"
    first_name/last_name/phone = CharField(...)
    line1 = models.CharField(max_length=255); line2 = models.CharField(max_length=255, blank=True)
    country_code = models.CharField(max_length=2)                  # any ISO country (worldwide shipping)
    state_region = models.ForeignKey("core.Region", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    area_region = models.ForeignKey("core.Region", null=True, blank=True, on_delete=models.PROTECT, related_name="+")  # the LGA/city row
    city_text = models.CharField(max_length=100, blank=True)       # free text where no Region data exists
    state_text = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    is_default_shipping / is_default_billing = BooleanField
```
   Validation rule: if the country HAS seeded regions (NG at launch), `state_region` is required and `area_region` (LGA) required when the state has children — dropdowns, not typing. Countries without region data use the `*_text` fields + postcode (postcode required for GB/US/CA). One serializer, per-country required-fields map in `apps/core/address_rules.py`.
2. **JWT:** SimpleJWT with rotation + blacklist app. Endpoints under `/api/v1/auth/`: `register`, `token` (login), `token/refresh`, `logout` (blacklist), `password/reset` + `password/reset/confirm` (emailed token), `me` (GET/PATCH). Register validates password with Django validators; duplicate email returns a clean 400 `{"email": ["Account already exists"]}`.
3. **Password hashers** setting includes the WordPress hasher (full code in Plan-22) *behind* the default so migrated users can log in and get transparently rehashed.
4. **Email:** anymail; `EMAIL_BACKEND` = `anymail.backends.resend.EmailBackend` (Resend is the sole provider; sending domain mg.tokecosmetics.com, `DEFAULT_FROM_EMAIL` on that domain). Implement `apps/notifications/send.py::send_email(template_name, to, context)` that renders MJML-free simple HTML+text templates from `apps/notifications/templates/email/` and sends via the default backend. No provider fallback — a send failure bubbles up and the Celery task `send_email_task` retries with backoff. All calls go through that task.
5. **Storage:** django-storages S3 backend for `MEDIA` (bucket from env, `AWS_S3_CUSTOM_DOMAIN` optional, `AWS_QUERYSTRING_AUTH=False` for public product images under `media/catalog/`, private for invoices under a signed prefix). Static files: whitenoise (only Django admin uses them).
6. **Celery:** `config/celery.py` standard app, Redis broker/result, beat schedule placeholder. One demo task `core.tasks.ping` and a beat entry running it every 5 min in dev only.
7. **Security baseline now, not later:** `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `X_FRAME_OPTIONS="DENY"`, `SECURE_REFERRER_POLICY`, CORS allowlist = the three frontend origins only, DRF default throttles (Section 5), `ATOMIC_REQUESTS=True`.
8. **Core app models:** `SiteSetting` (singleton key/value with typed accessor), `Redirect(old_path unique, new_path, status_code default 301, hits)` — used in Plan-24.
9. drf-spectacular wired: `/api/schema/`, `/api/docs/`.

**Verification:** pytest suite covering: register→login→refresh→me→logout flow; password reset email lands (console/locmem backend in tests); an uploaded image lands in S3 (manual smoke with real creds); `celery worker` processes `ping`. Run the flow against the deployed VPS stack too.

**CHECKPOINT:** show Hammed Swagger UI at `/api/docs/` and a test email delivered to his inbox via Resend. [Done 2026-07-15: live Resend send accepted, message id 618bccf2-2264-4ddf-835e-eb6618902fb8.]

---

## Plan-04-countries-pricing

**Objective:** The country/currency backbone + a single price-resolution service used by catalog, cart, checkout, and orders.

**Depends on:** Plan-03.

**Files:** `apps/core/models.py` (Country, Currency), `apps/pricing/` (models, `services.py`, tests).

**Specification:**
1. Models:
```python
# apps/core/models.py
class Currency(models.Model):
    code = models.CharField(max_length=3, primary_key=True)   # NGN, GBP, USD, CAD
    symbol = models.CharField(max_length=8)                   # ₦, £, $, CA$
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True)   # NG, GB, US, CA
    name = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)           # NG
    is_rest_of_world = models.BooleanField(default=False)     # the ZZ catch-all context
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # simple flat VAT; 7.5 NG, 20 GB, 0 US (see note), 0 CA
    prices_include_tax = models.BooleanField(default=True)
```
   Note: US/CA sales-tax-by-state is explicitly OUT of MVP scope — flat configurable rate per country, refine post-launch. Record this in docs/architecture.md.
2. Seed migration: NGN/GBP/USD/CAD + NG/GB/US/CA (NG default, NG 7.5% incl., GB 20% incl., US 0%, CA 0%) **+ a "Rest of World" row: `code="ZZ"` (ISO 3166 user-assigned code — never collides with a real country), name "International", currency USD, tax 0, `is_rest_of_world=True`.** Visitors from any non-market country shop in this context: USD prices, Stripe/PayPal, Rest-of-World shipping zone.
3. Pricing model:
```python
# apps/pricing/models.py
class Price(models.Model):
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="prices")
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    country = models.ForeignKey("core.Country", null=True, blank=True, on_delete=models.CASCADE)  # NULL = all countries using this currency
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # strikethrough
    starts_at = models.DateTimeField(null=True, blank=True)   # scheduled/sale windows
    ends_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["variant","currency","country","starts_at"], name="uniq_price_scope")]
```
   **Migration-ordering note:** `Price` has an FK to `catalog.ProductVariant`, which is created in Plan-05. Write the `Price` model and `resolve_price` service now (FK as the string reference shown), but generate/run the `pricing` DB migration at the START of Plan-05, right after the catalog models exist. Full `resolve_price` tests run in Plan-05 once variants are real; the Country/Currency tests run now.
4. Resolution service (THE only way any code gets a price):
```python
# apps/pricing/services.py
def resolve_price(variant, country: Country, at=None) -> ResolvedPrice | None:
    """Order: (1) active window price for (currency, country) exact match,
    (2) active window price for (currency, country=NULL),
    (3) non-windowed price for (currency, country), (4) (currency, NULL).
    Returns None if the variant is not sellable in this country (storefront hides it)."""
```
   `ResolvedPrice` = dataclass(amount, compare_at, currency, tax_rate, prices_include_tax). Unit tests must cover: country override beats currency default; expired sale window ignored; missing currency → None; NG default.
5. `X-Country` request middleware/DRF helper: resolves header → Country instance, attaches as `request.country`. Fallback chain: header missing → NG (default); header names an inactive/unknown country → the `is_rest_of_world` row (ZZ). The storefront sends ZZ whenever GeoIP/user choice lands outside active markets.

**Verification:** pytest for every resolution branch; `/api/v1/meta/countries/` endpoint returns active countries+currencies for the storefront switcher.

**CHECKPOINT:** short — show Hammed the test list and countries endpoint output.

---
# PHASE B — COMMERCE BACKEND

## Plan-05-catalog

**Objective:** Full product catalog models + read APIs for the storefront + write APIs for the admin.

**Depends on:** Plan-04.

**Files:** `apps/catalog/` (models.py split into `models/product.py`, `models/taxonomy.py`, `models/media.py` if large; serializers, views, urls, tests, factories).

**Specification:**
1. Models (key fields only — add `created_at/updated_at` on everything via a `TimeStampedModel` base in core):
   - `Category(name, slug unique, parent FK self null, description, image, is_active, sort_order, seo_title, seo_description)` — tree via parent FK + `get_ancestors()` helper (no MPTT dependency; depth ≤ 3 in practice).
   - `Brand(name, slug unique, logo, description, is_active)`
   - `Tag(name, slug unique)` / `Collection(name, slug, description, image, is_active, products M2M)` — collections power "New arrivals", "Best sellers" as *manual or rule-based*: add `rule` CharField choices (`manual`, `new_arrivals`, `best_sellers`, `trending`) — rule-based ones are computed by a nightly Celery task into the M2M.
   - `Product(name, slug unique, brand FK null, categories M2M, tags M2M, description rich-text/HTML, short_description, status choices[draft/active/archived], is_featured, ingredients TEXT, directions TEXT, warnings TEXT, specs JSONField list of {label,value}, faqs JSONField list of {q,a}, related M2M self, `available_countries` M2M(core.Country, blank) — **empty = available everywhere; the admin shows this as per-country checkboxes incl. "International (Rest of World)" (Hammed requires this toggle)**, seo_title, seo_description, published_at, legacy_source, legacy_wp_id)`
   - `ProductVariant(product FK related_name="variants", sku unique, barcode blank, name e.g. "50ml", option_values JSONField {"Size":"50ml"}, weight_grams int null, is_default bool, is_active, position)` — every product has ≥1 variant; simple products get one default variant (mirrors WooCommerce).
   - `ProductImage(product FK, image S3, alt, position, variant FK null)` / `ProductVideo(product FK, url, position)`.
2. Read API (public, country-aware via `request.country`):
   - `GET /api/v1/products/` — filters: category slug, brand slug, tag, collection, price_min/max (in the resolved currency), in_stock, search `q` (delegates to Plan-07 when available); ordering: newest, price_asc, price_desc, best_selling. **Sellability rule (one helper, `catalog.services.sellable_in(product, country)`, used by list, detail, search sync, and cart validation):** a product is visible/sellable in a country iff (a) `available_countries` is empty or contains it, AND (b) `resolve_price` returns a price for it. Missing-price = hidden is deliberate ("hide until priced", Hammed approved) — the admin gets an "unpriced for market X" checklist view so nothing is invisibly lost.
   - `GET /api/v1/products/{slug}/` — full detail incl. variants each with `price` (from `resolve_price`), stock status (from Plan-06 `available_qty > 0`), images, related products.
   - `GET /api/v1/categories/` (tree), `GET /api/v1/brands/`, `GET /api/v1/collections/{slug}/`.
3. Admin write API (staff-only, `IsAdminUser` + RBAC permission from Plan-16 spec): full CRUD on all catalog models + `POST /api/v1/admin/products/{id}/images/` multipart upload → S3, and bulk CSV import/export endpoints (`/admin/products/export.csv`, import as Celery job with row-level error report).
4. Cache: product list/detail responses cached in Redis 60s, keyed on (path, querystring, country); invalidated by a `post_save` signal bump of a namespace version key.
5. N+1 discipline: list/detail querysets use `select_related`/`prefetch_related`; add a test with `django-assert-num-queries` style assertion (≤ 8 queries for a 24-product page).

**Verification:** factories + pytest for filters, country price exclusion, N+1 budget; manual: create a product with 2 variants + images via Swagger, see it in the list API with NG and GB prices differing.

**CHECKPOINT:** show Hammed a product JSON in two countries (different currency/price).

---

## Plan-06-inventory

**Objective:** Single-inventory stock tracking with warehouses, movements, and race-safe reservations.

**Depends on:** Plan-05.

**Files:** `apps/inventory/` (models, services.py, tasks.py, tests).

**Specification:**
1. Models:
```python
class Warehouse(models.Model):
    name = models.CharField(max_length=100)
    location_country = models.CharField(max_length=2)                 # where it physically is (ISO code)
    serves_countries = models.ManyToManyField("core.Country", related_name="warehouses")
    priority = models.PositiveSmallIntegerField(default=100)          # lower = tried first when reserving
    is_active = models.BooleanField(default=True)
# SEED (Hammed confirmed stock physically sits in BOTH today):
#   "Lagos HQ"     location NG, serves [NG, ZZ], priority: NG=1st, ZZ=2nd (backup)
#   "UK Warehouse" location GB, serves [GB, US, CA, ZZ], priority 1st for those
# Adding a future country/warehouse = admin data entry, zero code.

class StockItem(models.Model):
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="stock_items")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)          # on-hand
    reserved = models.IntegerField(default=0)          # held by pending checkouts
    low_stock_threshold = models.IntegerField(default=5)
    class Meta:
        unique_together = [("variant", "warehouse")]
    @property
    def available(self): return self.quantity - self.reserved

class StockMovement(models.Model):                      # append-only audit trail
    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    delta_quantity = models.IntegerField(default=0)     # change to on-hand
    delta_reserved = models.IntegerField(default=0)     # change to reserved
    reason = models.CharField(max_length=30, choices=[...])  # sale, reservation, release, restock, adjustment, damaged, returned, migration
    reference = models.CharField(max_length=64, blank=True)  # order number etc.
    note = models.TextField(blank=True)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)
```
2. **Services (`apps/inventory/services.py`) — the ONLY code allowed to change stock numbers; everything goes through these inside `transaction.atomic()` with `select_for_update()`:**
```python
def available_for_country(variant, country) -> int:
    """SUM(quantity - reserved) across active warehouses whose serves_countries
    includes `country`. THE number the storefront shows as in-stock."""

def reserve(variant, qty, country, reference) -> None:
    """Lock (select_for_update) the StockItem rows of warehouses serving `country`,
    ordered by warehouse.priority. Raise InsufficientStock if their combined
    available < qty. Otherwise increment `reserved` walking warehouses in priority
    order (a line MAY split across warehouses, e.g. 3 from UK + 2 from Lagos),
    writing one StockMovement(reason='reservation', reference) per warehouse touched."""

def release(reference) -> None:
    """Replay the reservation movements recorded under `reference` and decrement
    `reserved` in the same warehouses by the same amounts (movement reason='release')."""

def commit_sale(reference) -> None:
    """Replay reservation movements under `reference`: reserved -= qty AND
    quantity -= qty per warehouse (reason='sale'). The warehouses that fulfil the
    order are therefore exactly the ones that reserved it — record them on the
    OrderItem (fulfillment_warehouses JSON) for the packing team."""

def adjust(stock_item, new_quantity, reason, note, user) -> None: ...
```
   Concurrency test REQUIRED: two threads reserving the last unit — exactly one succeeds (use `pytest-django` with transactional test + threads, or simulate with sequential `select_for_update` assertions).
3. Low-stock alerts: Celery beat hourly task emails admin a digest of `available <= low_stock_threshold`.
4. Admin API: stock list (with filters), adjust endpoint (requires reason+note), movement history per variant, CSV import/export of stock counts.

**Verification:** concurrency test green; adjust via API produces a movement row; low-stock email fires with a seeded item.

**CHECKPOINT:** brief — test output + a movement-history JSON.

---

## Plan-07-search

**Objective:** Fast, typo-tolerant product search with facets behind a stable API.

**Depends on:** Plan-05. Parallel-safe with Plan-06.

**Files:** `apps/searchsync/` (client.py, tasks.py, management/commands/reindex_search.py, tests).

**Specification:**
1. One Meilisearch index `products`: documents = `{id, name, slug, brand, categories[], tags[], description_stripped, sku_list[], price_ngn, price_gbp, price_usd, price_cad, in_stock, is_active, rating_avg, sold_count}`. Searchable: name, brand, categories, tags, sku_list, description. Filterable: brand, categories, in_stock, price_*. Sortable: price_*, sold_count, rating_avg. Synonyms seeded (e.g. "moisturiser"↔"moisturizer"); ranking rules default.
2. Sync: `post_save`/`post_delete` signals enqueue Celery `upsert_product(id)` / `delete_product(id)`; full `reindex_search` management command. Index only `status=active` products.
3. API: `GET /api/v1/search/?q=&category=&brand=&price_min=&price_max=&in_stock=&sort=&page=` → same product-card shape as the products list (id, name, slug, brand, primary image, resolved price for `request.country`, in_stock). Autocomplete: `GET /api/v1/search/suggest/?q=` → top 6 names+slugs, < 50 ms served straight from Meilisearch.
4. Fallback contract: if `MEILISEARCH_URL` unset, the same endpoints run Postgres `SearchVector(name, description) + TrigramSimilarity` — identical response shape (this is the RAM-pressure escape hatch from Decision 8).

**Verification:** index a misspelled query ("moistriser") returns moisturizer products; facet filter + price filter combine; suggest endpoint p95 < 100 ms measured with a quick loop.

**CHECKPOINT:** demo a typo search to Hammed.

---

## Plan-08-cart-checkout

> **[2026-07-15] SPLIT into four sub-plans** (executed in this order; 08a/08b/08c are mutually independent, 08d integrates): **08a-carts** ∥ **08b-delivery** ∥ **08c-coupons-totals** → **08d-checkout**. Full TDD plans in `docs/superpowers/plans/2026-07-15-plan-08{a,b,c,d}-*.md`. This split follows the 05a/b/c and 06/06b precedent. Shaped by a Fable 5 consult (2026-07-15) on the checkout/reservation-expiry orchestration.
>
> **[2026-07-15] BOUNDARY CHANGE — models filed forward (Hammed approved).** The `Order`/`OrderItem` (Plan-10) and `Payment`/`CountryPaymentGateway` (Plan-09) **models** are created in **08d**, verbatim from their specs, because checkout must write them. Plan-09/10 then add only *new* tables (`Refund`, `WebhookEvent`, `OrderEvent`) and behavior — the money tables stay append-only (no restructuring migrations on the custom-User-linked money models). 08d also ships **bank_transfer** as the first working gateway (no external HTTP — real end-to-end checkout at the 08 checkpoint) and adds one field the original spec lacks: `Order.reservation_reference` (attempt-suffixed reservation ledger key, e.g. `TC-100042/2`), which fixes a real latent bug — `inventory.reserve()` is reference-idempotent, so re-reserving after an expiry-release under the same reference would silently reserve nothing.
>
> **Deviations (Fable-approved, documented in the sub-plans + docs/architecture.md):** `options_for_address(address, lines, subtotal)` (decoupled from the Cart model); `compute_totals(items, country, delivery_amount, coupon)` (decoupled from apps.delivery); `CouponRedemption.order_number` soft-ref (decoupled from apps.orders); optional `expected_total` checkout guard (409 `cart_changed`); `applies_to` coupon as an eligibility gate (MVP).

**Objective:** Carts (guest + authed), shipping zones/rates, coupons, tax, and a checkout orchestration endpoint that produces a pending order with reserved stock.

**Depends on:** Plan-04, 05, 06.

**Files:** `apps/carts/`, `apps/checkout/` (models: ShippingZone, ShippingMethod, ShippingRate, Coupon, CouponRedemption; services: totals.py, checkout.py; tests).

**Specification:**
1. **Cart:** `Cart(id UUID pk, user FK null, country FK, currency FK, status[active/converted/abandoned], expires_at)`, `CartItem(cart FK, variant FK, qty, unit_price_snapshot, added_at)`. Guest carts identified by the UUID stored in a httpOnly cookie by the storefront BFF. On login, merge guest cart into user cart (sum quantities, cap at available stock). Endpoints: `GET/POST /api/v1/cart/`, `POST /api/v1/cart/items/`, `PATCH/DELETE /api/v1/cart/items/{id}/`. Every response returns the fully-priced cart (lines re-resolved via `resolve_price` — snapshots are for display drift detection, not charging).
2. **Delivery system (region-based, mixed granularity — replaces classic zone tables; Decision 13):**
```python
class DeliveryOption(models.Model):
    name = models.CharField(max_length=100)            # "Lagos Island Same-Day", "GIG Nationwide", "DHL Express Intl"
    kind = models.CharField(max_length=10, choices=[("manual","Manual"),("carrier","Carrier API")], default="manual")
    carrier_code = models.CharField(max_length=20, blank=True)     # "dhl", "gig" — used by Plan-32; blank for manual
    price = models.DecimalField(max_digits=12, decimal_places=2)   # flat price (the common case Hammed described)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    free_over = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField(); max_days = models.PositiveSmallIntegerField()
    countries = models.ManyToManyField("core.Country", blank=True)   # whole-country coverage (incl. the ZZ Rest-of-World row)
    regions = models.ManyToManyField("core.Region", blank=True)      # state- OR LGA/city-level coverage, any mix
    is_active = models.BooleanField(default=True); sort = models.PositiveSmallIntegerField(default=0)

class DeliveryOptionRate(models.Model):               # OPTIONAL weight tiers; if none exist, flat `price` applies
    option = models.ForeignKey(DeliveryOption, on_delete=models.CASCADE, related_name="rates")
    min_weight_g = models.IntegerField(default=0); max_weight_g = models.IntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
```
   **Matching (in `checkout/services/delivery.py::options_for_address(address, cart)`):** an option matches when the address's shopping country is in `countries`, OR any of `regions` equals the address's `area_region`, its `state_region`, or any ancestor of them ("Lagos State" coverage automatically matches every Lagos LGA — that's Hammed's zone-style setup; picking 3 individual LGAs is the detailed setup; both coexist). Result sorted by `sort`, each with computed price (weight tier if rates exist, `free_over` applied) and ETA range. Seed data: current live NG rates + intl-store international rates (Plan-00 items 10–11) recreated as DeliveryOptions; Region fixture `apps/core/fixtures/ng_regions.json` = 36 states + FCT + 774 LGAs (bundle a public dataset; verify count in the seed test).
   Public region browse for address forms: `GET /api/v1/meta/regions/?country=NG` (states) and `?parent=<id>` (its LGAs), plus `Country.area_label` in `/meta/countries/`.
3. **Coupons:** `Coupon(code unique CI, type[percent/fixed/free_shipping], value, currency null, min_subtotal, starts_at, ends_at, usage_limit, usage_limit_per_user, applies_to categories/products M2M optional, is_active, legacy_source)` + `CouponRedemption(coupon, user null, email, order FK)`. Validation service returns discount amount or a specific error code (expired, min-not-met, exhausted, not-valid-for-items).
4. **Totals service (single source of truth, used by cart display, checkout, and order creation):**
   `compute_totals(items, country, delivery_option=None, address=None, coupon=None) -> Totals(subtotal, discount, delivery, tax, grand_total, currency)`. Tax: if `prices_include_tax` → tax is extracted portion (`subtotal - subtotal/(1+r)`), else added. Round half-up at 2dp per line then sum; test the rounding.
5. **Checkout orchestration — AUTHENTICATED ONLY (Decision 7; anonymous carts exist, anonymous orders do not):**
   - `GET /api/v1/checkout/delivery-options/?address_id=` → `options_for_address` result for one of the user's saved addresses (this endpoint is what makes "options appear after choosing an address" work).
   - `POST /api/v1/checkout/` (Idempotency-Key required, `IsAuthenticated`) with `{cart_id, address_id, billing_address_id?, delivery_option_id, coupon_code?, payment_gateway, notes?}` →
   inside one transaction: validate everything (address belongs to user; delivery option matches the address — server-side re-check, never trust the client's option list; `sellable_in` per line; gateway active for the country) → `inventory.reserve(variant, qty, order.country, reference=order.number)` each line → create `Order(status="pending_payment", user=request.user)` + snapshot items/address JSON/totals → create `Payment(status="initiated")` via the gateway (Plan-09) → return `{order_number, payment: {gateway, action: redirect_url | client_secret | reference}}`.
   - **Buy Now:** `POST /api/v1/checkout/buy-now/ {variant_id, qty}` → creates/replaces the user's single "express cart" (a `Cart` with `kind="express"` — add that field, default `"standard"`; one express cart per user, upserted) and returns it. The storefront then runs the normal checkout against the express cart, leaving the standard cart untouched.
   Reservation TTL: `Order.reservation_expires_at = now + 30 min`; Celery beat task `expire_pending_orders` every 5 min: past-due pending orders → status `expired`, `inventory.release(reference=order.number)`.
6. Abandoned carts: carts untouched 3h → status `abandoned` (beat task). (Recovery *emails* are Plan-30; flagging is now so data accrues.)

**Verification:** pytest: totals rounding, coupon branches, guest-cart merge, checkout happy path creates order+reservation, expiry task releases stock, idempotent replay returns identical body without double-reserving.

**CHECKPOINT:** walk Hammed through a Swagger checkout that reserves stock and expires correctly (demo with 1-unit stock item).

---

## Plan-09-payments

**Objective:** Four gateways behind one interface, bulletproof webhooks (idempotent, signature-verified), refunds.

> **[2026-07-15] Note:** the `Payment` model, `CountryPaymentGateway` (+ seed), the `PaymentGateway` ABC, the gateway registry, and a minimal `mark_paid` **already exist** (built in Plan-08d, with `bank_transfer` as the proven first gateway). Plan-09 ADDS: the four networked gateways behind the existing ABC; `Refund` + `WebhookEvent` models; webhook views; `verify()` + the amount/currency equality check wrapping the existing `mark_paid`; refunds; and the late-payment-after-expiry re-reserve path (bump `Order.reservation_reference` to the next attempt suffix, then reserve+commit). Do NOT re-create `Payment`/`CountryPaymentGateway`.

**Depends on:** Plan-08. **Needs from Hammed:** test-mode API keys for Paystack, Flutterwave, Stripe, PayPal.

**Files:** `apps/payments/` (models.py, gateways/base.py, gateways/paystack.py, gateways/flutterwave.py, gateways/stripe.py, gateways/paypal.py, views_webhooks.py, services.py, tests/).

**Specification:**
1. Models:
```python
class Payment(models.Model):
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    gateway = models.CharField(max_length=20)                     # paystack|flutterwave|stripe|paypal|bank_transfer
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="initiated") # initiated|pending|succeeded|failed|cancelled|refunded|partially_refunded
    gateway_reference = models.CharField(max_length=128, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    raw_response = models.JSONField(default=dict)

class Refund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending")   # pending|succeeded|failed
    gateway_reference = models.CharField(max_length=128, blank=True)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)

class WebhookEvent(models.Model):                                  # idempotency ledger
    gateway = models.CharField(max_length=20)
    event_id = models.CharField(max_length=128)                    # gateway's event id
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True)
    error = models.TextField(blank=True)
    class Meta:
        unique_together = [("gateway", "event_id")]                # duplicate delivery = ignored
```
2. Gateway interface:
```python
class PaymentGateway(ABC):
    code: str
    supported_currencies: set[str]
    def initiate(self, payment, order, return_url) -> InitiateResult: ...   # redirect_url or client_secret or bank details
    def verify(self, payment) -> PaymentStatus: ...                         # server-side re-verification, ALWAYS called before fulfilling
    def refund(self, payment, amount, reason) -> RefundResult: ...
    def parse_webhook(self, request) -> ParsedEvent: ...                    # MUST verify signature (Paystack x-paystack-signature HMAC-SHA512; Flutterwave verif-hash; Stripe-Signature; PayPal cert verification) and raise InvalidSignature otherwise
```
   Gateway availability by country is **admin-managed data, not config** (Hammed requires toggling gateways per country from the backend):
```python
class CountryPaymentGateway(models.Model):            # in apps/payments
    country = models.ForeignKey("core.Country", on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20)         # paystack|flutterwave|stripe|paypal|bank_transfer
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    class Meta:
        unique_together = [("country", "gateway")]
```
   Seed: NG → [paystack, flutterwave, bank_transfer]; GB/US/CA/ZZ → [stripe, paypal]. `GET /api/v1/checkout/payment-methods/?country=` reads it (active rows, sort order); checkout validates the chosen gateway is active for the order's country. Admin CRUD screen ships in Plan-19.
3. Webhook endpoints `POST /api/v1/webhooks/{gateway}/` (CSRF-exempt, throttled, no auth — signature IS the auth):
   flow = verify signature → upsert `WebhookEvent` (unique violation ⇒ return 200 immediately) → enqueue Celery `process_webhook_event(id)` → return 200 fast. Processing: match payment by `gateway_reference` → call `gateway.verify()` (never trust the webhook body alone for money) → on success: `payments.services.mark_paid(payment)` which (atomically) sets Payment succeeded, Order → `processing`, `inventory.commit_sale(reference=order.number)` (commits exactly the warehouses that reserved), `CouponRedemption` write, enqueue confirmation email. **Amount+currency from verify() must equal the order total — mismatch ⇒ flag order `needs_review`, do not fulfil.**
4. Edge cases (each gets a test): duplicate webhook (unique constraint path), payment succeeds AFTER reservation expired (re-reserve if stock allows, else mark `needs_review` + alert admin), payment for cancelled order (auto-initiate refund flag + alert), partial refund math, gateway 5xx on initiate (return 502 with clean error, order stays pending, retry allowed with same Idempotency-Key).
5. Refund API (staff): `POST /api/v1/admin/orders/{n}/refunds/` (amount ≤ remaining), calls `gateway.refund`, restocks optionally (`restock: true` → `inventory.adjust` reason `returned`).
6. All gateway HTTP calls: 15s timeout, retried ×2 with backoff on connection errors ONLY (never retry ambiguous 5xx on money-moving calls without idempotency parameters supported by that gateway — Paystack/Stripe support them; use them).

**Verification:** unit tests with mocked gateway HTTP (respx/responses); then REAL test-mode e2e for each gateway: Paystack test card, Flutterwave test card, Stripe 4242…, PayPal sandbox — from checkout through webhook (use `stripe listen`/gateway dashboard webhook test or a tunnel) to order `processing` and stock committed.

**CHECKPOINT:** show Hammed one full test-mode payment per gateway with the order flipping to processing. This is the riskiest stage — do not rush it.

> **[2026-07-16] This checkpoint is DEFERRED, not cancelled.** The test-mode keys never
> arrived and this checkpoint was blocking every downstream stage. Resolution: the four
> networked gateways are **deactivated** (Plan-09b) and launch runs on bank transfer only.
> The code stays in the tree, untouched and uncertified. **No gateway is reactivated for
> any country until its test-mode payment is driven end-to-end and shown to Hammed** —
> that is still this checkpoint, just moved behind launch. Deactivation is what makes
> deferring it safe: uncertified code that cannot be reached takes no money.

---

## Plan-09b-manual-payments

**Objective:** Make bank transfer a complete, confirmable payment method in every market — because it is now the **only** one. Deactivate the four networked gateways.

> **[2026-07-16] Why this stage exists.** Decision #3 (§4) flipped launch to bank-transfer-only.
> That promotes a fringe NG option to the single path every order takes, and it exposes that
> `bank_transfer` is a **dead end**: `initiate()` shows bank details, then nothing in the
> codebase can ever mark the order paid. `mark_paid()` is reachable only via
> `confirm_payment()`, which calls `gateway.verify()`, which `bank_transfer` answers with
> `ManualVerificationOnly`. Meanwhile the expiry sweep releases the order after 30 minutes.
> **Ship the gateway switch-off without this stage and 100% of orders expire 30 minutes
> after the customer's money leaves their account, with nothing in the system recording it.**
> This is the launch blocker. Plan-18 keeps only the admin *UI*; the service layer is here.

**Depends on:** Plan-09 (gateway ABC, `confirm_payment` ladder), Plan-10 (`transition()`, `OrderEvent`, emails). **Needs from Hammed:** real bank account details per market (NG/NGN, GB/GBP, US/USD, CA/CAD; ZZ routes to the USD account).

**Files:** `apps/payments/` (models.py, gateways/base.py, gateways/bank_transfer.py, services.py, admin_urls.py, views.py, checks.py, migrations/, tests/), `apps/checkout/services/checkout.py`, `apps/checkout/tasks.py`.

**Specification:**

1. **Per-country bank accounts.** The three global `SiteSetting` rows (`bank_transfer.bank_name` etc.) are one account for the whole world — replace with data:
```python
class BankAccount(models.Model):                       # in apps/payments
    country = models.OneToOneField("core.Country", on_delete=models.PROTECT, related_name="bank_account")
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)   # MUST equal country.currency (validated)
    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=64)   # or IBAN
    extra = models.JSONField(default=dict)             # sort_code / routing_number / SWIFT / IBAN — per-market shape
    instructions = models.TextField(blank=True)        # market-specific wording appended to the standard line
    is_active = models.BooleanField(default=True)
```
   Keyed by **country, not currency**: US and ZZ both settle in USD but a Rest-of-World customer may need SWIFT/intermediary details a domestic US customer does not, and "which account do I show this customer" is a country question. Two rows may legitimately carry the same real account number — that is not a bug, don't dedupe it.

2. **`initiate()` must never render blanks.** Today `SiteSetting.get_typed("bank_transfer.account_number", "")` defaults to `""` — an unconfigured market shows the customer a payment page with an **empty account number**. Look up `BankAccount` for `order.country`; if missing or inactive, raise `GatewayNotConfigured` (→503). Losing the sale is recoverable; a customer wiring money into a blank is not.

3. **Checkout refuses a manual gateway with no account, BEFORE reserving stock.** Drop the hardcoded `supported_currencies = {"NGN"}` — but note **nothing in the codebase reads `supported_currencies`** (not `active_gateways_for`, which reads only `CountryPaymentGateway`; not the payment-methods view; not checkout's line-99 validation), so do **not** replace it with a derived property believing it gates anything. The real gate goes in `place_order` phase 1, beside line 99: if the chosen gateway's `confirmation == "manual"`, require an active `BankAccount` for the country. Gating at `initiate()` alone is too late — phase 1 has already committed the order, reserved stock **for 24h**, and converted the cart, so each retry burns another day-long hold on stock nobody can buy.

4. **Per-gateway reservation TTL.** `PaymentGateway.reservation_ttl_minutes = 30` (class default); `BankTransferGateway.reservation_ttl_minutes = 1440` (24h — NG transfers are NIP-instant; the real delay is staff working hours). `checkout.py:133` stamps `reservation_expires_at` from `get_gateway(payment_gateway).reservation_ttl_minutes` instead of the global `RESERVATION_TTL_MINUTES`. **No new machinery is needed:** the gateway is already chosen at checkout (validated line 99, `Payment` created line 145) in the *same transaction* that stamps the TTL. `RESERVATION_TTL_MINUTES` stays as the class default's source.

5. **`PaymentGateway.confirmation: "gateway" | "manual"`** class attribute (`bank_transfer` → `"manual"`). This replaces inferring manual-ness from `InitiateResult.action == "bank_details"`, which conflates three unrelated questions (needs-instructions-email? / `verify()`-able? / which TTL?) and breaks the moment a Paystack dedicated account arrives — not instant, but machine-confirmable.

6. **`confirm_manual_receipt()`** — the service that makes the money visible. Skips `verify()` entirely (there is no machine to ask; the staff member reading the bank statement **is** the verification).
```python
def confirm_manual_receipt(payment, *, staff_user, amount_received: Decimal,
                           bank_reference: str, note: str = "",
                           accept_shortfall: bool = False) -> None: ...
```
   Amount handling is a **three-way** decision, not `_amounts_match`'s exact equality — and **any nonzero delta requires an explicit `accept_discrepancy=True` plus a reason**:
   - `received == expected` → fulfil.
   - `received > expected`, accepted → **fulfil AND flag review** ("overpaid by X — refund the difference"). They paid enough; holding their goods hostage over a surplus is the wrong failure. The flag is what gets the surplus refunded.
   - `received < expected`, accepted → fulfil AND flag, recording **who** accepted it (the intl-wire case: intermediary banks eat a slice, so the amount *arriving* is legitimately less than the amount *sent*).
   - **any delta, not accepted → raise, fulfil nothing, leave no flag.** The common cause is a staff typo, and the expensive direction is overpayment: `50000` for `5000` would otherwise fulfil *and* plant a flag authorising a human to wire ₦45,000 out — with refunds manual (item 12) that flag **is** the authorisation; no gateway ledger will refuse it. The 400 carries `expected`/`received`, so Plan-18's "are you sure?" falls out for free. A mandatory free-text reason is the anti-"staff always tick the box" control: friction exactly where friction belongs, and it lands in the audit event.
   Then it reuses the **same** verdict ladder as `confirm_payment` — extract that ladder into `_react_to_verdict(payment, outcome)`, returning **whether the order actually ended up fulfilled**, and have both call it. The return value is load-bearing: a delta flag may only be written when the goods really shipped, or it overwrites the ladder's more urgent instruction (item 6b).

6b. **`_flag_review` must APPEND, not assign.** It currently assigns (`services.py:126`), which was tolerable when one writer touched an order per request. `confirm_manual_receipt` creates a second writer in the same call stack and the collision loses money: on a **cancelled** order where the customer overpaid ₦12,000 against ₦10,000, the ladder writes *"payment on a cancelled order — refund it"* (refund all ₦12,000, goods never ship) and the overpayment branch then **overwrites** it with *"refund the difference"* (₦2,000). Staff wire ₦2,000, resolve the flag, and the customer is out ₦10,000 with no goods and no trace. `resolve_review` still clears the whole string in one explicit act, so Plan-10's model is untouched.

6c. **One bank statement line must not release two orders.** `bank_reference` is free text. A customer (or fraudster) places two orders, sends one transfer, and quotes the same reference for both; two staff — or one, days apart — confirm both. Goods ship twice against money that arrived once. Auto-reconciliation stays out of scope, but a duplicate-reference check is ~5 lines and is the cheapest fraud control in the stage: refuse unless `allow_duplicate_reference=True`.

7. **Admin confirm API** `POST /api/v1/admin/orders/{number}/confirm-payment/` — staff-only, body `{amount_received, bank_reference, note, accept_shortfall}`. Writes an `OrderEvent` recording **actor, amount received, bank reference, and the shortfall/surplus decision** — an accountant must be able to reconstruct, months later, who released these goods and against which line on which bank statement. Plan-18 builds the UI over this endpoint.

8. **Deactivate the four networked gateways** (data migration): `is_active=False` for every paystack/flutterwave/stripe/paypal `CountryPaymentGateway` row; add `bank_transfer` rows for GB/US/CA/ZZ. **`is_active` gates the checkout menu and `initiate()` — never `confirm_payment()`.** Deactivation must not strand a customer who genuinely paid a gateway minutes before the deploy; confirmation of already-taken money must always still work. (No in-flight orders exist pre-launch, but the code shape is what keeps this true at reactivation.) **The reverse must be `RunPython.noop`** — a `migrate payments 0006` run for any unrelated reason (bisecting a later bad migration, a rollback during an incident) would otherwise silently flip four uncertified gateways live in production, in direct violation of the rule above. Reactivation is a human checkpoint, not schema symmetry. The migration must also depend on the **core Country seed**, or on a fresh DB every `if not country: continue` fires and bank transfer activates in **zero** markets — a site that silently takes no money anywhere.

9. **Customer "check my payment" branches on `confirmation`.** For a manual gateway, return the order's current status without calling `verify()`. `ManualVerificationOnly` stays as belt-and-braces for anything that slips through.

10. **Expired-manual-order email** when a manual-gateway order hits expiry — the customer who wired money 25 hours ago must not learn from silence. Fires from the expiry sweep via `transaction.on_commit`, like every other order email. **While in that loop, give it the poison isolation its docstring already promises:** decide manual-ness from a code set derived once from the registry, not a `get_gateway()` call per order. `get_gateway()` raises `UnknownGateway` on a migrated legacy gateway code (879 old NG orders arrive in Plan-21/23) — that order never expires, the exception kills the task run, and **every due order behind it starves, every 5 minutes, forever**. Wrap each iteration in try/except-log regardless: Plan-09b adds the first code path in that loop that can raise at all.

11. **`payments.W001` gains a bank-transfer arm (`payments.W002`):** warn at deploy when a country has `bank_transfer` active but no active `BankAccount`. Same failure this stage exists to kill, caught before a customer meets it.

12. **Manual refunds — the second dead end, and a launch blocker in its own right.** `BankTransferGateway` never implements `refund()`, so it inherits `base.py:113`'s bare `raise NotImplementedError`. `refunds.py:95` calls the gateway inside `except GatewayError` — and `NotImplementedError` is a `RuntimeError`, so it **escapes**: the staff request 500s **and the `pending` Refund row from phase 1 is never resolved**. `refundable_amount` counts pending rows, so that amount is reserved forever and every later refund on that payment fails `amount_exceeds_remaining` — one 500 poisons the payment permanently. Harmless when bank_transfer was a fringe NG option; fatal now that **every refund in every market takes this path** — and this stage's own ladder and overpayment flags all say "refund it", instructing staff to do something the system cannot do. Add `ManualRefundOnly(GatewayError)` (mirroring `ManualVerificationOnly`, so a mis-routed `create_refund` fails clean and *releases* the reserved row instead of stranding it) plus `record_manual_refund(payment, *, amount, staff_user, bank_reference, note, restock)`: staff wire the money from the bank app, then record it. The `Refund` row is born `succeeded` — there is no pending phase, because the transfer has already been sent by the time anyone records it — and `apply_succeeded_refund` (already documented as the entry point for a refund that completed out of band) does the ledger roll-up, lifecycle, restock and email unchanged.

13. **The `order_received` email must carry every per-market field.** `apps/notifications/templates/email/order_received.txt`/`.html` hardcode exactly `bank_name` / `account_name` / `account_number`. `enqueue_order_received` spreads `init.data` into the context, so the per-market fields item 1 adds (`sort_code`, `routing_number`, IBAN/SWIFT) **arrive and are silently dropped**. A UK domestic transfer is impossible without a sort code, and this email is the customer's only durable copy of the details — **so as written, GB and US cannot pay at all**, silently, and the order dies 24h later. Pass the account as one ordered, display-ready `bank_details` dict and have the templates iterate it, so a new market needs no template change. The email must also state the **24h deadline** — nothing anywhere tells the customer their reservation expires, which is the single fact most likely to make them transfer today rather than Saturday.

**Explicitly NOT in scope (YAGNI — the exit is Paystack dedicated accounts, so the manual flow must not grow features that assume it is permanent):** installment/partial-payment ledgers; automated bank-statement reconciliation or CSV import; per-country TTL tuning; a `BankAccount` CRUD screen (Django admin covers launch; Plan-18 owns admin UI); matching transfers to orders by anything but a human reading the reference.

**Follow-ups this stage creates but must NOT build (record them, don't scope-creep):** a 24h TTL on the *only* method means **every "place order" click holds stock for a day**, including customers who only wanted to see the account number and walked. With thin NG stock, three abandoned checkouts can sell out a variant for 24h against real buyers. So — **Plan-14** must expose customer-visible cancel on a pending order (`orders.services.cancel_order` already exists; the storefront just has to surface it) and re-show the bank details on the order page (today they live only in the checkout response and the email); **Plan-20**'s low-stock digest must distinguish reserved from sold, or staff will chase phantom sell-outs all day.

**Accounting caveat to write into architecture.md:** on an accepted discrepancy, `payment.amount` stays the order total while the real cash received lives in `raw_response.manual_receipt`. Refunding a surplus through the ledger therefore reads as a *partial refund of the order price*. Acceptable at launch — but **`payment.amount` is not cash-in**, and Plan-20/28 reporting must not treat it as such.

**Verification:** unit tests per branch, and a driven end-to-end: place an order in each market → assert the *correct* market's bank details render, **including the GB sort code in the email** → an unconfigured market is refused at checkout **before** an order exists or stock is reserved → confirm receipt via the admin API → order `processing`, stock committed, `OrderEvent` carries the actor + bank reference. Plus: an unexpected amount 400s with expected/received and changes nothing; an accepted overpayment fulfils+flags; a reused bank reference 409s; a manual refund lands; a 24h expiry emails the customer; two staff confirming the same order concurrently does not fire a false double-payment flag; and one unknown legacy gateway code does not starve the expiry sweep. **Render every email and read it** — a green suite hid two Plan-10 bugs that only rendered output caught.

**CHECKPOINT:** show Hammed a bank-transfer order in each market going from placed → bank details → admin confirm → processing, the GB email with its sort code, a manual refund, and the audit trail on the resulting order.

---

## Plan-10-orders

**Objective:** Order lifecycle, customer/admin order APIs, transactional emails, PDF invoices, tracking.

> **[2026-07-15] Note:** the `Order` + `OrderItem` models (full field list below) **already exist** (built in Plan-08d). Plan-10 ADDS: `OrderEvent` + the `state.py` state machine (08d sets `order.status` directly in exactly two places — `place_order` and `expire_pending_orders` — refactor both through `transition()`), customer/admin order APIs, transactional emails, PDF invoices, and tracking. Do NOT re-create `Order`/`OrderItem`.

**Depends on:** Plan-09.

**Files:** `apps/orders/` (models, state.py, serializers, views, invoice.py, tests), `apps/notifications/templates/email/*`.

**Specification:**
1. Models:
```python
class Order(models.Model):
    number = models.CharField(max_length=20, unique=True)         # TC-100001 (DB sequence), or legacy number
    user = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="orders")
    # user is null ONLY for migrated legacy guest orders and deleted accounts — every NEW order requires an account (Decision 7)
    email = models.EmailField()                                    # snapshot; kept even if the account is later deleted
    phone = models.CharField(max_length=32, blank=True)
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=24, default="pending_payment")
    # pending_payment → processing → shipped → delivered → completed
    # + cancelled, expired, refunded, on_hold(migrated)
    # [2026-07-16 CORRECTION — needs_review and partially_refunded were listed here and
    # are NOT statuses. Both were category errors, fixed while plan-09 was unmerged:
    #   needs_review       → orthogonal; Order.review_reason carries it, so flagging never
    #                        overwrites what actually happened.
    #   partially_refunded → a payment-ledger fact; a shipped order can be partially
    #                        refunded and still needs delivering (this one was a live bug).
    # `cancelled` also means "no money was ever captured" — paid orders exit via
    # `refunded`. See orders/state.py and docs/architecture.md § Order lifecycle.]
    subtotal/discount_total/shipping_total/tax_total/grand_total = DecimalField(12,2)
    coupon = models.ForeignKey("checkout.Coupon", null=True, on_delete=models.SET_NULL)
    delivery_option_name = models.CharField(max_length=100, blank=True)   # snapshot ("Lagos Island Same-Day")
    shipping_address = models.JSONField()                                  # snapshot, not FK
    billing_address = models.JSONField()
    customer_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    tracking_carrier = models.CharField(max_length=50, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    reservation_expires_at = models.DateTimeField(null=True)
    source = models.CharField(max_length=20, default="web")        # web|legacy_ng|legacy_intl|admin
    legacy_number = models.CharField(max_length=20, blank=True, db_index=True)
    placed_at = models.DateTimeField(default=timezone.now)

class OrderItem(models.Model):
    order = FK related_name="items"; variant = FK null SET_NULL     # product may be deleted later — snapshots survive
    product_name/variant_name/sku = CharField snapshots
    unit_price/line_total = DecimalField(12,2); quantity = int
    image_url = models.URLField(blank=True)
    fulfillment_warehouses = JSONField(default=dict)    # {"UK Warehouse": 3, "Lagos HQ": 2} — written by inventory.commit_sale, read by the packing team in admin

class OrderEvent(models.Model):                                     # timeline/audit
    order FK related_name="events"; type CharField; message Text; actor FK User null; created_at
```
2. **State machine in `state.py`:** explicit `ALLOWED_TRANSITIONS` dict; a single `transition(order, to_status, actor, message)` function writes the `OrderEvent`, fires side-effects (emails, stock commit already handled by payments), rejects illegal jumps. No view ever sets `order.status` directly.
3. Customer APIs: `GET /api/v1/orders/` (own), `GET /api/v1/orders/{number}/` (own or guest via signed token emailed in confirmation), `GET /api/v1/orders/{number}/invoice.pdf`.
4. Admin APIs: list w/ filters (status, date range, country, gateway, search by number/email/name), detail, transition endpoint, tracking update (sends "shipped" email), admin-note, manual order creation (phone orders).
5. Emails (all Celery, all via `send_email`): order confirmation (with items table + guest tracking link), payment received, shipped (with tracking), delivered, refund processed. Plain, brand-styled HTML + text alternative.
6. Invoice PDF: WeasyPrint in the worker container (add system deps to Dockerfile); simple branded template; stored to S3 private prefix; served via short-lived signed URL.

**Verification:** state-machine tests (legal + illegal transitions), guest tracking link auth test, invoice renders (open the PDF), each email template renders with a factory order and sends via Resend (test/console backend in CI).

**CHECKPOINT:** show Hammed a confirmation email + invoice PDF for a test order.

---

## Plan-11-accounts

**Objective:** Everything a logged-in customer can do, API-side: profile, addresses, wishlist, reviews.

**Depends on:** Plan-10. Parallel-safe with Plan-12.

**Files:** `apps/accounts/` (extend), `apps/wishlist/`, `apps/reviews/`.

**Specification:**
1. Addresses CRUD `/api/v1/me/addresses/` (+ set-default endpoints) — the STRUCTURED address model from Plan-03: serializer enforces the per-country rules (NG = state + LGA dropdowns backed by `/meta/regions/`; GB/US/CA = text + required postcode), unlimited addresses per user with labels ("Home", "Office"). Profile GET/PATCH (names, phone, marketing_consent) — response includes the read-only `toke_id`, which the storefront displays prominently in the account area. Password change (old-password required). Account deletion request endpoint (soft: `is_active=False`, anonymize email after 30d — GDPR/NDPR basic hygiene).
2. Wishlist: `GET/POST/DELETE /api/v1/me/wishlist/` (variant ids), product cards resolved per country like everything else.
3. Reviews: `POST /api/v1/products/{slug}/reviews/` — only by users with a delivered/completed order containing the product ("verified purchase"); rating 1–5 + text; status `pending` → admin approves (Plan-18); `GET` lists approved only; product `rating_avg`/`rating_count` denormalized on approval (and synced to search index).
4. Legacy guest-order claiming: new orders always have an account (Decision 7), but MIGRATED WordPress orders include guest purchases with no user. When someone registers (or already has an account) with an email matching legacy guest orders, attach those orders to their account on email verification — so old customers see their full history.
5. Newsletter capture (used by the storefront footer, Plan-12): `NewsletterSubscriber(email unique, source, consented_at, unsubscribed_at null)` + public `POST /api/v1/newsletter/` (throttled 5/min/IP) and an unsubscribe-link endpoint. Campaign *sending* is Plan-30; capture starts now so the list grows from day one.

**Verification:** pytest incl. the verified-purchase rule and guest-order attach; smoke via Swagger.

**CHECKPOINT:** compact API demo.

---
# PHASE C — STOREFRONT (storefront/ app, deployed to Vercel)

General storefront rules for Plans 12–15:
- **Server Components by default**; client components only where interactivity demands (cart drawer, forms, switchers). Data fetching on the server via a typed `lib/api.ts` client (fetch with `next: { revalidate }` tags), TanStack Query only for client-side mutations/cart.
- **BFF pattern:** Next.js Route Handlers under `app/api/` proxy auth + cart calls to Django, holding JWT/cart-id in httpOnly cookies. The browser never sees tokens. Server Components call Django directly with the cookie-derived token.
- Country context: cookie `country` (NG default). Middleware reads it; a first-visit banner suggests a country from Vercel's `x-vercel-ip-country` header ("It looks like you're in the UK — shop in GBP?") but NEVER hard-forces (user choice always wins, per requirements).
- Design: premium beauty aesthetic (Sephora/Cult Beauty class). Neutral palette (off-white/cream background, near-black text, one accent — pick from existing Toke branding in Plan-00 screenshots), generous whitespace, serif display font for headings (e.g. Playfair Display via next/font) + clean sans for body (e.g. Inter), subtle motion (Tailwind transitions; no heavy animation libs). Mobile-first. Use the `ui-ux-pro-max:design` skill when building the design system if available.
- Performance budget enforced every stage: Lighthouse (mobile) ≥ 95 on the pages that stage adds, images always via `next/image`, no client JS for content that doesn't need it.

## Plan-12-storefront-foundation

**Objective:** App shell every page uses: design system, header/footer/nav, country switcher, auth/cart BFF plumbing.

**Depends on:** Plan-03 (auth API), Plan-04 (countries API). 

**Files:** `storefront/src/app/layout.tsx`, `src/components/layout/{Header,Footer,MobileNav,CountrySwitcher,SearchBar,CartDrawer}.tsx`, `src/lib/{api.ts,auth.ts,country.ts}`, `src/app/api/auth/[...]/route.ts`, `src/app/api/cart/[...]/route.ts`, `src/middleware.ts`, Tailwind theme config.

**Specification:**
1. Typed API client `lib/api.ts`: base URL from `NEXT_PUBLIC_API_URL`, sends `X-Country` from cookie, helper `apiFetch<T>(path, opts)`; generate TS types from the OpenAPI schema (`openapi-typescript`) into `src/lib/api-types.ts` — regenerate script in package.json.
2. Auth BFF routes: `/api/auth/login|register|logout|refresh|me` → Django; access+refresh tokens in httpOnly cookies; silent refresh in a route-handler wrapper when access expires.
3. Cart BFF: cart UUID cookie management; add/update/remove proxied; `CartDrawer` client component with optimistic updates (TanStack Query).
4. Header: logo, nav (categories from API, cached/ISR 1h), search bar (wired in Plan-13), country/currency switcher (flag + currency, persists cookie, refreshes prices; options = active markets + "International (USD)" for everywhere else), account menu, cart button with count. Footer: links to policies/contact (CMS pages), newsletter email capture (stores to backend endpoint `POST /api/v1/newsletter/`), payment method logos.
5. Skeleton pages with correct routes so nav works: `/`, `/products`, `/product/[slug]`, `/category/[slug]`, `/search`, `/cart`, `/checkout`, `/account`, `/login`, `/register`, `/page/[slug]`.
6. Error/loading UX: root `error.tsx`, `not-found.tsx`, per-route `loading.tsx` skeletons.

**Verification:** `npm run build` clean; switch NG→GB and watch a (temporary) price widget change currency; login/logout round-trip works against the deployed API; Lighthouse ≥ 95 on the shell.

**CHECKPOINT:** deploy preview URL to Hammed (Vercel preview). Get design-direction sign-off HERE before building all pages.

## Plan-13-storefront-catalog-seo

**Objective:** Home, category/listing, product detail, search — with the full enterprise SEO layer. This stage carries the "100% SEO perfect" requirement.

**Depends on:** Plan-12, backend 05/07.

**Files:** `src/app/(shop)/page.tsx`, `category/[slug]/page.tsx`, `products/page.tsx`, `product/[slug]/page.tsx`, `search/page.tsx`, `src/components/product/{ProductCard,ProductGallery,VariantPicker,PriceTag,ReviewList,ReviewStars}.tsx`, `src/lib/seo.ts`, `src/app/sitemap.ts`, `src/app/robots.ts`.

**Specification:**
1. **Home:** hero banner(s), featured collections, best sellers, new arrivals, brand strip, editorial blocks — ALL content from the CMS API (Plan-19 backend models; until then, seeded fixtures). ISR `revalidate: 300`.
2. **PLP (category/listing/search):** SSR with filters (price, brand, availability, rating) as URL params (shareable/crawlable), sort options, pagination with `rel=prev/next`-style canonical handling (page param canonicalized), product cards with hover second-image, wishlist heart, price with compare-at strikethrough.
3. **PDP — Amazon-pattern buy box (Decision 14):** left = gallery w/ zoom; right = buy box card: price (+ compare-at strikethrough), star rating summary, variant picker (updates price/SKU/stock/image), **delivery estimate line** ("Delivery to <Ikeja / your area>: 1–2 days from ₦1,500" — from the user's default address via the delivery-options endpoint; generic country-level line when logged out), stock state ("Only 3 left" under threshold), qty selector, **two buttons: "Add to Cart" (secondary, opens drawer) and "Buy Now" (primary, calls the buy-now endpoint and routes straight into checkout; logged-out users get the inline-signup step first, then land back in checkout with the item intact — test this resume path)**. Below: accordion sections (description, ingredients, directions, warnings, FAQs — straight from product fields), reviews with stars + verified-purchase badge, related products carousel, recently-viewed strip (localStorage, client component). ISR per product `revalidate: 120` + on-demand revalidation webhook: Django `post_save` calls a Vercel revalidate route with a secret.
4. **SEO layer (`lib/seo.ts` used by every page):**
   - `generateMetadata` everywhere: title template `%s | Toke Cosmetics`, meta description, canonical URL (absolute, respects filters policy: filtered PLP variants canonicalize to the base category), Open Graph (og:image from product/category image), Twitter cards.
   - JSON-LD components: `Organization` (site-wide), `WebSite` + SearchAction, `BreadcrumbList` (every PLP/PDP), `Product` with `offers` (price in current currency, availability, priceValidUntil for sale windows), `AggregateRating`+`Review` when reviews exist, `FAQPage` on PDPs with FAQs.
   - `app/sitemap.ts`: index sitemap → products, categories, pages (from API, paginated); `app/robots.ts`: allow all, sitemap ref, disallow `/checkout`, `/account`, `/api`.
   - Slugs are IDENTICAL to the migrated WP slugs (guaranteed by Plan-21/24) so product URLs don't change shape beyond the domain path structure; the Plan-24 redirect middleware covers the rest.
5. Currency/i18n note: single locale (en) at launch; prices formatted with `Intl.NumberFormat` per currency. hreflang deliberately omitted (one URL set, country chosen in-session) — document this in docs/architecture.md.

**Verification:** Rich Results Test passes for Product, Breadcrumb, FAQ, Organization on real preview URLs; Lighthouse mobile ≥ 95 incl. SEO 100 on home/PLP/PDP; `curl` a PDP and confirm full HTML (SSR) with JSON-LD present; sitemap.xml valid.

**CHECKPOINT:** Hammed reviews look & feel of home/PLP/PDP on preview + sees the Rich Results screenshots.

## Plan-14-storefront-checkout

**Objective:** Cart page → address → shipping → payment → confirmation, all four gateways, guest + logged-in.

**Depends on:** Plan-12, backend 08/09/10.

**Files:** `src/app/(shop)/cart/page.tsx`, `checkout/page.tsx` (+ step components), `checkout/confirmation/[number]/page.tsx`, `src/components/checkout/*`, BFF `app/api/checkout/route.ts`.

**Specification:**
1. Cart page: line items (qty editors, remove), coupon field (inline validation with specific error messages), totals box, "estimated delivery" from shipping preview, trust badges. Free-shipping progress bar if a `free_over` rate exists for the country.
2. Checkout = the Amazon sequence (Decision 14), stacked collapsible steps (mobile-first), completed steps collapse to a one-line summary with "Change":
   (1) **Sign in / inline signup** — logged-in users skip it entirely; new customers see email + first name + password (that's all — account created silently, no detour); existing-email detection flips to a password field.
   (2) **Delivery address** — address book as selectable cards + "Add new address" (the per-country structured form: NG shows State → LGA dropdowns labeled with `area_label`; country locked to the shopping country with a "changing country restarts pricing" notice).
   (3) **Delivery options** — fetched for the CHOSEN address (`/checkout/delivery-options/?address_id=`), radio cards with name, price, ETA range ("Lagos Island Same-Day — ₦2,000 — today/tomorrow"). This step re-renders whenever the address changes.
   (4) **Payment method** — options from `/payment-methods/` for the country.
   (5) **Review & Place Order** — full order summary (items, address, delivery, totals incl. tax line) with a single "Place order" button; nothing is charged before this click. Order notes optional. Totals sidebar always visible/sticky on desktop, collapsible on mobile.
3. Payment step per gateway: Paystack → inline popup (paystack-js) or redirect; Flutterwave → inline/redirect; Stripe → Payment Element (supports Apple Pay/Google Pay automatically); PayPal → JS SDK buttons; bank transfer → account details screen + "I've paid" → order pending confirmation. After gateway completion: poll `GET /api/v1/orders/{number}/status/` (or gateway return URL) until webhook flips status → route to confirmation.
4. Confirmation page: order number, items, totals, delivery estimate, "create an account" prompt for guests (prefilled email), tracking link explanation.
5. Failure UX: payment failed/cancelled → order page with retry button (new payment on same order while reservation valid); reservation expired → clear message + cart restored.

**Verification:** end-to-end on the preview URL with ALL FOUR gateways in test mode (this duplicates Plan-09 verification but through the real UI); NEW-customer (inline signup mid-checkout) AND returning-customer checkout; Buy Now from a PDP while logged out (signup → resume with item intact); a Lagos address showing LGA-specific options vs a UK address showing UK options; mobile viewport walkthrough; Lighthouse on cart/checkout ≥ 90 (checkout has 3rd-party JS — budget accordingly, load gateway SDKs lazily only when selected).

**CHECKPOINT:** Hammed does a test purchase himself on his phone.

## Plan-15-storefront-account

**Objective:** Customer dashboard: orders, order detail + tracking, addresses, profile, wishlist, reviews, password.

**Depends on:** Plan-12, backend Plan-11.

**Files:** `src/app/account/{layout,page,orders/page,orders/[number]/page,addresses/page,wishlist/page,profile/page,security/page}.tsx`, `src/app/(auth)/{login,register,forgot-password,reset-password}/page.tsx`.

**Specification:** account layout with side nav (responsive to tabs on mobile); orders list with status chips; order detail mirrors confirmation + invoice download + tracking; addresses CRUD with default badges; wishlist grid with add-to-cart; profile + marketing consent toggle; password change; login/register/forgot/reset pages with proper error states and redirect-back behavior. Auth-gated via middleware (redirect to /login?next=…).

**Verification:** full click-through of every page as a real migrated-style user (create via API); password reset email round-trip on preview.

**CHECKPOINT:** quick video/screen walkthrough for Hammed.

---

# PHASE D — ADMIN PORTAL (admin/ app → backend.tokecosmetics.com on Vercel)

General admin rules: same BFF auth pattern but **staff-only** (backend rejects non-staff JWT on `/api/v1/admin/*`); data tables via TanStack Table; every mutation optimistic-with-rollback or explicit-refresh; desktop-first but usable on tablet; keep it clean and fast over pretty (shadcn/ui defaults are fine).

## Plan-16-admin-foundation

**Objective:** Admin shell: staff login, RBAC, layout, navigation, audit surface.

**Depends on:** Plan-03. Parallel-safe with Phase C.

**Specification:**
1. **RBAC backend (in `apps/accounts/`):** `Role(name)` with Django permission groups mapping: seed roles `Owner` (all), `Manager` (orders/products/customers/coupons/reports), `Support` (orders read+transition, customers read), `Content` (CMS only). `StaffInvite` flow: Owner creates invite → email → set password. DRF permission class `HasAdminScope("orders.manage")` used across all admin endpoints (retrofit onto Plans 05–11 admin endpoints — they were built with `IsAdminUser`; tighten now).
2. Admin app: login page (staff check), sidebar nav (Dashboard, Orders, Products, Inventory, Customers, Reviews, Coupons, Content, Reports, Settings, Staff), topbar with env indicator (STAGING red badge when pointing at non-prod), global search (orders by number/email, products by name/SKU, customers by Toke ID/email/name).
3. `AuditLog` model in core: `(actor, action, model, object_id, changes JSON, ip, created_at)` — DRF mixin writes it on every admin mutation. Viewer page under Settings.
4. Session security: 15-min access token enforced; idle logout; admin endpoints throttle-per-user.

**Verification:** role-restricted user cannot access forbidden endpoints (test each role); audit rows appear for a product edit.

**CHECKPOINT:** Hammed logs into backend-preview URL with an Owner account.

## Plan-17-admin-catalog-inventory

**Objective:** Full product & stock management UI.

**Depends on:** Plan-16, backend 05/06.

**Specification:** products table (search, status filter, bulk actions activate/archive); product editor — tabbed form (Details, **Availability: per-country visibility checkboxes incl. "International (Rest of World)"**, **Variants: an option-matrix builder — define option names + values (e.g. Size: 50ml/100ml; Shade: Fair/Medium/Deep), click "Generate variants", and the grid of all combinations appears with per-variant SKU (auto-suggested), prices per currency, stock per warehouse, and optional variant image; add/remove a value regenerates without losing filled rows; single-variant products skip the builder entirely (Shopify-style flow — Hammed explicitly wants variable products painless to create)**, prices grid **with an "unpriced for market X" indicator per row**, Images drag-drop upload+reorder, Content: ingredients/directions/warnings/specs/FAQs, SEO fields with Google-style preview, Related); categories tree manager (drag to reparent); brands/collections CRUD; warehouse manager (CRUD + serves-countries mapping + priority); inventory screen — stock grid (variant × warehouse, plus computed per-country availability columns = sum of serving warehouses), adjust modal (reason+note mandatory), movement history drawer, low-stock filter, CSV import wizard (upload → column map → dry-run report → apply) and export button; "unpriced products per market" checklist view (products hidden in a country only because a price is missing).

**Verification:** create a full product with 2 variants, 4-currency prices, images — confirm it appears correctly on the storefront preview in two countries; CSV round-trip (export, edit a qty, import, movement logged).

**CHECKPOINT:** Hammed creates one product himself end-to-end.

## Plan-18-admin-orders-customers

**Objective:** Order operations and customer management UI.

**Depends on:** Plan-16, backend 10/11.

**Specification:** orders table (status tabs, date/gateway/country filters, export CSV); order detail — items, totals, payment panel (gateway ref, verify-again button), timeline (OrderEvents), status transition buttons (only legal ones shown), tracking form (carrier+number → sends email), refund modal (amount, reason, restock toggle), admin notes, print invoice; **needs-attention queue** surfaced prominently (filter is `review_reason != ''` — `needs_review` is NOT a status, see Plan-10); customers table (search, orders count, lifetime value) + detail (profile, addresses, order history, notes, deactivate); reviews moderation queue (approve/reject with reason).

> **[2026-07-16, added by Plan-10 — BANK TRANSFER IS UNFINISHED AND THIS IS ITS OWNER.**
> `bank_transfer.py` says "an admin confirms receipt (Plan-18)" but Plan-18's spec never
> mentioned it, so the deferral had no owner. It does now. **`bank_transfer` is seeded
> ACTIVE for NG** (`payments/migrations/0002`) and is a dead end until the below ships —
> an order can be placed and paid but never fulfilled. Do not launch NG without this.
>
> 1. **Confirm-receipt action** on the payment panel for manual gateways. It must NOT go
>    through `gateway.verify()` — there is nothing to ask; the staff member reading the
>    bank statement *is* the verification (`verify()` raises `ManualVerificationOnly`).
>    Build it as its own service that records who confirmed and what amount, then reuses
>    `mark_paid` **and the same verdict reactions `confirm_payment` has** (re-reserve on
>    `NOOP_EXPIRED`, flag on `NOOP_CANCELLED`). Factor that verdict block out of
>    `payments/services.py` so both entry points share it — otherwise this stage
>    reimplements the recovery paths badly.
> 2. **Per-gateway reservation TTL.** `RESERVATION_TTL_MINUTES=30` vs a transfer that
>    takes hours ⇒ today every bank-transfer order expires before the money lands and the
>    exception path becomes the happy path. Make the TTL a gateway attribute
>    (`reservation_expires_at` is computed in one place, `checkout.py`) with a settings
>    override. **~24h, not 48h:** NG transfers are NIP/instant — the real delay is *human
>    confirmation*, i.e. staff working hours ("paid 11pm, confirmed 10am"). The multi-day
>    tail is already caught by the expired→re-reserve lane.
> 3. **Expired manual orders must email the customer.** `expired` mails nothing by design
>    (correct for an abandoned card checkout) but a bank-transfer customer may believe
>    they have paid. "Your payment window closed — if you already transferred, reply and
>    we'll match it" turns a silent failure into a recoverable one. Per-gateway
>    distinction on the expiry effect, not just on the TTL.
>
> Don't over-build the manual flow: Decision 3 names Paystack dedicated accounts as the
> endgame, which makes bank transfer webhook-confirmed with a real `verify()`. The manual
> path may be transitional. When that lands, add `confirmation: "gateway" | "manual"` as
> the gateway attribute governing verify()/confirm-queue/TTL — dedicated accounts are
> `confirmation="gateway"` **and** `action="bank_details"` (they still need the
> instructions email), which is exactly why a single `is_instant` bit is the wrong model.

**Verification:** process a test order end-to-end in the UI: paid → add tracking (email received) → delivered → partial refund (gateway test mode) with restock. Approve a review, see it on the PDP. **Plus: place a bank_transfer order, confirm receipt as staff, see it fulfil and the customer emailed.**

**CHECKPOINT:** Hammed processes one order himself.

## Plan-19-admin-marketing-cms

**Objective:** Coupons + all marketing-managed content (homepage, banners, pages, menus) without developer help.

**Depends on:** Plan-16. Backend CMS models built in THIS stage (they were stubbed for Plan-13):

**Specification:**
1. Backend `apps/cms/`: `Banner(title, subtitle, image, mobile_image, cta_text, cta_url, placement[hero/strip/category], sort, starts_at, ends_at, is_active, countries M2M blank=all)`; `HomepageSection(type[hero/collection_carousel/banner_grid/editorial/brand_strip], sort, config JSONField, is_active)`; `Page(title, slug, body rich text, seo fields, status)` for About/Contact/Policies/FAQs; `MenuItem(label, url, parent, sort, menu[header/footer])`. Public endpoints: `GET /api/v1/cms/homepage/`, `/cms/pages/{slug}/`, `/cms/menus/`. Admin CRUD for all.
2. Admin UI: homepage builder (ordered section list, add/edit/preview section, publish), banner manager with schedule + country targeting, pages editor (rich text — use TipTap), menu manager, coupon manager (create single or bulk-generate codes, limits, validity, scope; usage stats per coupon), payment-gateways-by-country manager (CountryPaymentGateway CRUD — toggle/reorder which gateways appear per country, incl. Rest of World); **delivery manager: regions browser (country → states → LGAs tree, activate/deactivate, shows each country's `area_label`) and delivery-options CRUD — create an option with name, price (+ optional weight tiers), ETA days, and a coverage picker that multi-selects whole countries, whole states, or individual LGAs/cities in one tree control (mixed granularity per Decision 13), plus a "test an address" widget that shows which options a given state/LGA would see**.
3. Storefront: replace Plan-13 fixtures with live CMS API + on-demand revalidation on CMS save.

**Verification:** Hammed's team changes the hero banner and sees it live on preview within a minute (revalidation working); coupon created in admin works at checkout.

**CHECKPOINT:** content edit demo by Hammed.

## Plan-20-admin-dashboard-reports

**Objective:** MVP analytics: KPI dashboard + core reports + exports. (Deep analytics/traffic = post-launch; storefront gets GA4 + Vercel Analytics tags in Plan-25.)

**Depends on:** Plan-16, backend 10.

**Specification:**
1. Backend `apps/analytics/`: aggregate queries (revenue, order count, AOV, top products, top customers, sales by category/brand/country/gateway, refunds, coupon performance, abandoned cart count) with date-range + country params. Materialize daily aggregates via nightly Celery task into `DailySalesRollup(date, country, currency, orders, revenue, refunds…)` so date-range queries stay instant; today computed live. Currency handling: report **per currency** (no FX mixing) with per-currency totals side by side — document this limitation.
2. Endpoints under `/api/v1/admin/reports/…` + `?format=csv` streaming export; XLSX export via openpyxl Celery job → S3 signed link (for big ranges); simple PDF summary (WeasyPrint, reuse invoice plumbing).
3. Admin UI: dashboard (KPI cards with vs-previous-period deltas, revenue chart, orders-by-status donut, top products table, low stock widget, needs-review widget); Reports page (pick report, range, country → table + export buttons). Charts: recharts.

**Verification:** seed 3 months of factory orders; dashboard numbers hand-checked against SQL; CSV/XLSX open correctly in Excel.

**CHECKPOINT:** Hammed reviews dashboard with seeded data.

---
# PHASE E — MIGRATION (apps/migration_wp/ — management commands, run ON THE VPS web container)

Migration ground rules:
- All importers are **idempotent** (re-runnable: match on `legacy_source` + `legacy_wp_id` / `legacy_number`, update-or-skip, never duplicate) and support `--dry-run` (prints a report, writes nothing).
- They read MariaDB directly (`pymysql` connection using creds from env `WP_NG_DB_*` / `WP_INTL_DB_*` — read-only MySQL user: ask Hammed to approve creating `CREATE USER 'wp_readonly'@'localhost' … GRANT SELECT`).
- MariaDB port 3306 is on the host; from inside Docker use `host.docker.internal`/host-gateway (add `extra_hosts: ["host.docker.internal:host-gateway"]` to web/worker services).
- Every run writes a `MigrationRun(command, started, finished, stats JSON, errors JSON)` row; every skipped/broken source record is logged with its WP id — nothing silently dropped.
- After each importer: a **verification command** compares source vs destination counts and spot-checks samples, output saved to `docs/migration/verification-<stage>.md`.

## Plan-21-migration-products

**Objective:** NG catalog (products, variations, categories, brands/attributes, images) → new platform. Intl products NOT migrated as separate entities (per Hammed: NG inventory is the source of truth) — but Plan-23 needs intl order items to reference *something*: order items store snapshots, so no product linkage is required for intl-only products.

**Depends on:** Plan-05, Plan-02. 

**Files:** `apps/migration_wp/management/commands/{migrate_categories.py,migrate_products.py,migrate_media.py}`, `apps/migration_wp/wp_reader.py` (shared SQL layer), tests with a fixture MySQL dump.

**Specification:**
1. `wp_reader.py`: thin functions returning dicts. Core queries (NG store, prefix `wp_`):
```sql
-- products
SELECT p.ID, p.post_title, p.post_name AS slug, p.post_content, p.post_excerpt,
       p.post_status, p.post_date_gmt
FROM wp_posts p WHERE p.post_type='product' AND p.post_status IN ('publish','draft');

-- all postmeta for a product id (pivot in Python):
SELECT meta_key, meta_value FROM wp_postmeta WHERE post_id=%s;
-- keys used: _sku, _price, _regular_price, _sale_price, _sale_price_dates_from/to,
-- _stock, _stock_status, _manage_stock, _weight, _thumbnail_id, _product_image_gallery,
-- _product_attributes (PHP-serialized — parse with phpserialize)

-- variations of a product
SELECT ID, post_title, post_name FROM wp_posts
WHERE post_type='product_variation' AND post_parent=%s AND post_status='publish';
-- variation attributes: postmeta keys LIKE 'attribute_%%'

-- category tree
SELECT t.term_id, t.name, t.slug, tt.parent, tt.description
FROM wp_terms t JOIN wp_term_taxonomy tt USING(term_id) WHERE tt.taxonomy='product_cat';

-- product→category / product→attribute term links
SELECT tr.object_id, tt.taxonomy, t.term_id, t.name, t.slug
FROM wp_term_relationships tr
JOIN wp_term_taxonomy tt ON tr.term_taxonomy_id=tt.term_taxonomy_id
JOIN wp_terms t ON tt.term_id=t.term_id
WHERE tt.taxonomy IN ('product_cat','product_tag') OR tt.taxonomy LIKE 'pa_%%';

-- attachment file for an id
SELECT pm.meta_value FROM wp_postmeta pm WHERE pm.post_id=%s AND pm.meta_key='_wp_attached_file';
```
   Use `phpserialize` (add to pyproject) for `_product_attributes` and gallery parsing. Handle broken serialization gracefully (log, continue).
2. `migrate_categories`: WP tree → `Category` preserving **slug exactly** and parent links; store term_id in `legacy_wp_id`.
3. `migrate_products`: each WP product → `Product` (slug preserved EXACTLY — SEO-critical) + variants:
   - simple product → one default `ProductVariant` (sku from `_sku` or generated `TC-WP-<id>`); variable product → one variant per variation with `option_values` from its attributes.
   - Prices: `_regular_price` → `Price(currency=NGN, amount)`; `_sale_price` (+date window) → additional NGN Price row with `compare_at_amount=regular`, `starts_at/ends_at` from `_sale_price_dates_*`. **GBP/USD/CAD prices are NOT derivable from the NG store** — create the NGN rows only and emit `docs/migration/pricing-todo.csv` (variant, name, NGN price) for Hammed's team to fill international prices in the admin (Plan-17 grid) before launch. Audit Plan-00 item 8 may find intl-site prices for matching SKUs — if SKUs match across stores, prefill from `tokecosm_usawp100` the same way and note "prefilled from intl site" in the CSV.
   - Stock: NG-store `_stock`/`_stock_status` → `StockItem(quantity, warehouse="Lagos HQ")` + `StockMovement(reason='migration')`. **Intl-store stock seeds the UK warehouse:** match intl products to migrated NG products by SKU (fallback: normalized name); matched `_stock` from `tokecosm_usawp100` → `StockItem(warehouse="UK Warehouse")`. Unmatched intl products with stock > 0 go in a report for Hammed (they may need manual creation). Have Hammed's team confirm both warehouses' real counts before launch — WP stock numbers drift from physical reality.
   - `ingredients/directions/warnings`: audit item 3 will reveal where these live (often in description or ACF meta) — extract if structured, else leave in description.
4. `migrate_media`: for each referenced image: copy from `/home/tokecosm/public_html/wp-content/uploads/<path>` (mounted read-only into the container: add a `volumes: - /home/tokecosm/public_html/wp-content/uploads:/mnt/wp-uploads-ng:ro` entry) → upload to S3 under `media/catalog/<product-slug>/<filename>` → create `ProductImage`. Skip missing files with a logged warning (broken-image report). De-dupe by (product, source filename).
5. Verification command `verify_products`: counts (products, variants, categories, images) source vs dest; 5 random products printed side by side (name, slug, price, stock, image count); every WP published product either migrated or listed with a reason.

**Verification:** dry-run report reviewed → real run → verify_products clean → spot-check 5 product pages on the storefront preview vs the live WP pages.

**CHECKPOINT:** Hammed reviews the storefront with real products + the pricing-todo.csv handoff.

## Plan-22-migration-customers

**Objective:** Migrate customers **who have ≥1 order** (either store), preserving login ability where possible.

**Depends on:** Plan-03, Plan-00 item 5.

**Files:** `apps/migration_wp/management/commands/migrate_customers.py`, `apps/accounts/hashers.py`, tests.

**Specification:**
1. **WordPress password compatibility — full implementation (put exactly this in `apps/accounts/hashers.py`):**
```python
import base64, hashlib, hmac
import bcrypt                      # add dependency: bcrypt
from passlib.hash import phpass    # add dependency: passlib
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash

def _verify_wp_hash(password: str, wp_hash: str) -> bool:
    """Supports all three formats found in wp_users.user_pass:
    - '$wp$2y$...'  WP >= 6.8: bcrypt over base64(HMAC-SHA384(password, key='wp-sha384'))
    - '$P$...' / '$H$...'  classic phpass
    - '$2y$...'  plain bcrypt (some security plugins)
    """
    if wp_hash.startswith("$wp$"):
        pre = base64.b64encode(hmac.new(b"wp-sha384", password.encode(), hashlib.sha384).digest())
        return bcrypt.checkpw(pre, wp_hash[3:].encode())   # strip leading '$wp' -> '$2y$...'
    if wp_hash.startswith(("$P$", "$H$")):
        return phpass.verify(password, wp_hash)
    if wp_hash.startswith(("$2y$", "$2a$", "$2b$")):
        return bcrypt.checkpw(password.encode(), wp_hash.encode())
    return False

class WordPressPasswordHasher(BasePasswordHasher):
    """Stored as 'wordpress$<original wp hash>'. verify() delegates to _verify_wp_hash.
    must_update() returns True so Django transparently re-hashes with the default
    (Argon2/PBKDF2) hasher on the user's first successful login."""
    algorithm = "wordpress"

    def verify(self, password, encoded):
        _, wp_hash = encoded.split("$", 1)
        return _verify_wp_hash(password, wp_hash)

    def encode(self, password, salt=None):
        raise NotImplementedError("wordpress hasher is verify-only")

    def must_update(self, encoded):
        return True

    def safe_summary(self, encoded):
        _, wp_hash = encoded.split("$", 1)
        return {"algorithm": self.algorithm, "hash": mask_hash(wp_hash)}
```
   Settings: `PASSWORD_HASHERS = [Argon2… (default list), "apps.accounts.hashers.WordPressPasswordHasher"]`. Tests: generate a real phpass hash with passlib, a real `$wp$2y$` (construct with the same pre-hash + bcrypt), verify login works and the hash is upgraded after `authenticate()`.
2. `migrate_customers` (per store): users with ≥1 order (`JOIN wc_orders ON customer_id`) → `User(email lower-cased, names from usermeta first_name/last_name or billing meta, phone from billing_phone usermeta, password="wordpress$"+user_pass, toke_id=generate_toke_id() — migrated customers get their Toke ID at import like everyone else, legacy_source, legacy_wp_id, marketing_consent=False)` + `Address` from billing/shipping usermeta if complete.
   - **Email collision across the two stores:** same email in both → ONE user; keep NG as primary `legacy_source`, record intl id too (add `legacy_wp_id_intl` nullable int).
   - Users whose hash format is unrecognized → import with unusable password (`set_unusable_password()`) and include in the "must reset" list.
   - Guest-order emails do NOT get accounts (orders keep the email; guest→account conversion path from Plan-11 covers them organically).
3. Post-launch comms artifact: write `docs/migration/customers-report.md` — counts migrated per store, collisions merged, unusable-password count — and a CSV for a "welcome to the new site" email campaign (sent manually post-cutover, not automatically).

**Verification:** dry-run stats ≈ audit item 5 numbers; log in on the staging storefront AS A REAL MIGRATED USER with their old password (coordinate with Hammed to use his own test account from the old store, or create one on live WP first and migrate it).

**CHECKPOINT:** live demo of an old-password login on staging. Hammed signs off on the must-reset list size.

## Plan-23-migration-orders

**Objective:** Complete order history from BOTH stores into `Order`/`OrderItem` with `source`/`legacy_number`, linked to migrated users by email.

**Depends on:** Plan-10, Plan-22 (+ any pre-Nov-2025 archive found by Plan-00 item 2).

**Files:** `apps/migration_wp/management/commands/migrate_orders.py`, tests.

**Specification:**
1. HPOS extraction (per store, adjust prefix):
```sql
SELECT o.id, o.status, o.currency, o.total_amount, o.customer_id,
       o.billing_email, o.date_created_gmt, o.payment_method, o.payment_method_title,
       o.transaction_id, o.customer_note, o.ip_address
FROM wp_wc_orders o WHERE o.type='shop_order' AND o.status <> 'trash';

SELECT address_type, first_name, last_name, company, address_1, address_2,
       city, state, postcode, country, email, phone
FROM wp_wc_order_addresses WHERE order_id=%s;

SELECT oi.order_item_id, oi.order_item_name, oi.order_item_type
FROM wp_woocommerce_order_items oi WHERE oi.order_id=%s;
-- itemmeta per item: _product_id, _variation_id, _qty, _line_subtotal, _line_total, _line_tax, _sku (via lookup)
SELECT meta_key, meta_value FROM wp_woocommerce_order_itemmeta WHERE order_item_id=%s;
-- shipping lines: order_item_type='shipping' (name + cost meta); fee lines: 'fee'; coupon lines: 'coupon' (code + discount_amount meta)
-- order meta (refunds have their own wc_orders rows with type='shop_order_refund' and parent_order_id)
```
2. Status mapping: `wc-completed→completed`, `wc-processing→processing`, `wc-on-hold→on_hold`, `wc-cancelled→cancelled`, `wc-refunded→refunded`, `wc-pending→cancelled` (historic pendings are dead), `wc-failed→cancelled`. Keep the raw WP status in an `OrderEvent(type='migration', message='WP status: wc-on-hold')`.
3. Field mapping: `number = legacy prefix + WP id`? NO — `number` stays the WP order number string (e.g. `1234`) ONLY if globally unique across both stores; since both stores are numeric ids, prefix them: NG order 1234 → `number="NG-1234"`, intl → `"INT-1234"`, and store the bare original in `legacy_number`. `placed_at=date_created_gmt (UTC)`, totals from HPOS columns + item lines, `currency` as recorded, addresses → JSON snapshots, `payment` → a `Payment(status=succeeded if completed/processing, gateway=payment_method, gateway_reference=transaction_id, raw_response={'migrated': True})` for paid statuses.
4. Items: snapshots from item name/meta (`product_name`, `sku`, `unit_price=_line_subtotal/_qty` guarded for qty=0, `quantity`, `line_total`). Link `variant` FK when a migrated NG variant matches `_product_id`/`_variation_id` via `legacy_wp_id`; intl items stay snapshot-only (variant NULL) — this is fine by design.
5. User linkage: match `billing_email` (lowered) to migrated users; unmatched → guest order (user NULL). Refund rows (`shop_order_refund`) → `Refund` records attached to the parent's Payment with `status=succeeded`.
6. **Do NOT touch inventory** (reason: history, not new sales — no StockMovements) and **do NOT send any emails** during import (guard: importer sets `order._suppress_signals = True`; notification signal handlers check it).
7. `verify_orders`: per store — count by status source vs dest, sum of grand totals per currency source vs dest (to the kobo/penny), 5 random orders diffed field-by-field, orphan report (orders whose email matched no user = expected guests).

**Verification:** totals reconcile exactly per currency per store; a migrated customer sees their old orders (both stores) in the staging account dashboard.

**CHECKPOINT:** Hammed picks 3 real orders he remembers and finds them in the new admin.

## Plan-24-migration-seo-redirects

**Objective:** Zero SEO loss at cutover: every indexed old URL 301s to its new home; sitemaps ready; intl domain folds into the main domain.

**Depends on:** Plan-13, Plan-21, Plan-00 item 7.

**Files:** `apps/migration_wp/management/commands/build_redirects.py`, storefront `src/middleware.ts` (extend), `docs/migration/redirect-map.csv`.

**Specification:**
1. Build the URL inventory (from audit item 7): all product, category, page, and blog URLs from both WP sites + Google Search Console top-pages export if Hammed can provide it.
2. `build_redirects`: generate `Redirect` rows (core model from Plan-03):
   - WP product URL pattern (e.g. `/product/<slug>/` — confirm the actual permalink base from audit) → `/product/<slug>` (same slug guaranteed by Plan-21).
   - `/product-category/<slug>/` → `/category/<slug>`; pages `/<slug>/` → `/page/<slug>` or dropped-with-redirect-to-home if not migrated (explicit list, Hammed approves).
   - `/shop/` → `/products`; paginated/filtered old URLs → their base target. `?` query junk stripped.
   - Old-domain map: every tokecosmeticsintl.com URL → the equivalent tokecosmetics.com URL (same rules).
3. Serving redirects: storefront `middleware.ts` checks a compiled redirect map — fetched from `GET /api/v1/redirects/` at build time into `redirects.json` (regenerated on deploy) for the finite explicit list, plus the 3 pattern rules coded directly in middleware. Unknown 404s: log to backend (`POST /api/v1/redirects/miss/`) so the admin Redirect manager (simple CRUD page in admin Settings — add it here) shows real 404 traffic to patch post-launch.
4. Intl domain: after cutover, Cloudflare Bulk Redirect (or a tiny VPS vhost) 301s `tokecosmeticsintl.com/*` → mapped path on tokecosmetics.com. Keep for ≥ 12 months.
5. Canonicals on the new site already handled in Plan-13; verify no `next.tokecosmetics.com` URLs ever get indexed: `X-Robots-Tag: noindex` header on the staging domain (Vercel env-conditional) — REMOVE it in the cutover runbook (this is a classic launch-killer; it's called out again in Plan-27).

**Verification:** script fires HEAD requests at the top-200 old URLs against a staging host header and asserts 301→200 chains land on the right pages; `redirect-map.csv` reviewed.

**CHECKPOINT:** Hammed approves the dropped-pages list.

---
# PHASE F — LAUNCH

## Plan-25-qa-hardening

**Objective:** The security/performance/accessibility sweep that earns "production-ready".

**Depends on:** all of Phases B–E functionally complete.

**Specification:**
1. **Security checklist (do every item, record evidence in docs/security-review.md):**
   - Run `/security-review` skill (or a manual OWASP pass) over the backend: IDOR checks on every `/me/` and `/orders/{number}` endpoint (user A cannot fetch user B's order — write the tests), mass-assignment (serializers use explicit `fields`, never `__all__` on writable), SQLi (ORM-only; any `raw()` audited), XSS (product descriptions/CMS bodies sanitized server-side with `bleach` allowlist — this is stored HTML rendered by the storefront!), file upload validation (content-type + magic bytes + size caps + image re-encode via Pillow), webhook signature tests per gateway, JWT blacklist actually blocks after logout, admin endpoints reject non-staff and wrong-role staff, rate limits verified with a loop, secrets audit (`git log -p | grep -iE 'key|secret|password'` on the repo, env files perms on VPS), DEBUG=False + ALLOWED_HOSTS strict, dependency scan (`pip-audit`, `npm audit`) with fixes.
   - Django `manage.py check --deploy` clean. Security headers on both apps (CSP for storefront: default-src 'self' + explicit gateway/analytics origins; verify with securityheaders.com).
   - Backups restore-drill again on the now-real DB; document RPO (24h) / RTO in `docs/runbooks/disaster-recovery.md`.
2. **Performance:** Lighthouse CI (mobile) on home/PLP/PDP/cart ≥ 95 perf, 100 SEO, ≥ 95 a11y, ≥ 95 best-practices; k6 (or locust) on the API: 100 concurrent browsers on product list + 20 rps checkout mix, p95 < 400 ms API-side on the VPS while WP still runs — tune gunicorn workers, add missing DB indexes (`django-silk` or `explain` the top queries), verify Redis cache hit rate.
3. **Accessibility:** axe-core automated pass on all storefront routes (0 critical), manual keyboard-only checkout walkthrough, focus states visible, form errors announced (aria-live), images alt'd from admin data, contrast checked in the design tokens.
4. **Test sweep:** backend coverage ≥ 85% on money paths (pricing, checkout, payments, orders, inventory) — coverage report in CI; Playwright e2e suite for the 7 golden paths (browse→PDP→cart→inline-signup checkout→pay(stripe test)→confirmation; PDP Buy Now as a returning user; login; account order view; admin order processing; admin variable-product create via the option-matrix builder; coupon apply) running against preview in CI nightly.
5. Observability: Sentry (backend + both frontends) with release tags; UptimeRobot (or similar free) on `/healthz/` + storefront home; Django admin error-log page fed by a `SystemEvent` model capturing Celery task failures.

**Verification:** all checklists green with evidence linked from docs/security-review.md.

**CHECKPOINT:** Hammed receives a plain-English risk summary: what was found, what was fixed, what's accepted-and-why.

## Plan-26-staging-uat

**Objective:** Everything live on real staging domains; Hammed's team runs structured UAT; international prices entered.

**Depends on:** Plan-25.

**Specification:**
1. Domains live: `next.tokecosmetics.com` (storefront, Vercel custom domain, **noindex header ON**), `backend.tokecosmetics.com` (admin, Vercel), `api.tokecosmetics.com` (already). Full production env vars (test-mode payment keys still).
2. Fresh full migration run (products + customers + orders) against current live data; verification commands re-run; pricing-todo grid: Hammed's team enters GBP/USD/CAD prices in admin; spot-check 10 products per country.
3. UAT script in `docs/uat-checklist.md` (~60 scenarios written out: browse/search/filter per country, new-customer inline-signup checkout AND returning-customer checkout per gateway, Buy Now, LGA-based delivery options for at least 3 different Nigerian addresses, coupon, refund, stock-out behavior, account flows incl. old-WP-password login and multi-address book, admin flows incl. variable-product creation and delivery-option setup, CMS edit, report export, mobile pass). Hammed + one team member execute; every failure becomes a GitHub issue; fix and re-test until the checklist is 100%.
4. Payment gateways: flip to LIVE keys; do ONE real small-value transaction per gateway (₦100 Paystack, ₦100 Flutterwave, £1 Stripe, £1 PayPal) and refund it through the admin — this validates live webhooks end-to-end BEFORE cutover (configure live webhook URLs in each gateway dashboard pointing at api.tokecosmetics.com).
5. Content freeze coordination: agree the cutover date/time with Hammed (low-traffic window, e.g. 02:00 WAT); announce to his team.

**Verification:** UAT checklist 100% pass, 4 live payments verified + refunded.

**CHECKPOINT:** formal go/no-go decision with Hammed. No-go = fix list, repeat.

## Plan-27-cutover

**Objective:** tokecosmetics.com serves the new platform; old data delta-synced; old sites retired safely. **Write this as a timed runbook in `docs/runbooks/cutover.md` and rehearse the DNS steps verbally with Hammed first.**

**Runbook (execute in order, with rollback points):**
1. **T-24h:** final backups of BOTH WP DBs + uploads (`mysqldump` both DBs to `/root/pre-cutover-backups/` + S3). Verify Vercel prod deployment green. Confirm Cloudflare access.
2. **T-1h:** put WP NG store in "checkout paused" mode if plugin available, else banner ("maintenance shortly") — Hammed's call; announce on socials/story if desired.
3. **T-0 freeze:** WooCommerce orders freeze moment. Run delta sync: `migrate_orders --since <last-run-timestamp>` + `migrate_customers --since …` (importers support `--since` on `date_created_gmt` — built for exactly this). Verify delta counts.
4. **DNS switch (Cloudflare):** change `tokecosmetics.com` + `www` to point at Vercel (CNAME flattening per Vercel docs); add the domain to the Vercel storefront project (it becomes primary; `next.` stays as alias). Because Cloudflare proxies, TTL pain is minimal.
5. **Immediately after:** REMOVE the noindex header/env from the production domain (double-check `curl -sI https://tokecosmetics.com | grep -i robots` returns nothing); flip `NEXT_PUBLIC_SITE_URL`/canonical base to `https://tokecosmetics.com`; redeploy; submit the new sitemap in Google Search Console (both properties: old URLs property + new); Bing too.
6. Intl domain: Cloudflare bulk redirect tokecosmeticsintl.com → tokecosmetics.com per Plan-24 map.
7. WP sites: keep serving on `old.tokecosmetics.com` (already exists as a vhost — repoint docroot if needed) admin-only/IP-restricted for reference for 90 days. WP cron/emails DISABLED (no duplicate customer emails!): `define('DISABLE_WP_CRON', true);` + pause SMTP plugin — get Hammed's confirm for each edit (these are the first allowed WP writes).
8. **Monitor (48h):** Sentry error rates, payment success rate per gateway vs UAT baseline, GSC coverage/404 reports, redirect-miss endpoint, `docker stats`/`free -h`, order volume vs same weekday last week. On-call = whoever runs this + Hammed on WhatsApp.
9. **Rollback plan (decide within 2h if triggered):** DNS back to VPS (Cloudflare, instant-ish), un-pause WP checkout. New orders taken on the new platform during the window are exported (admin CSV) for manual handling. Rollback triggers: payment success rate collapse, checkout hard-broken, data-integrity discovery.
10. **T+7d:** confirm GSC indexing transferring (old URLs 301-crawled), Core Web Vitals field data starting, then schedule WP retirement (T+90d: archive DBs+files to S3 cold storage, remove vhosts, THEN reclaim the ~8 GB and drop the WP stack — separate approved change).

**CHECKPOINT:** T+48h review with Hammed: metrics summary, incident list, go-forward punch list. 🎉

---

# PHASE G — POST-LAUNCH (build in this order unless Hammed reprioritizes)

## Plan-28-accounting
Lightweight Sage-style module (`apps/accounting/`): double-entry-lite — `Account(code, name, type[asset/liability/income/expense/equity])`, `JournalEntry(date, memo, source[order/refund/manual/purchase])` + `JournalLine(entry, account, debit, credit)` with a balance constraint; auto-posting rules: paid order → DR cash/gateway-receivable CR sales + VAT payable; refund reverses; COGS posting from inventory valuation (moving average cost on `StockItem` — add `unit_cost`); purchase records (`Supplier`, `PurchaseOrder` receive flow updates stock + cost); expense entry UI; reports: P&L, sales/tax report, inventory valuation, customer balances (store credit groundwork), general ledger browser; CSV exports shaped for Sage import. Admin UI section "Accounting". Per-currency ledgers (no FX consolidation in v1).

## Plan-29-loyalty-referrals

**REFERRAL HALF: customer experience SHIPPED 2026-08-14** (`apps/referrals/`, storefront
`/account/referrals`). See `docs/runbooks/referral-programme.md`.

> **AMENDMENT 1 (Hammed, 2026-08-14): the published affiliate terms win over the sketch
> below.** This stage originally said "referral codes per user with reward on referee's
> first completed order". The shop already runs a public affiliate programme with
> different, *advertised* terms — <https://tokecosmetics.com/affiliates-2/> — and those
> are what customers have read: **10% of every qualifying sale** (not just the first),
> a **30-day click window**, commission on **net sales excluding shipping and tax**, a
> **60-day holding period** before it is payable, a **₦20,000 minimum payout** with
> balances rolling over, monthly bank transfer, no self-referral, and the **₦200k Club**
> tier. Building the one-off-reward model would have meant paying something other than
> what the shop has promised in public.
>
> Two decisions the published terms did not cover, both Hammed's call on 2026-08-14:
> **per-currency wallets with no FX conversion** (the terms name only ₦20,000 because the
> WordPress programme was Nigeria-only; this platform sells in four currencies), and
> **masked-plus-notified bank details rather than encryption at rest** (see the runbook's
> security notes for the threat model).
>
> Also dropped from the sketch: **no enrolment step.** Every registered customer is a
> referrer automatically, so there is no application, approval, or "join" button.

> **AMENDMENT 2 (Hammed, 2026-08-15): the single-balance question, and its two limits.**
> Hammed proposed one central wallet per customer — referral earnings and loyalty points
> both flowing in, payouts and checkout payment both flowing out — constrained to **one
> wallet in one currency, fixed by the market the account was created in**. Consulted
> Fable 5 for dissent; it disagreed with two of the three pillars and was right on both,
> verified against the code. What was settled:
>
> **(a) Balances stay PER-CURRENCY in the ledger. "One wallet" is a UI promise, not a
> schema rule.** The constraint as worded is not representable: `User` carries no country,
> market or currency field (`apps/accounts/models.py:65-98`) — accounts are global and
> country is stamped per ORDER. Backfilling a home market would be guesswork, worst for the
> migrated WordPress customers spanning three stores. It also contradicts Amendment 1's
> no-FX ruling one day later: a Nigerian referrer earns GBP when a UK friend buys, and a
> naira-only wallet cannot hold it. Resolution: keep the per-currency balances
> `services.balances()` already returns; the checkout rule is **you may spend the balance
> whose currency matches the order's currency**, so an NG shopper only ever sees naira.
> Foreign earnings stay withdrawable at their own threshold, just not spendable here.
>
> **(b) Loyalty points never become withdrawable cash.** Referral commission is a debt the
> shop owes; points are a revocable marketing gesture. A points-to-cash path is a
> laundering route (stolen card → buy → earn → convert → withdraw) and converts breakage
> into a cash liability. Points keep their own ledger and redeem at checkout as a
> **discount line**, as this stage always sketched. Two things then come free:
> `commission_base` already subtracts `discount_total` (`apps/referrals/services.py:261`),
> so a points-discounted referred order pays commission on the net with no new rule; and
> there is no cash-out path to abuse. Note the asymmetry, which is deliberate: referral
> CASH must NOT be a discount line, because `taxable = subtotal - discount`
> (`apps/checkout/services/totals.py:59`) would shrink VAT on goods the customer is paying
> full price for. Points reduce the price; commission pays the price.
>
> **(c) The derive-only principle does not survive a spendable balance.** No stored balance
> exists anywhere today, and payouts are safe only because claiming MUTATES the rows it
> read (`request_payout` takes `select_for_update()` on the Commission rows and flips them
> to `paid`). A checkout spend reads a SUM and INSERTS a negative row — row locks cannot
> lock a row that does not exist yet, so two tabs can both spend the same balance. Any
> spendable balance needs a `WalletAccount(user, currency)` anchor row taken with
> `select_for_update()` on every debit; a `balance` column on it is then an ENFORCED CACHE
> with a nightly `balance == SUM(entries)` reconciliation, ledger still authoritative.
> Non-negativity must be a spend-time check, NOT a DB constraint — clawbacks are
> deliberately allowed to push a balance negative (`apps/referrals/models.py:200-206`).
>
> **(d) Spending at checkout is a `Payment` row with `gateway="wallet"`, not a parallel
> money path** — hold at placement, capture in `_fulfil_locked`, release on expiry beside
> the stock reservation. Not debit-immediately: bank transfer is the dominant tender with a
> 24h window, so abandoned orders are routine. Split tender is less alien here than it
> looks — `retry_payment` already handles a Payment whose amount is not the grand total for
> RoW `quote_required` orders (`apps/checkout/services/checkout.py:284-290`), which is what
> `Payment.purpose` exists for. Three things break and must be handled: `refundable_amount`
> caps at `payment.amount` (`apps/payments/refunds.py:53-59`); `refunded_total_for` sums
> only `payments.Refund` rows (`apps/referrals/services.py:428-440`), so a wallet refund
> recorded outside that ledger silently stops commission reversal working in proportion;
> and `retry_payment` must mirror the remainder, not re-hold. Refund rule: money returns to
> the tender it came from, wallet-first on partials — never refund card money into a
> spendable balance.
>
> **(e) No migration of existing Commission rows.** Extend `balances()` so available =
> matured commissions + adjustments + wallet entries. The live rows never move.
>
> **(f) NO FUNGIBLE BALANCE TABLE, and the page is called "Rewards" — second Fable
> consult, same day, on the CBN/e-money question.** This SUPERSEDES the `WalletAccount` +
> `WalletEntry` sketch in (c): that design merged the ledgers, and a merged balance debited
> on withdrawal makes points cash-redeemable pro rata, which manufactures stored value in
> substance no matter what it is called. What keeps this arrangement ordinary store credit
> plus an ordinary trade payable is three rules: **no customer top-up ever** (e-money is
> value issued against funds received FROM the holder — no customer money ever enters
> here, and this feature does most of the work); **nothing but commission is ever
> withdrawable**; and **payouts keep claiming specific `Commission` rows**, exactly as
> `request_payout` does today. One Rewards PAGE satisfies "one place to see it", but the
> page shows **two figures** — "Affiliate earnings (withdrawable)" and "Store credit /
> points (spend at checkout)" — never one merged number. Vocabulary: avoid *wallet,
> e-wallet, cash balance, funds, top up, withdraw funds*; say "request a payout of your
> commission" and "store credit". Terms copy must say points have no cash value, are
> non-transferable, redeem only at tokecosmetics.com, and that commissions are payments
> under the affiliate agreement, not deposits.
>
> This reopens (c)'s concurrency question rather than answering it: without a fungible
> balance there is no `WalletAccount` row to lock. The likely answer is that a checkout
> spend CLAIMS specific commission rows the way a payout does (`select_for_update` on rows
> it then mutates, which is what makes payouts safe), with partial-row spend as the open
> problem. Settle it when slice 3 is designed, not before.
>
> **Open for a professional, not for code:** the withholding-tax question on commissions
> (already open), plus a new one that falls out of spend-at-checkout — **if an affiliate
> applies commission against an order, that is a set-off, and WHT may still be due on the
> gross commission even though no cash moved.** If so, WHT must be recorded at SETTLEMENT
> (payout *or* checkout application), not only at bank transfer. Eight questions drafted
> for the lawyer/accountant in `docs/runbooks/referral-programme.md`.

> **AMENDMENT 3 (Hammed, 2026-08-15): the tax and scope decisions, after the research.**
> The briefing in `docs/runbooks/referral-programme.md` went to Hammed with six questions
> for an accountant. He ruled directly rather than waiting, and the rulings narrow this
> stage considerably:
>
> **(a) No withholding, at any rate, for anyone.** Commission is paid in full — a
> referrer with ₦50,000 available receives ₦50,000, residents and non-residents alike.
> The MECHANISM is built anyway and defaults to zero: `settings.REFERRAL_WHT_PERCENT`,
> snapshot onto each `PayoutRequest` as `wht_rate_percent` / `wht_amount` / `net_amount`
> (plus remittance fields, unused). His instruction was to keep the tax rules
> configurable so the treatment can change without a rewrite, and this is that — an env
> var and a month's payouts, not a migration. `net_amount` is stored, not derived,
> because it is the figure a bank statement is reconciled against. Migration 0003
> backfills `net = amount` on every existing row; without it three real production
> payouts would read as having sent nothing.
>
> **(b) COMMISSION CANNOT BE SPENT AT CHECKOUT. Ever, in this version.** It is a payout
> balance and nothing else: not store credit, not a checkout tender, not a discount, not
> loyalty points, not a payment method. This CANCELS Amendment 2's slice 3 — the
> `WalletAccount`/`WalletEntry` concurrency design, the `gateway="wallet"` Payment leg,
> and the refund-routing rules are all moot and should not be built. It also moots the
> two hardest open questions in the tax briefing: WHT-on-set-off (there is no set-off)
> and VAT-on-credit-tender (nothing is ever tendered). What survives from Amendment 2 is
> the reasoning about why points-as-discount and commission-as-payment are different
> things — worth keeping for whenever loyalty points are built.
>
> **(c) Record-keeping is already sufficient.** Hammed's list — referrer identity,
> commission earned, related order, status, date earned, date available after the hold,
> date requested, date paid, payout amount, bank reference, and any reversal or clawback
> — maps onto fields that already exist (`Commission.matures_at`, `reversed_at`,
> `reversed_reason`, `PayoutRequest.paid_at`/`reference`, `ReferralAdjustment`). Nothing
> was built for this; it was checked and reported.
>
> **(d) Paid commission must be identifiable separately from sales revenue**, labelled
> **"Referrer Commission Paid"**. New report `referrer_commission` in `apps/analytics`,
> its own report rather than a line on `revenue`: commission is a marketing expense, and
> netting it against sales would answer "what did we sell" with affiliate costs already
> deducted. It reports six figures per currency — earned / paid / reversed as EVENTS in
> the window, pending / available / requested as POSITIONS right now. `paid` is keyed off
> `PayoutRequest.paid_at`, never `Commission.status == "paid"`, which means *claimed by a
> request* and would overstate cash out by everything sitting in the queue.

Still to build in this stage, in this order:
- **Admin referral surface (NEXT)** — payout queue with the fraud flags
  `services.fraud_flags` already computes, approve/reject/mark-paid (the services exist and
  are tested; nothing calls them over HTTP yet), blocking a referrer, manual adjustments,
  `referrals.*` RBAC scopes, and an **aging alert on payout requests stuck in `requested`**.
  Per Amendment 2 this needs NO wallet redesign: payouts keep drawing from the same
  per-currency derived balance, and wallet entries are just more signed rows in the same
  derivation.
- **Loyalty points** — `apps/loyalty/`: points config (earn rate per currency, redemption
  value, expiry), `PointsTransaction` ledger; earn on order completion, redeem as a
  checkout discount line; storefront account pages + admin config/report. No wallet
  dependency, no payment-core changes. Points accrue on the EXTERNALLY-PAID amount only —
  never on a slice paid with credit, or the shop compounds its own giveaway.
- ~~Spend-at-checkout~~ **CANCELLED by Amendment 3(b).** Commission is a payout balance
  and cannot be spent. Do not build `WalletAccount`, `WalletEntry` or the `wallet`
  Payment leg; `apps/payments/services.py` is not touched by this stage at all.

## Plan-30-marketing-automation
Abandoned-cart recovery emails (the Plan-08 flagged carts: 1h/24h sequences with resume-cart signed links, unsubscribe honored), post-purchase review-request email (7d after delivered), win-back (90d), newsletter campaign send via Resend (audiences/broadcasts), SMS via Termii (NG) for order updates opt-in, coupon-in-email personalization. All consent-gated; suppression list model.

## Plan-31-blog-content
`apps/blog/` (Post, Category, Author, SEO fields) + admin editor + storefront `/blog` with Article JSON-LD, internal-linking widgets to products, and the WP blog-post migration (audit found how many exist; same slug-preserving importer pattern + redirects).

## Plan-32-carrier-integrations
DHL + GIG Logistics (and future carriers) behind a `checkout/carriers/base.py::CarrierProvider` interface: `get_rates(address, parcel) -> list[RateQuote]`, `create_shipment(order) -> tracking_number + label_url`, `track(tracking_number) -> events`. A `DeliveryOption` with `kind="carrier"` calls `get_rates` live at checkout (with a cached fallback price when the carrier API is down — never block checkout on a carrier outage); admin order detail gets a "Book shipment" button that creates the shipment, stores the tracking number (customer email fires via the existing Plan-10 flow), and attaches the label PDF. Webhook/polling tracking updates advance shipped→delivered automatically. Needs API credentials from Hammed (GIG merchant account, DHL Express account). Everything else — option display, checkout, pricing UI — already works because carriers are just another `DeliveryOption` kind.

---

# APPENDIX A — Environment variables (single source of truth; `.env.example` files mirror this)

Backend (`/opt/tokecosmetics/.env.prod`, local `backend/.env`):
```
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=                     # 64 random chars; generate with: python -c "import secrets;print(secrets.token_urlsafe(64))"
ALLOWED_HOSTS=api.tokecosmetics.com
DATABASE_URL=postgres://toke:***@postgres:5432/toke
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
MEILISEARCH_URL=http://meilisearch:7700
MEILI_MASTER_KEY=
AWS_ACCESS_KEY_ID= / AWS_SECRET_ACCESS_KEY= / AWS_STORAGE_BUCKET_NAME= / AWS_S3_REGION_NAME=
EMAIL_BACKEND=anymail.backends.resend.EmailBackend   # unset in dev/tests -> console backend
RESEND_API_KEY=re_...           # Resend is the sole email provider
DEFAULT_FROM_EMAIL="Toke Cosmetics <hello@mg.tokecosmetics.com>"   # must be on the verified Resend domain
PAYSTACK_SECRET_KEY= / PAYSTACK_PUBLIC_KEY=
FLUTTERWAVE_SECRET_KEY= / FLUTTERWAVE_PUBLIC_KEY= / FLUTTERWAVE_VERIF_HASH=
STRIPE_SECRET_KEY= / STRIPE_PUBLISHABLE_KEY= / STRIPE_WEBHOOK_SECRET=
PAYPAL_CLIENT_ID= / PAYPAL_CLIENT_SECRET= / PAYPAL_MODE=sandbox|live
FRONTEND_URL=https://tokecosmetics.com
ADMIN_URL=https://backend.tokecosmetics.com
SENTRY_DSN=
WP_NG_DB_NAME=tokecosm_wp481 / WP_NG_DB_USER=wp_readonly / WP_NG_DB_PASSWORD= / WP_NG_DB_HOST=host.docker.internal
WP_INTL_DB_NAME=tokecosm_usawp100 / (same pattern)
REVALIDATE_SECRET=              # shared with storefront for on-demand ISR
```
Storefront (Vercel env): `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL`, `API_INTERNAL_TOKEN` (if used), `REVALIDATE_SECRET`, `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY`, `NEXT_PUBLIC_FLUTTERWAVE_PUBLIC_KEY`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_PAYPAL_CLIENT_ID`, `NEXT_PUBLIC_GA4_ID`, `SENTRY_DSN`, `STAGING_NOINDEX=1` (staging only).
Admin (Vercel env): `NEXT_PUBLIC_API_URL`, `SENTRY_DSN`.

# APPENDIX B — Definition of Done (applies to every stage)

1. All acceptance criteria in the stage met and demonstrated (not asserted).
2. Tests written and green locally AND in CI; no skipped tests without a linked issue.
3. Ran the actual thing (server/UI/e2e) — typecheck alone is never "done".
4. No secrets in git; `.env.example` updated when a variable was added.
5. Docs updated when behavior/architecture changed (`docs/architecture.md`, runbooks).
6. Conventional commits pushed; deployable state (main always deployable after Plan-02).
7. Checkpoint delivered to Hammed in plain language with something clickable/visual.

# APPENDIX C — When you are unsure

- Architecture/decision conflict → re-read Sections 4–5; if still ambiguous, ask Hammed with a recommendation ("I suggest A because…; OK?").
- Anything touching the live WP site, DNS, payment keys, or deleting data → ALWAYS stop and ask, showing the exact command.
- A stage feels too big to hold in your head → that's expected; expand it with `superpowers:writing-plans` into 2-5-minute TDD tasks FIRST. Do not free-style large stages.
- Original client requirements live in `dev_prompt.txt` next to this file — consult it when a detail here seems underspecified; this master file wins on conflicts (its decisions were approved by Hammed on 2026-07-12).
