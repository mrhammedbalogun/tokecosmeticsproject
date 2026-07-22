# Plan-13 — Storefront catalog + SEO (Home, PLP, PDP, search) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the real storefront pages — the 15-section premium homepage from Hammed's signed-off design brief, category/listing pages with crawlable URL-param filters, an Amazon-pattern product detail page (gallery + buy box with Add to Cart / Buy Now / delivery estimate), search with autocomplete — and the full enterprise SEO layer (`lib/seo.ts`, `generateMetadata` everywhere, JSON-LD, `sitemap.ts`, `robots.ts`), on top of the Plan-12 shell, ending at a design + Lighthouse + structured-data checkpoint for Hammed.

**Architecture:** Server Components by default; client islands only where interactivity demands (gallery zoom, variant picker, qty/buy buttons, carousels' arrow controls, announcement rotation, autocomplete, wishlist hearts, recently-viewed). All Django calls stay server-side through the existing `lib/api.ts` client (`X-Country` header, `next: { revalidate, tags }` data-cache); browser-side mutations go through same-origin BFF Route Handlers exactly as in Plan-12 (new ones this plan: wishlist, buy-now, suggest, revalidate). Pages render dynamically (they read the `country` cookie), so caching lives at the **fetch data-cache layer** with tags (`catalog`, `product:<slug>`), invalidated by a secret-protected `/api/revalidate` route. Framer Motion arrives this plan but only via `LazyMotion` islands — the Lighthouse mobile ≥ 95 / SEO 100 budget still binds on home/PLP/PDP.

**Tech Stack:** Next.js 16.2.10 (App Router) · React 19.2 · Tailwind CSS v4 tokens from `globals.css` · framer-motion (LazyMotion + `m`, scroll-reveal only) · Vitest + RTL (unit) · pytest (the two backend tasks) · next/image everywhere (backend media via `remotePatterns`, local generated SVG art via `dangerouslyAllowSVG` + CSP sandbox). Backend Django is **done** except the two explicitly-gated tasks in this plan (seed data + additive serializer fields) — nothing else in the backend may be touched.

**Spec:** `master-tokerebuild.md` lines 890–941 (Phase C rules + Plan-13) and `docs/design-direction.md` (the design authority Hammed signed off 2026-07-22 — palette, Playfair/Inter, the 15-section homepage, motion vocabulary, WCAG-AA + Lighthouse ≥ 95 non-negotiables). Read both before Task 1.

**Branch:** `plan-13-storefront-catalog-seo` off `main`.

---

## ⚠️ Read this first — Next.js 16 is not the Next.js you know

`storefront/AGENTS.md` warns: **this is Next.js 16.2.10, which has breaking changes vs. older App Router versions.** Before writing any page, metadata, sitemap, or route-handler code, read the bundled docs that ship in the repo under `storefront/node_modules/next/dist/docs/01-app/`:

- `03-api-reference/04-functions/generate-metadata.md` — `generateMetadata`, `params`/`searchParams` are **Promises** (`await` them).
- `03-api-reference/03-file-conventions/01-metadata/sitemap.md` and `robots.md` — `app/sitemap.ts` / `app/robots.ts` conventions.
- `03-api-reference/04-functions/revalidateTag.md` / `revalidatePath.md` — on-demand invalidation.
- `03-api-reference/02-components/image.md` and `05-config/01-next-config-js/images.md` — `next/image`, `remotePatterns`, `dangerouslyAllowSVG`.

Known Next-16 facts already baked into the shipped Plan-12 code: `cookies()`/`headers()` are **async** (`await cookies()`), middleware is **`src/proxy.ts`** (exported function `proxy`, not `middleware`), route pages receive `params`/`searchParams` as Promises. If a snippet in this plan disagrees with the bundled docs, **the bundled docs win** — treat plan code as shape/intent. Do not fetch these facts from memory or the public web.

---

## Decisions needing sign-off

Get Hammed's answers before the tasks noted. Recommendations are provided so nothing blocks — if Hammed is unavailable, proceed with the recommendation and record that in the commit message.

**D1 — Seed a realistic dev catalog via a backend management command + serve `/media/` in dev (blocks Task 1). RECOMMENDED: yes to both.**
The dev DB has only 4 products, essentially no stock, no reviews, no collection/tag data — the new pages would look like a wireframe and Hammed cannot judge the design. Task 1 adds `manage.py seed_dev_catalog`: **seed-data only, zero schema changes** — ≥ 24 products across 5 categories, brands, skin-concern tags, collections (`best-sellers`, `new-arrivals`, `glow-naturally`), prices in all 4 currencies (some with `compare_at_amount` sales), stock (including low-stock and one out-of-stock product), approved reviews feeding `rating_avg`, and Pillow-generated premium gradient placeholder images attached as real `ProductImage`/`Category.image` rows. Because Django's runserver does not serve `MEDIA_URL` by default, the task also adds the standard **3-line, DEBUG-only** `static(settings.MEDIA_URL, …)` block to `backend/config/urls.py` — a dev convenience, inert in production. Flag: confirm the command + the DEBUG-only urls edit are acceptable.

**D2 — Additive catalog serializer fields (blocks Tasks 2, 5, 11, 12). RECOMMENDED: yes — without variant `id` the PDP literally cannot add to cart.**
Verified against `backend/apps/catalog/api_serializers.py` and `backend/apps/carts/views.py`: the cart API takes `{variant_id}` (the **pk**), but `VariantSerializer` exposes only `sku` — so a PDP built on today's API has no way to add anything to the cart. Related gaps: product **cards** expose one image (no hover second image), no default-variant identifiers (wishlist heart and quick-add need a sku/id), no low-stock signal ("Only a few left"), and detail images don't say which variant they belong to. Task 2 adds **read-only, additive** fields (no schema change, no behaviour change, existing fields untouched):
- `VariantSerializer`: `id`, `low_stock` (true when `0 < available ≤ 5` in the request country).
- `ProductListSerializer`: `default_variant_id`, `default_sku`, `hover_image` (second image URL or null).
- `ProductDetailSerializer.get_images`: add `variant_id` to each image dict.
All pytest-covered. Fallback if Hammed refuses backend edits: fetch the product detail on wishlist/quick-add click (extra round-trip) and **drop** hover-swap + "only a few left" + add-to-cart-from-card; the PDP would still need `id` — there is no fallback for that, which is why the recommendation is a hard yes.

**D3 — Homepage content source until Plan-19 CMS. RECOMMENDED: typed constants in `src/lib/home-content.ts` + catalog API for product rows.**
Verified: **no CMS/content endpoints exist today** (`config/urls.py` has no CMS app; Plan-19 builds it). The master guide says "until then, seeded fixtures". Concretely: editorial copy (announcement messages, hero headline/CTAs, brand story, why-choose items, testimonials, community/education teasers) lives in one typed, commented module `src/lib/home-content.ts` that Plan-19 will later replace with API calls; product rows (best sellers, new arrivals, featured collection) come from the real catalog API via seeded collections. Also note: the design brief's nav items Collections/Ingredients/Blog/Community/Rewards have no routes yet — the header keeps Plan-12's category nav (+ a Skin Concerns link to `/products?tag=…`), and the full mega-nav lands when those routes exist (Plans 15/19). Confirm.

**D4 — Imagery = generated premium placeholders now; Hammed supplies real brand photography later. RECOMMENDED: proceed with placeholders.**
No licensed photography exists in the repo. Product/category photos: Pillow-generated soft gradient "product shot" placeholders seeded as real media (D1) so every API image URL is real. Homepage lifestyle/editorial art: deterministic brand-palette gradient SVGs generated by a committed script (`scripts/gen-placeholders.mjs`) into `storefront/public/home/`. The design will read premium-abstract rather than photographic. **Hammed: real brand photography (hero lifestyle shots, product photos) is a content task on you — when supplied, product photos drop in via the existing admin image upload (Plan-16 admin) or a re-run of the seed command pointed at real files, and `public/home/` files are replaced 1:1.**

**D5 — PDP delivery estimate line: static per-country copy (no backend change). RECOMMENDED: yes.**
The master guide wants the estimate "from the user's default address via the delivery-options endpoint" — but verified reality (`backend/apps/checkout/views.py:43`): `GET /checkout/delivery-options/` is `IsAuthenticated` **and requires an `address_id` + a non-empty `cart_id`** — it cannot quote a variant that isn't in a cart yet, which is exactly the PDP situation. No public per-product estimate endpoint exists, and this plan may not add one. So: `src/lib/delivery-estimates.ts` holds per-country copy (NG: "Delivery to Nigeria: 1–3 days, from ₦1,500" · GB/US/CA: "Delivery: 5–10 business days, calculated at checkout" · ZZ/RoW: "International delivery: quoted after checkout" — Hammed edits the strings); logged-in users with a default address see it personalised with their address label/state ("Delivery to Ikeja: …", data from `GET /me/addresses/`). Live quotes arrive with Plan-14 checkout where a cart + address exist.

**D6 — Buy Now guest path is partial until Plan-14. RECOMMENDED: authed path fully wired now; guests get a save-intent redirect.**
Verified: `POST /api/v1/checkout/buy-now/` **exists** (`backend/apps/checkout/urls.py:14`) — it builds an `express` cart holding exactly the Buy-Now item — but it is `IsAuthenticated`-only, and the inline-signup-inside-checkout step is Plan-14's. So this plan: logged-in Buy Now → BFF → express cart → `router.push("/checkout")` (the Plan-12 skeleton page — Plan-14 replaces it); logged-out Buy Now → stash `{variant_id, quantity}` in `sessionStorage` under `toke-buynow-intent` and redirect to `/login?next=/checkout` (the skeleton login page). The full guest resume path ("inline signup, land back in checkout with the item intact") is **explicitly Plan-14 scope** and its checkpoint. Confirm this split.

**D7 — On-demand revalidation: storefront half now, Django webhook later. RECOMMENDED: defer the Django side.**
The master guide wants Django `post_save` to call a Vercel revalidate route. This plan builds the storefront half completely: tagged fetches + `POST /api/revalidate` (secret in `REVALIDATE_SECRET`). Wiring Django to call it is a backend edit + deployment config (site URL, secret in Django env) that is pointless before Vercel exists — pages already render dynamically and the backend's own catalog cache is only 60 s. Defer the Django `post_save` webhook to the deployment plan (Plan-22); record it there.

**Flagged risks (no sign-off needed — recorded for later plans):**
- **Prod server-IP throttling:** DRF throttles anon 60/min **per IP**; in production every SSR fetch arrives from the Next server's IP, which would throttle the whole site. Same class of issue Plan-12 D5 noted for newsletter. Must be solved in Plan-22 (trusted proxy config / throttle exemption for the storefront server). Dev is unaffected.
- **PLP filter gaps:** `/products/` supports category/brand/tag/collection/price/ordering but its `in_stock` filter is a documented no-op, and **no rating filter exists anywhere**. `/search/` does support `in_stock`. This plan ships price + brand + sort on PLPs and an in-stock toggle on `/search` only; rating filter is future backend work.
- **Category SEO fields not exposed:** `Category.description/seo_title/seo_description` exist in the model but `/categories/` serves only `name/slug/image/sort_order/children` — category metadata falls back to name-based templates until a later additive backend change.
- **`priceValidUntil` not exposable:** the price API returns `compare_at` but not `ends_at`, so Product JSON-LD omits `priceValidUntil` (valid without it).

---

## Critical context for the implementer

You know nothing about this codebase. Read this before touching anything.

**What already exists (Plan-12, merged — build ON it, do not re-plan it):**
- `storefront/src/lib/api.ts` — `apiFetch<T>(path, opts)`: server-side Django client. Prefixes `API_URL` + `/api/v1`, sets `X-Country` (default NG), optional `token` → Bearer, `cartId` → `X-Cart-Id`, passes `next: { revalidate, tags }` through to fetch, throws `ApiError { status, data }` on non-2xx. **Every Django call goes through this.**
- `storefront/src/lib/session.ts` — `getAccessToken()`, `fetchWithAuth<T>(path, opts)` (silent refresh + retry-once on 401, persists rotated tokens).
- `storefront/src/lib/country.ts` — `COUNTRY_COOKIE`/`DEFAULT_COUNTRY`/`REST_OF_WORLD`, `getMarkets()`, `normalizeCountry()`, `formatMoney(amount, currencyCode, symbol)` (**grouping only, never rounds**), `labelFor(market)`.
- `storefront/src/lib/auth.ts` — cookie names + `cookieOptions()`. `src/lib/cart-types.ts` — `Cart`/`CartLine`/`EMPTY_CART`.
- `storefront/src/hooks/useCart.ts` — TanStack Query cart with `addItem`/`setQty` optimistic mutations against the `/api/cart` BFF.
- Layout: `src/app/(shop)/layout.tsx` (suggestion banner + `<Header/>` + `<main>` + `<Footer/>`), `Header.tsx` (server: logo, category nav from `/categories/`, `SearchBar`, `CountrySwitcher`, `AccountMenu`, `CartButton`+`CartDrawer`), `Footer.tsx` (policies, `NewsletterForm` → `/api/newsletter`, payment logos), `MobileNav`, `components/ui/Skeleton.tsx`, root `error/not-found/loading`.
- `src/proxy.ts` (Next-16 middleware): seeds `country` cookie (NG default), forwards geo hint. Matcher excludes `/api/`.
- BFF routes: `/api/auth/[action]`, `/api/cart/[[...path]]`, `/api/country`, `/api/newsletter`.
- Design tokens in `src/app/globals.css` (`--color-cream/beige/ink/ink-soft/line/accent/accent-strong/leaf/gold/surface`, `--font-display` Playfair / `--font-sans` Inter, `--radius-card`). Tailwind v4 utilities: `bg-background text-foreground text-muted border-line bg-accent bg-beige text-gold font-display` etc.
- Skeleton pages this plan **replaces**: `(shop)/page.tsx`, `(shop)/products/page.tsx`, `(shop)/category/[slug]/page.tsx`, `(shop)/product/[slug]/page.tsx`, `(shop)/search/page.tsx`.

**Backend API surface this plan consumes** (verified against code, not the master guide; dev base `http://localhost:8000`, all under `/api/v1/`, Swagger at `/api/docs/`):

- `GET /products/` — paginated `{count, next, previous, results}` (PageNumberPagination, **PAGE_SIZE 24**, `?page=N`). Filters: `category`, `brand`, `tag`, `collection` (slugs), `price_min`, `price_max`, `q` (naive icontains — real search is `/search/`), `ordering` ∈ `newest` (default) | `price_asc` | `price_desc` | `best_selling` (currently = newest until Plan-10 data wiring). Card row (after Task 2): `{name, slug, brand, is_featured, from_price, currency, image, hover_image, default_variant_id, default_sku, rating_avg, rating_count}`. `from_price` is a **string** ("4500.00") or null; `rating_avg` is a **string** ("4.50"); `image`/`hover_image` are **relative** `/media/...` URLs or null. Only sellable-in-country, priced products are returned ("hide until priced").
- `GET /products/<slug>/` — `{name, slug, brand:{name,slug,logo,description}|null, description (rich HTML), short_description, ingredients, directions, warnings, specs:[{label,value}], faqs:[{q,a}], seo_title, seo_description, variants:[...], images:[{url,alt,variant_id}], related:[card rows], rating_avg, rating_count}`. Variant (after Task 2): `{id, sku, name, option_values:{Size:"50ml"}, price:{amount, compare_at|null, currency, tax_rate, prices_include_tax}|null, in_stock, low_stock}`. 404 if not sellable in the request country. Backend caches all catalog GETs 60 s per (country, path, querystring).
- `GET /categories/` — unpaginated **tree** (active roots, nested `children`): `{name, slug, image, sort_order, children:[…]}`. **No description/SEO fields** (see flagged risk).
- `GET /brands/` — unpaginated `{name, slug, logo, description}`.
- `GET /collections/<slug>/` — `{name, slug, description, image}`. Products of a collection via `/products/?collection=<slug>`.
- `GET /search/` — paginated card rows. Params: `q` (trigram ≥ 3 chars), `category`, `brand`, `price_min/max`, `in_stock=1`, `sort` ∈ `price_asc|price_desc|newest` (note: **`sort`**, not `ordering`, and relevance is the default when `q` present). Throttle scope `search` = **30/min/IP**.
- `GET /search/suggest/?q=` — `[{name, slug}]` (≤ 6). Throttle `suggest` = **60/min/IP** → the BFF must forward the client IP (`X-Forwarded-For`), same pattern as the newsletter route.
- `GET /products/<slug>/reviews/` — public, unpaginated approved reviews `[{rating, title, body, author, created_at}]`. **Every approved review is a verified purchase by construction** (only verified purchasers can post) — the storefront shows the "Verified purchase" badge on all of them.
- Wishlist (authed, sku-based): `GET /me/wishlist/`, `POST /me/wishlist/` body `{sku}` (201/200), `DELETE /me/wishlist/<sku>/` (204).
- `POST /checkout/buy-now/` — **authed only**, body `{variant_id, quantity}` → express-cart JSON (same `Cart` shape, `kind: "express"`).
- `GET /me/addresses/` — authed; rows include `{id, label, line1, city_text, country_code, is_default_shipping, ...}` (used only for the delivery-line label).
- Media URLs are **relative** (`/media/catalog/products/x.png`) — absolutise against the API origin (Task 3 `mediaUrl()`), and `next/image` needs the `remotePatterns` entry from Task 3.

**Standing guardrails (do not break):**
- **No payments/checkout/shipping code.** The only checkout-adjacent thing allowed here is the Buy-Now proxy (D6) because the master Plan-13 spec names it. `/checkout` and `/cart` pages stay Plan-12 skeletons.
- **The browser never sees a JWT.** All authed calls go through Route Handlers / Server Components with `fetchWithAuth`. Never put a token in client code.
- **Money strings verbatim.** Display exactly what the API returns; `formatMoney` adds grouping/symbol only. JSON-LD `price` uses the API string as-is. Never compute, round, or convert money in the storefront.
- **Backend edits are limited to Tasks 1–2 exactly as written** (D1/D2). Nothing else — no view, model, url, or settings changes beyond those tasks.
- **Performance budget:** Lighthouse mobile ≥ 95 (SEO = 100) on `/`, a PLP, and a PDP. Everything below-the-fold heavy is lazy; `next/image` for every image; framer-motion only through the `LazyMotion` islands built in Task 5; no other animation/carousel/lightbox libraries.
- **WCAG AA:** semantic headings in order, visible focus, keyboard-reachable interactive islands, `aria-label`s, alt text everywhere, `prefers-reduced-motion` respected by every animation this plan adds.

**Commands:**
```bash
# storefront (from tokecosmetics-platform/storefront)
npm run test -- --run     # Vitest
npm run build             # must be clean
npm run dev               # dev on :3000
npm start                 # production server (used for verification — see Task 14)
npm run gen:api           # regenerate src/lib/api-types.ts (backend must be running)

# backend (from tokecosmetics-platform/backend, second terminal)
uv run python manage.py runserver 0.0.0.0:8000
uv run pytest -q                       # full backend suite
uv run python manage.py seed_dev_catalog   # after Task 1
```

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `backend/apps/catalog/management/commands/seed_dev_catalog.py` | idempotent dev catalog seed (products/prices/stock/reviews/images) | 1 |
| `backend/config/urls.py` | + DEBUG-only media serving (3 lines) | 1 |
| `backend/apps/catalog/tests/test_seed_dev_catalog.py` | seed command pytest | 1 |
| `backend/apps/catalog/api_serializers.py` | + additive fields (D2) | 2 |
| `backend/apps/catalog/api_views.py`, `apps/search/backends.py` | + `variants` prefetch for the new list fields | 2 |
| `backend/apps/catalog/tests/test_serializer_extras.py` | pytest for D2 fields | 2 |
| `storefront/src/lib/api-types.ts` | regenerated OpenAPI types | 2 |
| `storefront/next.config.ts` | image `remotePatterns` + SVG policy | 3 |
| `storefront/src/lib/media.ts` | absolutise `/media/...` URLs | 3 |
| `storefront/src/lib/catalog.ts` | typed catalog/search/review fetchers + query builder + category-tree helpers | 3 |
| `storefront/src/lib/country.ts` | + `symbolFor(currencyCode)` | 3 |
| `storefront/src/lib/seo.ts` | canonical/metadata factory + JSON-LD builders + `<JsonLd>` | 4 |
| `storefront/src/components/motion/Motion.tsx` | LazyMotion provider + `FadeUp` reveal island | 5 |
| `storefront/src/components/product/{ReviewStars,PriceTag,ProductCard,WishlistHeart}.tsx` | card primitives | 5 |
| `storefront/src/app/api/wishlist/[[...sku]]/route.ts` | wishlist BFF | 5 |
| `storefront/scripts/gen-placeholders.mjs` + `public/home/**` | generated homepage art (D4) | 6 |
| `storefront/src/lib/home-content.ts` | typed homepage editorial content (D3) | 6 |
| `storefront/src/components/home/*` (15 sections, split 6/7) | homepage sections | 6, 7 |
| `storefront/src/app/(shop)/page.tsx` | homepage assembly + metadata + Org/WebSite JSON-LD | 6, 7 |
| `storefront/src/components/layout/{AnnouncementBar,ScrollShrink}.tsx` | rotating bar + shrinking header | 6 |
| `storefront/src/components/plp/{ProductGrid,FiltersBar,SortSelect,Pagination}.tsx` | PLP engine | 8 |
| `storefront/src/app/(shop)/products/page.tsx` | all-products PLP | 8 |
| `storefront/src/app/(shop)/category/[slug]/page.tsx` + `components/plp/Breadcrumbs.tsx` | category PLP + BreadcrumbList | 9 |
| `storefront/src/app/(shop)/search/page.tsx` | search PLP (noindex) | 10 |
| `storefront/src/app/api/search/suggest/route.ts` + `components/layout/SearchBar.tsx` | autocomplete | 10 |
| `storefront/src/components/product/{ProductGallery,VariantPicker,QtySelector,PdpAccordions,BuyBox,PdpContext}.tsx` | PDP islands | 11, 12 |
| `storefront/src/app/(shop)/product/[slug]/page.tsx` | PDP assembly + metadata + Product/Breadcrumb/FAQ JSON-LD | 11 |
| `storefront/src/lib/delivery-estimates.ts` | per-country delivery copy (D5) | 11 |
| `storefront/src/lib/cart-ui.ts` | open-cart-drawer event bus | 12 |
| `storefront/src/app/api/checkout/buy-now/route.ts` | Buy-Now BFF (D6) | 12 |
| `storefront/src/components/product/{ReviewList,RelatedProducts,RecentlyViewed}.tsx` + `lib/recently-viewed.ts` | PDP below-the-fold | 12 |
| `storefront/src/app/api/revalidate/route.ts` | tag revalidation webhook target (D7) | 12 |
| `storefront/src/app/sitemap.ts`, `src/app/robots.ts` | sitemap + robots | 13 |
| `tokecosmetics-platform/docs/architecture.md` | § Catalog/SEO (canonical policy, hreflang omission, tags) | 13 |

**Task order is a dependency chain.** Seed data (1) → API fields + types (2) → fetch/media libs (3) → SEO lib (4) → card primitives + wishlist (5) → home 1 (6) → home 2 (7) → PLP engine (8) → category PLP (9) → search (10) → PDP buy box (11) → PDP actions + below-fold (12) → sitemap/robots/docs (13) → verification checkpoint (14).

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
cd tokecosmetics-platform
git checkout main
git status --short          # must be empty
git checkout -b plan-13-storefront-catalog-seo
```

---

### Task 1: Backend — seed a realistic dev catalog (`seed_dev_catalog`) + dev media serving

**Why:** 4 products with no stock/images/reviews cannot exercise a 15-section homepage, a filterable PLP, or a PDP — and Hammed cannot judge the design against a wireframe. This command is **seed-data only** (D1): it writes rows through the existing models/services, changes no schema, and is idempotent (safe to re-run). It also makes `/media/` reachable in dev (DEBUG-only), because Django's runserver does not serve uploaded media by default and the seeded images would otherwise 404.

**Gated on:** D1.

**Files:**
- Create: `backend/apps/catalog/management/__init__.py`, `backend/apps/catalog/management/commands/__init__.py`, `backend/apps/catalog/management/commands/seed_dev_catalog.py`
- Modify: `backend/config/urls.py` (append a DEBUG-only block)
- Test: `backend/apps/catalog/tests/test_seed_dev_catalog.py`

- [ ] **Step 1: Write the failing test**

`backend/apps/catalog/tests/test_seed_dev_catalog.py`:

```python
"""The seed command must produce a browsable catalog and be idempotent."""
import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.catalog.models import Collection, Product
from apps.core.models import Country
from apps.inventory.services import available_for_country
from apps.pricing.services import resolve_price


@pytest.mark.django_db
@override_settings(DEBUG=True)  # the command refuses to run outside DEBUG
class TestSeedDevCatalog:
    def _run(self):
        call_command("seed_dev_catalog", "--no-images")  # images skipped in tests (slow)

    def test_seeds_a_realistic_catalog(self):
        self._run()
        products = Product.objects.filter(status="active")
        assert products.count() >= 24

        ng = Country.objects.get(code="NG")
        gb = Country.objects.get(code="GB")
        us = Country.objects.get(code="US")
        ca = Country.objects.get(code="CA")

        priced_everywhere = 0
        with_stock = 0
        for p in products.prefetch_related("variants"):
            v = p.variants.filter(is_active=True).first()
            assert v is not None, f"{p.slug} has no variant"
            if all(resolve_price(v, c) is not None for c in (ng, gb, us, ca)):
                priced_everywhere += 1
            if available_for_country(v, ng) > 0:
                with_stock += 1
        assert priced_everywhere >= 24, "every seeded product is priced in all 4 currencies"
        assert with_stock >= 20, "most products in stock in NG"

        # Collections used by the homepage exist and are populated.
        for slug in ("best-sellers", "new-arrivals", "glow-naturally"):
            c = Collection.objects.get(slug=slug)
            assert c.products.count() >= 4, f"collection {slug} too small"

        # Reviews fed the denormalised rating.
        assert products.filter(rating_count__gt=0).count() >= 10

    def test_is_idempotent(self):
        self._run()
        first = Product.objects.count()
        self._run()
        assert Product.objects.count() == first

    @override_settings(DEBUG=False)
    def test_refuses_outside_debug(self):
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            call_command("seed_dev_catalog", "--no-images")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd tokecosmetics-platform/backend
uv run pytest apps/catalog/tests/test_seed_dev_catalog.py -q
```
Expected: FAIL — unknown command `seed_dev_catalog`.

- [ ] **Step 3: Implement the command**

Create the two empty `__init__.py` files, then `backend/apps/catalog/management/commands/seed_dev_catalog.py`. The data tables below are the actual seed content — adjust names/copy for tone if you must, but keep the counts, the 4-currency coverage, and the stock variety:

```python
"""Seed a realistic DEV catalog so the storefront (Plan-13) can be designed and
verified against real API responses. Seed data ONLY — no schema changes. Idempotent:
every object is get_or_create'd by slug/sku; re-running never duplicates.

DEV-ONLY: refuses to run when DEBUG is False (production backstop).
"""
import io
import random
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.catalog.models import (
    Brand, Category, Collection, Product, ProductImage, ProductVariant, Tag,
)
from apps.core.models import Country, Currency
from apps.inventory.models import StockItem, Warehouse
from apps.pricing.models import Price
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating

# --- palette for generated placeholder "product shots" (brand tones) ---
PALETTES = [
    ((251, 249, 245), (28, 122, 62)),    # cream -> forest green
    ((241, 234, 224), (201, 162, 39)),   # beige -> soft gold
    ((251, 249, 245), (140, 198, 63)),   # cream -> leaf
    ((241, 234, 224), (26, 26, 26)),     # beige -> ink
    ((251, 249, 245), (107, 104, 98)),   # cream -> warm grey
]

CATEGORIES = [  # (name, slug, children)
    ("Face", "face", ["Cleansers", "Serums", "Moisturisers"]),
    ("Body", "body", ["Body Butters", "Body Washes"]),
    ("Hair", "hair", []),
    ("Kids & Babies", "kids-babies", []),
    ("Men", "men", []),
]

TAGS = [  # skin concerns (homepage "shop by concern" grid + PLP ?tag= filter)
    ("Acne", "acne"), ("Hyperpigmentation", "hyperpigmentation"),
    ("Dry Skin", "dry-skin"), ("Oily Skin", "oily-skin"),
    ("Sensitive Skin", "sensitive-skin"), ("Eczema", "eczema"),
    ("Dark Spots", "dark-spots"), ("Uneven Tone", "uneven-tone"),
]

BRANDS = [
    ("Toke Naturals", "toke-naturals"), ("Shea Republic", "shea-republic"),
    ("Ajali Botanics", "ajali-botanics"), ("Lumiere Lagos", "lumiere-lagos"),
]

# (name, slug, brand, category, tags, sizes, (NGN, GBP, USD, CAD) base, on_sale, featured)
PRODUCTS = [
    ("Radiance Glow Serum", "radiance-glow-serum", "toke-naturals", "serums",
     ["hyperpigmentation", "dark-spots"], ["30ml", "50ml"],
     ("18500", "32.00", "39.00", "52.00"), True, True),
    ("Shea Whip Body Butter", "shea-whip-body-butter", "shea-republic", "body-butters",
     ["dry-skin"], ["200ml", "400ml"], ("9500", "16.50", "21.00", "27.00"), False, True),
    ("Gentle Oat Cleanser", "gentle-oat-cleanser", "toke-naturals", "cleansers",
     ["sensitive-skin"], ["150ml"], ("7200", "12.00", "15.00", "19.50"), False, True),
    ("Clear Skin Turmeric Bar", "clear-skin-turmeric-bar", "ajali-botanics", "cleansers",
     ["acne", "uneven-tone"], ["120g"], ("4500", "8.00", "10.00", "13.00"), True, False),
    ("Midnight Repair Cream", "midnight-repair-cream", "lumiere-lagos", "moisturisers",
     ["dry-skin", "uneven-tone"], ["50ml"], ("21500", "36.00", "44.00", "58.00"), False, True),
    ("Baby Soft Oil", "baby-soft-oil", "shea-republic", "kids-babies",
     ["sensitive-skin", "eczema"], ["100ml", "250ml"],
     ("6800", "11.50", "14.00", "18.00"), False, False),
    ("Vitamin C Brightening Toner", "vitamin-c-brightening-toner", "toke-naturals", "face",
     ["dark-spots", "hyperpigmentation"], ["200ml"],
     ("11200", "19.00", "24.00", "31.00"), True, True),
    ("Black Soap Deep Cleanse", "black-soap-deep-cleanse", "ajali-botanics", "body-washes",
     ["acne", "oily-skin"], ["250ml", "500ml"], ("5900", "10.00", "12.50", "16.00"), False, False),
    ("Cocoa Silk Hair Butter", "cocoa-silk-hair-butter", "shea-republic", "hair",
     [], ["150ml"], ("8400", "14.00", "17.50", "22.50"), False, False),
    ("Even Tone Night Mask", "even-tone-night-mask", "lumiere-lagos", "face",
     ["uneven-tone", "hyperpigmentation"], ["75ml"], ("16800", "28.00", "35.00", "46.00"), True, False),
    ("Calm Balm for Eczema", "calm-balm-eczema", "toke-naturals", "body",
     ["eczema", "sensitive-skin"], ["60ml"], ("9900", "17.00", "21.00", "27.50"), False, False),
    ("Papaya Enzyme Scrub", "papaya-enzyme-scrub", "ajali-botanics", "face",
     ["uneven-tone"], ["100ml"], ("7600", "13.00", "16.00", "21.00"), False, False),
    ("Hydra Dew Moisturiser", "hydra-dew-moisturiser", "toke-naturals", "moisturisers",
     ["dry-skin"], ["50ml", "100ml"], ("12800", "22.00", "27.00", "35.00"), False, True),
    ("Men's Beard + Face Oil", "mens-beard-face-oil", "lumiere-lagos", "men",
     ["dry-skin"], ["30ml"], ("10500", "18.00", "22.50", "29.00"), False, False),
    ("Charcoal Detox Wash", "charcoal-detox-wash", "ajali-botanics", "men",
     ["oily-skin", "acne"], ["200ml"], ("6900", "11.50", "14.50", "18.50"), True, False),
    ("Kids Curl Cream", "kids-curl-cream", "shea-republic", "kids-babies",
     [], ["150ml"], ("5500", "9.50", "12.00", "15.50"), False, False),
    ("Rosehip Recovery Oil", "rosehip-recovery-oil", "lumiere-lagos", "serums",
     ["dark-spots", "dry-skin"], ["30ml"], ("14500", "24.50", "30.00", "39.00"), False, False),
    ("Aloe Rescue Gel", "aloe-rescue-gel", "toke-naturals", "body",
     ["sensitive-skin"], ["120ml"], ("4900", "8.50", "10.50", "13.50"), False, False),
    ("Silk Press Shampoo", "silk-press-shampoo", "shea-republic", "hair",
     [], ["300ml"], ("7800", "13.50", "16.50", "21.50"), False, False),
    ("Glow Duo Face Kit", "glow-duo-face-kit", "toke-naturals", "face",
     ["hyperpigmentation"], ["Kit"], ("26500", "45.00", "55.00", "70.00"), True, True),
    ("Tea Tree Spot Serum", "tea-tree-spot-serum", "ajali-botanics", "serums",
     ["acne"], ["15ml"], ("8900", "15.00", "19.00", "24.50"), False, False),
    ("Mango Lip + Cheek Balm", "mango-lip-cheek-balm", "shea-republic", "face",
     [], ["20g"], ("4600", "8.00", "10.00", "12.80"), False, False),
    ("Overnight Hand Repair", "overnight-hand-repair", "lumiere-lagos", "body",
     ["dry-skin"], ["75ml"], ("7100", "12.00", "15.00", "19.00"), False, False),
    ("Balance Facial Mist", "balance-facial-mist", "toke-naturals", "face",
     ["oily-skin", "sensitive-skin"], ["100ml"], ("6300", "10.50", "13.00", "17.00"), False, False),
]

REVIEW_BODIES = [
    (5, "Absolute holy grail", "My hyperpigmentation faded within weeks. Texture is silk."),
    (5, "Worth every naira", "Smells divine and a little goes a very long way."),
    (4, "Really good", "Gentle on my sensitive skin, no purging. Wish the jar were bigger."),
    (5, "Family favourite", "I use it on the kids too — no reactions, just glow."),
    (4, "Impressed", "Two weeks in and my skin is noticeably more even."),
    (3, "Decent", "Does the job, though I prefer a lighter texture for daytime."),
    (5, "Repurchasing forever", "Third bottle. My skin has never looked better."),
]

REVIEWERS = [  # (email, first_name)
    ("amaka.dev@example.com", "Amaka"), ("tunde.dev@example.com", "Tunde"),
    ("zainab.dev@example.com", "Zainab"), ("chidi.dev@example.com", "Chidi"),
    ("funke.dev@example.com", "Funke"), ("emeka.dev@example.com", "Emeka"),
]


def _placeholder_png(size, c1, c2, seed):
    """Soft two-tone vertical gradient with an off-centre blurred highlight — a
    premium, deliberately abstract stand-in for product photography (D4)."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    img = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        row_color = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
        img.paste(row_color, (0, y, w, y + 1))
    rng = random.Random(seed)
    overlay = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(overlay)
    cx, cy = int(w * rng.uniform(0.3, 0.7)), int(h * rng.uniform(0.25, 0.5))
    r = int(min(w, h) * 0.45)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=70)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=r // 3))
    white = Image.new("RGB", (w, h), (255, 255, 255))
    img = Image.composite(white, img, overlay)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return ContentFile(buf.getvalue())


class Command(BaseCommand):
    help = "Seed a realistic DEV catalog (products, prices, stock, reviews, images)."

    def add_arguments(self, parser):
        parser.add_argument("--no-images", action="store_true",
                            help="Skip Pillow image generation (fast; used by tests).")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_dev_catalog is DEV-ONLY (requires DEBUG=True).")
        rng = random.Random(1313)
        countries = {c.code: c for c in Country.objects.all()}
        currencies = {c.code: c for c in Currency.objects.all()}

        # One warehouse serving every market (stock is country-scoped via warehouses).
        wh, _ = Warehouse.objects.get_or_create(
            name="Lagos Main (dev)",
            defaults={"location_country": "NG", "priority": 10},
        )
        wh.serves_countries.set(Country.objects.all())

        cats = {}
        for i, (name, slug, children) in enumerate(CATEGORIES):
            parent, _ = Category.objects.get_or_create(
                slug=slug, defaults={"name": name, "sort_order": i})
            cats[slug] = parent
            for j, child in enumerate(children):
                cslug = child.lower().replace(" ", "-")
                cats[cslug], _ = Category.objects.get_or_create(
                    slug=cslug, defaults={"name": child, "parent": parent, "sort_order": j})

        tags = {}
        for name, slug in TAGS:
            tags[slug], _ = Tag.objects.get_or_create(slug=slug, defaults={"name": name})
        brands = {}
        for name, slug in BRANDS:
            brands[slug], _ = Brand.objects.get_or_create(slug=slug, defaults={"name": name})

        from django.contrib.auth import get_user_model
        users = []
        for email, first in REVIEWERS:
            u, created = get_user_model().objects.get_or_create(
                email=email, defaults={"first_name": first})
            if created:
                u.set_unusable_password()
                u.save(update_fields=["password"])
            users.append(u)

        # Price scoping: NGN->NG, GBP->GB, CAD->CA; USD rows use country=None so BOTH
        # the US market and ZZ (rest-of-world, USD) resolve the same row.
        price_country = {"NGN": countries.get("NG"), "GBP": countries.get("GB"),
                         "USD": None, "CAD": countries.get("CA")}

        all_products = []
        for idx, (name, slug, brand, cat, tag_slugs, sizes, amounts, on_sale, featured) in enumerate(PRODUCTS):
            product, _created = Product.objects.get_or_create(
                slug=slug,
                defaults=dict(
                    name=name, brand=brands[brand], status="active", is_featured=featured,
                    short_description=f"{name} — small-batch, science-backed care for melanin-rich skin.",
                    description=(
                        f"<p><strong>{name}</strong> is formulated with cold-pressed African "
                        "botanicals and clinically proven actives. Dermatologist reviewed, "
                        "cruelty free, and made for melanin-rich skin.</p>"
                        "<p>Free of parabens, sulphates and mineral oil.</p>"),
                    ingredients="Aqua, Butyrospermum Parkii (Shea) Butter, Niacinamide, "
                                "Glycerin, Simmondsia Chinensis (Jojoba) Seed Oil, Tocopherol.",
                    directions="Apply to clean skin morning and evening. Massage gently until absorbed.",
                    warnings="External use only. Patch-test before first use. Discontinue if irritation occurs.",
                    specs=[{"label": "Skin type", "value": "All, incl. sensitive"},
                           {"label": "Origin", "value": "Made in Nigeria"},
                           {"label": "Cruelty free", "value": "Yes"}],
                    faqs=[{"q": "Is it safe for sensitive skin?",
                           "a": "Yes — it is fragrance-light, but do your own patch test first."},
                          {"q": "When will I see results?",
                           "a": "Most customers report visible changes within 2-4 weeks of consistent use."}],
                    published_at=timezone.now() - timezone.timedelta(days=len(PRODUCTS) - idx),
                ),
            )
            all_products.append(product)
            product.categories.add(cats[cat])
            if cats[cat].parent:
                product.categories.add(cats[cat].parent)
            for t in tag_slugs:
                product.tags.add(tags[t])

            for pos, size in enumerate(sizes):
                sku = f"TOKE-{slug[:18].upper().replace('-', '')}-{size.upper().replace('/', '')}"
                variant, _ = ProductVariant.objects.get_or_create(
                    sku=sku,
                    defaults=dict(product=product, name=size,
                                  option_values={"Size": size},
                                  weight_grams=150 + pos * 150,
                                  is_default=(pos == 0), position=pos),
                )
                mult = Decimal("1") if pos == 0 else Decimal("1.6")  # bigger size ~1.6x
                for code, base in zip(("NGN", "GBP", "USD", "CAD"), amounts):
                    amount = (Decimal(base) * mult).quantize(Decimal("0.01"))
                    Price.objects.get_or_create(
                        variant=variant, currency=currencies[code],
                        country=price_country[code], starts_at=None,
                        defaults=dict(
                            amount=amount,
                            compare_at_amount=(amount * Decimal("1.25")).quantize(Decimal("0.01"))
                            if on_sale else None,
                        ),
                    )
                # Stock variety: idx 7 out of stock; 3/10/17 low stock; rest healthy.
                if idx == 7:
                    qty = 0
                elif idx in (3, 10, 17):
                    qty = rng.randint(2, 4)
                else:
                    qty = rng.randint(25, 180)
                StockItem.objects.get_or_create(
                    variant=variant, warehouse=wh,
                    defaults={"quantity": qty, "reserved": 0})

            if not opts["no_images"] and not product.images.exists():
                c1, c2 = PALETTES[idx % len(PALETTES)]
                for pos in range(2):  # two images -> card hover-swap + gallery
                    img = ProductImage(product=product, position=pos,
                                       alt=f"{name} — {'packaging' if pos else 'product'} shot")
                    img.image.save(f"{slug}-{pos}.png",
                                   _placeholder_png((900, 1200), c1, c2, seed=idx * 10 + pos),
                                   save=True)

            # Reviews: ~70% of products get 1-4 approved reviews (deterministic spread).
            if idx % 10 != 9:
                for r in range(rng.randint(1, 4)):
                    rating, title, body = REVIEW_BODIES[(idx + r) % len(REVIEW_BODIES)]
                    Review.objects.get_or_create(
                        product=product, user=users[(idx + r) % len(users)],
                        defaults=dict(rating=rating, title=title, body=body,
                                      status="approved"),
                    )
                recompute_product_rating(product)

        if not opts["no_images"]:
            root_cats = [c for c in cats.values() if c.parent is None]
            for i, cat in enumerate(root_cats):
                if not cat.image:
                    c1, c2 = PALETTES[i % len(PALETTES)]
                    cat.image.save(f"{cat.slug}.png",
                                   _placeholder_png((800, 800), c1, c2, seed=100 + i),
                                   save=True)

        # Homepage collections.
        for cslug, cname, picks in (
            ("best-sellers", "Best Sellers", [p for p in all_products if p.is_featured]),
            ("new-arrivals", "New Arrivals", all_products[-8:]),
            ("glow-naturally", "Glow Naturally", all_products[0:6]),
        ):
            col, _ = Collection.objects.get_or_create(
                slug=cslug, defaults={"name": cname,
                                      "description": f"{cname} — curated by Toke."})
            col.products.set(picks)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(all_products)} products, "
            f"{ProductVariant.objects.count()} variants, "
            f"{Review.objects.count()} reviews."))
```

- [ ] **Step 4: Serve media in dev**

Append to the **end** of `backend/config/urls.py`:

```python
# DEV ONLY: serve uploaded media (seeded product/category images) from runserver.
# django.conf.urls.static.static() is a no-op when DEBUG is False, so this cannot
# change production behaviour. Prod media is served by the web server/CDN (Plan-22).
from django.conf import settings  # noqa: E402
from django.conf.urls.static import static  # noqa: E402

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest apps/catalog/tests/test_seed_dev_catalog.py -q
```
Expected: 3 passed. Note the command only **adds** rows (`get_or_create` everywhere) — the 4 pre-existing dev products are untouched.

- [ ] **Step 6: Run it for real + smoke the API**

```bash
uv run python manage.py seed_dev_catalog
uv run python manage.py runserver 0.0.0.0:8000
```
In another terminal:

```bash
curl -s "http://localhost:8000/api/v1/products/?page=1" -H "X-Country: NG" | head -c 600
curl -s "http://localhost:8000/api/v1/products/radiance-glow-serum/" -H "X-Country: GB" | head -c 600
```
Expected: `count` ≥ 24; the GB detail shows GBP prices with `compare_at` on sale items. Then open one returned `image` URL (e.g. `http://localhost:8000/media/catalog/products/radiance-glow-serum-0.png`) in a browser — it must render a gradient PNG, not 404.

- [ ] **Step 7: Full backend suite (regression gate)**

```bash
uv run pytest -q
```
Expected: green (new code only; the urls edit is DEBUG-gated).

- [ ] **Step 8: Commit**

```bash
git add backend/apps/catalog/management backend/apps/catalog/tests/test_seed_dev_catalog.py backend/config/urls.py
git commit -m "feat(backend): seed_dev_catalog command + DEBUG media serving (Plan-13 D1)

Idempotent dev-only seed: 24 products / 5 categories / brands / concern tags /
collections, prices in NGN+GBP+USD+CAD (some on sale), varied stock incl. low and
out-of-stock, approved reviews feeding rating_avg, Pillow gradient placeholder
imagery as real media. Zero schema changes.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Backend — additive catalog serializer fields (D2) + regenerate storefront API types

**Why:** verified blocking gap — the cart API takes `variant_id` (the pk, see `apps/carts/views.py:36`) but `VariantSerializer` exposes only `sku`, so a PDP built on today's API cannot add anything to the cart. While opening the serializer, add the other read-only display fields the master Plan-13 spec needs (hover second image on cards, low-stock message, default-variant identifiers for the wishlist heart, image→variant linkage for the gallery). **Strictly additive** — no existing field, filter, or behaviour changes; the whole backend suite must stay green.

**Gated on:** D2.

**Files:**
- Modify: `backend/apps/catalog/api_serializers.py`
- Modify: `backend/apps/catalog/api_views.py` (list queryset: prefetch `variants`)
- Modify: `backend/apps/search/backends.py` (same prefetch in `_base`)
- Test: `backend/apps/catalog/tests/test_serializer_extras.py`
- Regenerate: `storefront/src/lib/api-types.ts`

- [ ] **Step 1: Write the failing tests**

`backend/apps/catalog/tests/test_serializer_extras.py`. Before writing it, **read `apps/catalog/tests/test_product_api.py`** and copy its established setup pattern (how it builds an active product with variants, prices, warehouse and stock). Build a module-level pytest fixture `client_product` that returns `(product, v_low, v_ok)` where: the product is active with two active variants (`v_low` is `is_default=True` with stock qty 3; `v_ok` qty 50, both in a warehouse serving NG), both variants have an NGN price, and the product has two images. Then:

```python
"""Plan-13 D2: additive read-only serializer fields. Existing fields must be untouched."""
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
class TestVariantExtras:
    def test_detail_variant_exposes_id_and_low_stock(self, client_product):
        product, v_low, v_ok = client_product
        res = APIClient().get(f"/api/v1/products/{product.slug}/", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        variants = {v["sku"]: v for v in res.data["variants"]}
        assert variants[v_low.sku]["id"] == v_low.id
        assert variants[v_low.sku]["low_stock"] is True      # qty 3
        assert variants[v_ok.sku]["low_stock"] is False      # qty 50
        # regression: pre-existing fields still present
        assert {"sku", "name", "option_values", "price", "in_stock"} <= set(variants[v_ok.sku])

    def test_detail_images_expose_variant_id(self, client_product):
        product, _, _ = client_product
        res = APIClient().get(f"/api/v1/products/{product.slug}/", HTTP_X_COUNTRY="NG")
        assert all("variant_id" in i for i in res.data["images"])


@pytest.mark.django_db
class TestCardExtras:
    def test_list_exposes_default_variant_and_hover_image(self, client_product):
        product, v_low, _ = client_product
        res = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="NG")
        row = next(r for r in res.data["results"] if r["slug"] == product.slug)
        assert row["default_variant_id"] == v_low.id          # v_low is is_default
        assert row["default_sku"] == v_low.sku
        assert row["hover_image"] is not None and row["hover_image"] != row["image"]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/catalog/tests/test_serializer_extras.py -q
```
Expected: FAIL — `id`/`low_stock`/`default_variant_id`/`hover_image` missing from responses.

- [ ] **Step 3: Implement (additive only)**

In `backend/apps/catalog/api_serializers.py`:

```python
# module level, above VariantSerializer:
LOW_STOCK_MAX = 5  # "only a few left" threshold shown on the storefront PDP
```

`VariantSerializer` — add the declared field, extend `Meta.fields`, add the method:

```python
class VariantSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    low_stock = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ["id", "sku", "name", "option_values", "price", "in_stock", "low_stock"]

    # ... get_price / get_in_stock unchanged ...

    def get_low_stock(self, obj):
        from apps.inventory.services import available_for_country

        available = available_for_country(obj, self.context["request"].country)
        return 0 < available <= LOW_STOCK_MAX
```

`ProductListSerializer` — extend `Meta.fields` and add:

```python
    class Meta:
        model = Product
        fields = ["name", "slug", "brand", "is_featured", "from_price", "currency",
                  "image", "hover_image", "default_variant_id", "default_sku",
                  "rating_avg", "rating_count"]

    hover_image = serializers.SerializerMethodField()
    default_variant_id = serializers.SerializerMethodField()
    default_sku = serializers.SerializerMethodField()

    def _default_variant(self, obj):
        variants = [v for v in obj.variants.all() if v.is_active]
        if not variants:
            return None
        return next((v for v in variants if v.is_default), variants[0])

    def get_default_variant_id(self, obj):
        v = self._default_variant(obj)
        return v.id if v else None

    def get_default_sku(self, obj):
        v = self._default_variant(obj)
        return v.sku if v else None

    def get_hover_image(self, obj):
        imgs = list(obj.images.all()[:2])
        return imgs[1].image.url if len(imgs) > 1 else None
```

`ProductDetailSerializer.get_images` becomes:

```python
    def get_images(self, obj):
        return [{"url": i.image.url, "alt": i.alt, "variant_id": i.variant_id}
                for i in obj.images.all()]
```

In `backend/apps/catalog/api_views.py` `ProductListView.get_queryset`, extend the prefetch so `_default_variant` does not N+1:

```python
            .prefetch_related("images", "variants")
```

Same one-word addition in `backend/apps/search/backends.py` `PostgresSearchBackend._base`.

- [ ] **Step 4: Run the new tests, then the FULL backend suite**

```bash
uv run pytest apps/catalog/tests/test_serializer_extras.py -q
uv run pytest -q
```
Expected: new tests pass; full suite green. **Watch `apps/catalog/tests/test_query_budget.py`** — the extra `variants` prefetch adds exactly one query to the list endpoint; if that test asserts an exact count, raise it by one **with a comment naming Plan-13 D2** (the only permitted edit to an existing test).

- [ ] **Step 5: Mutation-verify**

Change `get_low_stock` to `return False`. Confirm `test_detail_variant_exposes_id_and_low_stock` goes RED. Revert.

- [ ] **Step 6: Regenerate the storefront API types**

With the backend running:

```bash
cd ../storefront
npm run gen:api
```
Expected: `storefront/src/lib/api-types.ts` updates (now contains `low_stock`, `hover_image`).

- [ ] **Step 7: Commit**

```bash
git add backend/apps/catalog/api_serializers.py backend/apps/catalog/api_views.py backend/apps/search/backends.py backend/apps/catalog/tests/test_serializer_extras.py backend/apps/catalog/tests/test_query_budget.py storefront/src/lib/api-types.ts
git commit -m "feat(backend): additive catalog fields for the storefront (Plan-13 D2)

Variant id (unblocks PDP add-to-cart) + low_stock; card hover_image +
default_variant_id/default_sku; image variant_id. Read-only, additive, no
behaviour change; storefront api-types regenerated.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Storefront libs — catalog fetchers, media helper, currency symbols, image config, framer-motion install

**Why:** every page in this plan needs typed fetchers with consistent cache tags, absolute media URLs, and currency symbols for `formatMoney`. Define them once, unit-tested, before any page exists. Also do the one-time config: `next/image` must be allowed to load backend media, and framer-motion must be installed (used from Task 5 onward).

**Files:**
- Modify: `storefront/package.json` (framer-motion), `storefront/next.config.ts`
- Modify: `storefront/src/lib/country.ts` (add `symbolFor`)
- Create: `storefront/src/lib/media.ts`, `storefront/src/lib/catalog.ts`
- Test: `storefront/src/lib/__tests__/media.test.ts`, `storefront/src/lib/__tests__/catalog.test.ts`, extend `storefront/src/lib/__tests__/country.test.ts`

- [ ] **Step 1: Install framer-motion + configure images**

```bash
cd tokecosmetics-platform/storefront
npm install framer-motion@^12
```

Replace `storefront/next.config.ts` (verify option names against `node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/images.md`):

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Backend media (seeded product/category images) in dev. Plan-22 adds the
    // production media host here.
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000", pathname: "/media/**" },
    ],
    // Local, self-authored SVG art only (public/home/**, generated by
    // scripts/gen-placeholders.mjs). NEVER feed user-supplied or remote SVGs
    // through the optimizer — the CSP sandbox below is the backstop.
    dangerouslyAllowSVG: true,
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },
};

export default nextConfig;
```

- [ ] **Step 2: Write the failing tests**

`storefront/src/lib/__tests__/media.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { mediaUrl } from "@/lib/media";

describe("mediaUrl", () => {
  beforeEach(() => { process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000"; });

  it("absolutises relative /media paths against the API origin", () => {
    expect(mediaUrl("/media/catalog/products/x.png"))
      .toBe("http://localhost:8000/media/catalog/products/x.png");
  });
  it("passes through absolute URLs", () => {
    expect(mediaUrl("https://cdn.example.com/x.png")).toBe("https://cdn.example.com/x.png");
  });
  it("returns null for null/empty", () => {
    expect(mediaUrl(null)).toBeNull();
    expect(mediaUrl("")).toBeNull();
  });
});
```

`storefront/src/lib/__tests__/catalog.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildProductQuery, findCategory, flattenCategories, type CategoryNode } from "@/lib/catalog";

const TREE: CategoryNode[] = [
  { name: "Face", slug: "face", image: null, sort_order: 0, children: [
    { name: "Serums", slug: "serums", image: null, sort_order: 0, children: [] },
  ]},
  { name: "Body", slug: "body", image: null, sort_order: 1, children: [] },
];

describe("buildProductQuery", () => {
  it("serialises only known, present params in a stable order", () => {
    expect(buildProductQuery({ category: "face", ordering: "price_asc", page: 2 }))
      .toBe("category=face&ordering=price_asc&page=2");
  });
  it("omits page 1 and empty values", () => {
    expect(buildProductQuery({ page: 1, brand: "" })).toBe("");
  });
  it("ignores unknown keys (URL params are user input)", () => {
    // @ts-expect-error — deliberately passing junk
    expect(buildProductQuery({ evil: "1;drop" })).toBe("");
  });
});

describe("category tree helpers", () => {
  it("finds a nested node with its ancestor chain", () => {
    const hit = findCategory(TREE, "serums");
    expect(hit?.node.name).toBe("Serums");
    expect(hit?.ancestors.map((a) => a.slug)).toEqual(["face"]);
  });
  it("returns null for a miss", () => {
    expect(findCategory(TREE, "nope")).toBeNull();
  });
  it("flattens the tree depth-first", () => {
    expect(flattenCategories(TREE).map((c) => c.slug)).toEqual(["face", "serums", "body"]);
  });
});
```

Append to `storefront/src/lib/__tests__/country.test.ts`:

```ts
import { symbolFor } from "@/lib/country";

describe("symbolFor", () => {
  it("maps the four live currencies and falls back to the code", () => {
    expect(symbolFor("NGN")).toBe("₦");
    expect(symbolFor("GBP")).toBe("£");
    expect(symbolFor("USD")).toBe("$");
    expect(symbolFor("CAD")).toBe("CA$");
    expect(symbolFor("EUR")).toBe("EUR ");
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/media.test.ts src/lib/__tests__/catalog.test.ts src/lib/__tests__/country.test.ts
```
Expected: FAIL — modules/exports missing.

- [ ] **Step 4: Implement**

Append to `storefront/src/lib/country.ts`:

```ts
/** Display symbols for the live currencies. Server truth is /meta/countries/ —
 * this map only saves a fetch where just the symbol is needed on a card. */
const CURRENCY_SYMBOLS: Record<string, string> = {
  NGN: "₦", GBP: "£", USD: "$", CAD: "CA$",
};

export function symbolFor(currencyCode: string): string {
  return CURRENCY_SYMBOLS[currencyCode] ?? `${currencyCode} `;
}
```

`storefront/src/lib/media.ts`:

```ts
/** Backend media URLs come back relative ("/media/..."). Absolutise against the
 * API origin so next/image and Open Graph tags work. NEXT_PUBLIC_API_URL is used
 * (not API_URL) because the value is embedded in HTML sent to the browser. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}
```

`storefront/src/lib/catalog.ts`:

```ts
/** Typed, tagged catalog/search/review fetchers. Server-side only (uses apiFetch).
 * Cache strategy: pages render dynamically (they read the country cookie), so
 * caching lives in the fetch data-cache — short revalidate + tags, invalidated by
 * POST /api/revalidate (Task 12). Backend also caches catalog GETs for 60 s. */
import { apiFetch } from "@/lib/api";

// ---------- types (mirror backend serializers; regenerate api-types for drift) ----------
export interface ProductCard {
  name: string; slug: string;
  brand: string | null;           // the brand SLUG (SlugRelatedField), not the name
  is_featured: boolean;
  from_price: string | null;      // money string — display verbatim
  currency: string;
  image: string | null; hover_image: string | null;   // relative /media URLs
  default_variant_id: number | null; default_sku: string | null;
  rating_avg: string;             // "4.50"
  rating_count: number;
}
export interface Paginated<T> {
  count: number; next: string | null; previous: string | null; results: T[];
}
export interface VariantPrice {
  amount: string; compare_at: string | null; currency: string;
  tax_rate: string; prices_include_tax: boolean;
}
export interface Variant {
  id: number; sku: string; name: string;
  option_values: Record<string, string>;
  price: VariantPrice | null; in_stock: boolean; low_stock: boolean;
}
export interface ProductDetail {
  name: string; slug: string;
  brand: { name: string; slug: string; logo: string | null; description: string } | null;
  description: string; short_description: string;
  ingredients: string; directions: string; warnings: string;
  specs: { label: string; value: string }[];
  faqs: { q: string; a: string }[];
  seo_title: string; seo_description: string;
  variants: Variant[];
  images: { url: string; alt: string; variant_id: number | null }[];
  related: ProductCard[];
  rating_avg: string; rating_count: number;
}
export interface CategoryNode {
  name: string; slug: string; image: string | null; sort_order: number;
  children: CategoryNode[];
}
export interface BrandRow { name: string; slug: string; logo: string | null; description: string }
export interface CollectionRow { name: string; slug: string; description: string; image: string | null }
export interface ReviewRow { rating: number; title: string; body: string; author: string; created_at: string }

// ---------- product list query builder (URL params are untrusted input) ----------
export interface ProductListParams {
  category?: string; brand?: string; tag?: string; collection?: string;
  price_min?: string; price_max?: string;
  ordering?: "newest" | "price_asc" | "price_desc" | "best_selling";
  page?: number;
}
const LIST_KEYS: (keyof ProductListParams)[] = [
  "category", "brand", "tag", "collection", "price_min", "price_max", "ordering", "page",
];

export function buildProductQuery(params: ProductListParams): string {
  const qs = new URLSearchParams();
  for (const key of LIST_KEYS) {
    const v = params[key];
    if (v === undefined || v === "" || (key === "page" && Number(v) <= 1)) continue;
    qs.set(key, String(v));
  }
  return qs.toString();
}

// ---------- fetchers ----------
const CATALOG_REVALIDATE = 60; // matches the backend's own catalog cache TTL

export async function getProducts(params: ProductListParams, country: string) {
  const q = buildProductQuery(params);
  return apiFetch<Paginated<ProductCard>>(`/products/${q ? `?${q}` : ""}`, {
    country, next: { revalidate: CATALOG_REVALIDATE, tags: ["catalog"] },
  });
}

export async function getProduct(slug: string, country: string) {
  return apiFetch<ProductDetail>(`/products/${slug}/`, {
    country, next: { revalidate: CATALOG_REVALIDATE, tags: ["catalog", `product:${slug}`] },
  });
}

export async function getCategoryTree(country: string) {
  return apiFetch<CategoryNode[]>("/categories/", {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export async function getBrands(country: string) {
  return apiFetch<BrandRow[]>("/brands/", {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export async function getCollection(slug: string, country: string) {
  return apiFetch<CollectionRow>(`/collections/${slug}/`, {
    country, next: { revalidate: 3600, tags: ["catalog"] },
  });
}

export interface SearchParams {
  q?: string; category?: string; brand?: string;
  price_min?: string; price_max?: string; in_stock?: "1";
  sort?: "price_asc" | "price_desc" | "newest"; page?: number;
}
export async function searchProducts(params: SearchParams, country: string) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || (k === "page" && Number(v) <= 1)) continue;
    qs.set(k, String(v));
  }
  // /search/ is throttled 30/min/IP — server-side calls only, never poll it.
  return apiFetch<Paginated<ProductCard>>(`/search/?${qs.toString()}`, {
    country, cache: "no-store",
  });
}

export async function getReviews(slug: string) {
  return apiFetch<ReviewRow[]>(`/products/${slug}/reviews/`, {
    next: { revalidate: 300, tags: [`product:${slug}`] },
  });
}

// ---------- category tree helpers ----------
export function findCategory(
  tree: CategoryNode[], slug: string, ancestors: CategoryNode[] = [],
): { node: CategoryNode; ancestors: CategoryNode[] } | null {
  for (const node of tree) {
    if (node.slug === slug) return { node, ancestors };
    const hit = findCategory(node.children, slug, [...ancestors, node]);
    if (hit) return hit;
  }
  return null;
}

export function flattenCategories(tree: CategoryNode[]): CategoryNode[] {
  return tree.flatMap((n) => [n, ...flattenCategories(n.children)]);
}
```

- [ ] **Step 5: Run tests**

```bash
npm run test -- --run src/lib/__tests__
```
Expected: PASS (all lib suites incl. the Plan-12 ones).

- [ ] **Step 6: Mutation-verify**

In `buildProductQuery`, remove the `key === "page" && Number(v) <= 1` guard. Confirm the "omits page 1" test goes RED. Revert.

- [ ] **Step 7: Build gate + commit**

```bash
npm run build
git add package.json package-lock.json next.config.ts src/lib/media.ts src/lib/catalog.ts src/lib/country.ts src/lib/__tests__/media.test.ts src/lib/__tests__/catalog.test.ts src/lib/__tests__/country.test.ts
git commit -m "feat(storefront): catalog fetchers with cache tags, media/symbol helpers, image config

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: SEO library (`lib/seo.ts`) — canonical policy, metadata factory, JSON-LD builders

**Why:** the "100% SEO perfect" requirement lives in exactly one module so every page agrees on canonical rules, title templates, OG images, and JSON-LD shapes. Pure functions → fully unit-tested. Canonical policy (documented in Task 13): **a PLP URL's canonical strips every query param except `page` (kept when > 1); when any filter/sort param is present, the canonical is the bare base path** — filtered variants consolidate onto the category page. JSON-LD money uses API strings verbatim.

**Files:**
- Create: `storefront/src/lib/seo.ts`, `storefront/src/components/seo/JsonLd.tsx`
- Test: `storefront/src/lib/__tests__/seo.test.ts`

- [ ] **Step 1: Write the failing tests**

`storefront/src/lib/__tests__/seo.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import {
  absoluteUrl, canonicalFor, pageMetadata,
  organizationJsonLd, webSiteJsonLd, breadcrumbJsonLd, productJsonLd, faqJsonLd,
} from "@/lib/seo";
import type { ProductDetail } from "@/lib/catalog";

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = "https://tokecosmetics.com";
  process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
});

describe("absoluteUrl / canonicalFor", () => {
  it("builds absolute URLs from the site origin", () => {
    expect(absoluteUrl("/products")).toBe("https://tokecosmetics.com/products");
  });
  it("keeps page>1, strips page=1", () => {
    expect(canonicalFor("/products", { page: "2" })).toBe("https://tokecosmetics.com/products?page=2");
    expect(canonicalFor("/products", { page: "1" })).toBe("https://tokecosmetics.com/products");
  });
  it("filtered PLPs canonicalise to the bare base path (master spec)", () => {
    expect(canonicalFor("/category/face", { brand: "toke-naturals", page: "3" }))
      .toBe("https://tokecosmetics.com/category/face");
  });
});

describe("pageMetadata", () => {
  it("sets title, description, canonical, OG and twitter", () => {
    const md = pageMetadata({
      title: "Face", description: "Face care.", path: "/category/face",
      image: "http://localhost:8000/media/catalog/categories/face.png",
    });
    expect(md.title).toBe("Face");
    expect(md.alternates?.canonical).toBe("https://tokecosmetics.com/category/face");
    expect(md.openGraph?.images).toEqual(["http://localhost:8000/media/catalog/categories/face.png"]);
    expect(md.twitter).toMatchObject({ card: "summary_large_image" });
  });
  it("noindex sets robots", () => {
    const md = pageMetadata({ title: "Search", description: "d", path: "/search", noindex: true });
    expect(md.robots).toMatchObject({ index: false, follow: true });
  });
});

describe("JSON-LD builders", () => {
  it("Organization + WebSite/SearchAction", () => {
    expect(organizationJsonLd()).toMatchObject({
      "@type": "Organization", url: "https://tokecosmetics.com",
    });
    const site = webSiteJsonLd();
    expect(site.potentialAction.target).toContain("/search?q={search_term_string}");
  });

  it("BreadcrumbList positions items from 1", () => {
    const ld = breadcrumbJsonLd([
      { name: "Home", path: "/" }, { name: "Face", path: "/category/face" },
    ]);
    expect(ld.itemListElement[1]).toMatchObject({
      position: 2, name: "Face", item: "https://tokecosmetics.com/category/face",
    });
  });

  it("Product uses AggregateOffer across priced variants, money verbatim", () => {
    const product = {
      name: "Serum", slug: "serum", short_description: "Glow.",
      brand: { name: "Toke Naturals", slug: "toke-naturals", logo: null, description: "" },
      rating_avg: "4.50", rating_count: 3,
      images: [{ url: "/media/p/serum-0.png", alt: "", variant_id: null }],
      variants: [
        { id: 1, sku: "A", name: "30ml", option_values: {}, in_stock: true, low_stock: false,
          price: { amount: "18500.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } },
        { id: 2, sku: "B", name: "50ml", option_values: {}, in_stock: false, low_stock: false,
          price: { amount: "29600.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } },
      ],
    } as unknown as ProductDetail;
    const ld = productJsonLd(product, "/product/serum");
    expect(ld.offers).toMatchObject({
      "@type": "AggregateOffer", lowPrice: "18500.00", highPrice: "29600.00",
      priceCurrency: "NGN", offerCount: 2,
    });
    expect(ld.aggregateRating).toMatchObject({ ratingValue: "4.50", reviewCount: 3 });
    expect(ld.image[0]).toBe("http://localhost:8000/media/p/serum-0.png");
  });

  it("Product omits aggregateRating when no reviews and uses a single Offer for one variant", () => {
    const product = {
      name: "Balm", slug: "balm", short_description: "Calm.", brand: null,
      rating_avg: "0.00", rating_count: 0, images: [],
      variants: [{ id: 1, sku: "A", name: "60ml", option_values: {}, in_stock: true, low_stock: false,
        price: { amount: "9900.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } }],
    } as unknown as ProductDetail;
    const ld = productJsonLd(product, "/product/balm");
    expect(ld.aggregateRating).toBeUndefined();
    expect(ld.offers).toMatchObject({ "@type": "Offer", price: "9900.00",
      availability: "https://schema.org/InStock" });
  });

  it("FAQPage maps q/a pairs", () => {
    const ld = faqJsonLd([{ q: "Safe?", a: "Yes." }]);
    expect(ld.mainEntity[0]).toMatchObject({
      "@type": "Question", name: "Safe?",
      acceptedAnswer: { "@type": "Answer", text: "Yes." },
    });
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/seo.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `lib/seo.ts`**

```ts
/** The single source of SEO truth: canonical policy, generateMetadata factory,
 * JSON-LD builders. Every page imports from here — no page hand-rolls metadata.
 * Money in JSON-LD is the API string verbatim (never recomputed). */
import type { Metadata } from "next";
import { mediaUrl } from "@/lib/media";
import type { ProductDetail } from "@/lib/catalog";

export const SITE_NAME = "Toke Cosmetics";
export const TITLE_TEMPLATE = `%s | ${SITE_NAME}`;
export const DEFAULT_DESCRIPTION =
  "Premium skincare for melanin-rich skin — natural ingredients, science-backed, shipped from Nigeria worldwide.";

export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");
}
export function absoluteUrl(path: string): string {
  return `${siteUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Canonical policy (docs/architecture.md § Plan-13): keep ONLY `page` (when >1);
 * any other param present → canonical is the bare base path (filtered PLP variants
 * consolidate onto the category/listing base). */
export function canonicalFor(
  path: string, searchParams: Record<string, string | undefined> = {},
): string {
  const entries = Object.entries(searchParams).filter(([, v]) => v !== undefined && v !== "");
  const nonPage = entries.filter(([k]) => k !== "page");
  if (nonPage.length > 0) return absoluteUrl(path);
  const page = Number(searchParams.page ?? "1");
  return page > 1 ? `${absoluteUrl(path)}?page=${page}` : absoluteUrl(path);
}

export interface PageMeta {
  title: string; description: string; path: string;
  searchParams?: Record<string, string | undefined>;
  image?: string | null; noindex?: boolean;
}

export function pageMetadata(meta: PageMeta): Metadata {
  const canonical = canonicalFor(meta.path, meta.searchParams);
  return {
    title: meta.title,
    description: meta.description,
    alternates: { canonical },
    openGraph: {
      title: meta.title, description: meta.description, url: canonical,
      siteName: SITE_NAME, type: "website",
      ...(meta.image ? { images: [meta.image] } : {}),
    },
    twitter: {
      card: "summary_large_image", title: meta.title, description: meta.description,
      ...(meta.image ? { images: [meta.image] } : {}),
    },
    ...(meta.noindex ? { robots: { index: false, follow: true } } : {}),
  };
}

// ---------------- JSON-LD ----------------
/* eslint-disable @typescript-eslint/no-explicit-any */

export function organizationJsonLd(): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE_NAME,
    url: siteUrl(),
    logo: absoluteUrl("/logos/toke-logo.png"),
    sameAs: [
      "https://www.instagram.com/tokecosmetics",
      "https://www.facebook.com/tokecosmetics",
    ],
  };
}

export function webSiteJsonLd(): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: siteUrl(),
    potentialAction: {
      "@type": "SearchAction",
      target: `${siteUrl()}/search?q={search_term_string}`,
      "query-input": "required name=search_term_string",
    },
  };
}

export function breadcrumbJsonLd(
  crumbs: { name: string; path: string }[],
): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem", position: i + 1, name: c.name, item: absoluteUrl(c.path),
    })),
  };
}

const AVAILABILITY = {
  in: "https://schema.org/InStock",
  out: "https://schema.org/OutOfStock",
};

export function productJsonLd(product: ProductDetail, path: string): Record<string, any> {
  const url = absoluteUrl(path);
  const priced = product.variants.filter((v) => v.price !== null);
  const anyInStock = priced.some((v) => v.in_stock);
  const currency = priced[0]?.price?.currency;

  let offers: Record<string, any> | undefined;
  if (priced.length === 1) {
    offers = {
      "@type": "Offer", url, price: priced[0].price!.amount, priceCurrency: currency,
      availability: priced[0].in_stock ? AVAILABILITY.in : AVAILABILITY.out,
    };
  } else if (priced.length > 1) {
    // Compare as numbers to pick low/high, but EMIT the original API strings.
    const sorted = [...priced].sort((a, b) => Number(a.price!.amount) - Number(b.price!.amount));
    offers = {
      "@type": "AggregateOffer", url,
      lowPrice: sorted[0].price!.amount,
      highPrice: sorted[sorted.length - 1].price!.amount,
      priceCurrency: currency, offerCount: priced.length,
      availability: anyInStock ? AVAILABILITY.in : AVAILABILITY.out,
    };
  }
  // priceValidUntil deliberately omitted — the API does not expose sale windows
  // (Plan-13 flagged risk); the property is optional.

  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.name,
    url,
    description: product.short_description || product.seo_description || undefined,
    image: product.images.map((i) => mediaUrl(i.url)).filter(Boolean),
    ...(product.brand ? { brand: { "@type": "Brand", name: product.brand.name } } : {}),
    sku: product.variants[0]?.sku,
    ...(offers ? { offers } : {}),
    ...(product.rating_count > 0
      ? { aggregateRating: {
          "@type": "AggregateRating",
          ratingValue: product.rating_avg, reviewCount: product.rating_count,
        } }
      : {}),
  };
}

export function faqJsonLd(faqs: { q: string; a: string }[]): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question", name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
}
```

`storefront/src/components/seo/JsonLd.tsx`:

```tsx
/** Server component: emits one JSON-LD script tag. `<` is escaped so payload
 * content can never close the script tag (XSS hardening for API-sourced text). */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/lib/__tests__/seo.test.ts
```
Expected: PASS.

- [ ] **Step 5: Mutation-verify**

In `canonicalFor`, change `if (nonPage.length > 0) return absoluteUrl(path);` to always keep the query string. Confirm the "filtered PLPs canonicalise" test goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add src/lib/seo.ts src/components/seo/JsonLd.tsx src/lib/__tests__/seo.test.ts
git commit -m "feat(storefront): SEO library — canonical policy, metadata factory, JSON-LD builders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Product primitives — stars, price tag, ProductCard (hover swap + wishlist heart), motion islands, wishlist BFF

**Why:** the same card renders on home rows, PLPs, search, related and recently-viewed — build it once. The wishlist heart needs an authed BFF proxy (sku-based backend API). Motion primitives (`LazyMotion` + `FadeUp`) are created here and reused by every later task; they are the ONLY sanctioned way to use framer-motion in this plan.

**Files:**
- Create: `storefront/src/components/motion/Motion.tsx`
- Create: `storefront/src/components/product/ReviewStars.tsx`, `PriceTag.tsx`, `WishlistHeart.tsx`, `ProductCard.tsx`
- Create: `storefront/src/app/api/wishlist/[[...sku]]/route.ts`
- Test: `storefront/src/app/api/wishlist/__tests__/route.test.ts`, `storefront/src/components/product/__tests__/PriceTag.test.tsx`

- [ ] **Step 1: Motion primitives**

`storefront/src/components/motion/Motion.tsx`:

```tsx
"use client";
/** The ONLY entry point for framer-motion in the storefront. LazyMotion +
 * domAnimation keeps the animation bundle small (Lighthouse budget); every
 * effect respects prefers-reduced-motion. Vocabulary (design-direction.md):
 * fade-up on scroll, subtle hover lift/zoom — calm and expensive, never busy. */
import { LazyMotion, domAnimation, m, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

export function MotionRoot({ children }: { children: ReactNode }) {
  return <LazyMotion features={domAnimation} strict>{children}</LazyMotion>;
}

export function FadeUp({
  children, delay = 0, className,
}: { children: ReactNode; delay?: number; className?: string }) {
  const reduced = useReducedMotion();
  if (reduced) return <div className={className}>{children}</div>;
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.55, delay, ease: [0.21, 0.61, 0.35, 1] }}
    >
      {children}
    </m.div>
  );
}
```

Mount `MotionRoot` once: in `storefront/src/components/providers.tsx`, wrap the existing children (inside the QueryClientProvider) with `<MotionRoot>…</MotionRoot>`.

- [ ] **Step 2: Write the failing PriceTag test**

`storefront/src/components/product/__tests__/PriceTag.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceTag } from "@/components/product/PriceTag";

describe("PriceTag", () => {
  it("renders the API amount verbatim with symbol + grouping", () => {
    render(<PriceTag amount="18500.00" currency="NGN" />);
    expect(screen.getByText("₦18,500.00")).toBeInTheDocument();
  });
  it("shows compare-at as struck-through with an accessible name", () => {
    render(<PriceTag amount="18500.00" compareAt="23125.00" currency="NGN" />);
    const was = screen.getByText("₦23,125.00");
    expect(was.tagName).toBe("S");
    expect(screen.getByText(/was/i)).toBeInTheDocument(); // sr-only prefix
  });
  it("renders a from-prefix when asked", () => {
    render(<PriceTag amount="9.50" currency="GBP" from />);
    expect(screen.getByText(/from/i)).toBeInTheDocument();
    expect(screen.getByText("£9.50")).toBeInTheDocument();
  });
});
```

Run: `npm run test -- --run src/components/product/__tests__/PriceTag.test.tsx` — expected FAIL.

- [ ] **Step 3: Implement the primitives**

`storefront/src/components/product/PriceTag.tsx` (server component):

```tsx
import { formatMoney, symbolFor } from "@/lib/country";

/** Money display. NEVER computes or rounds — formats the API strings only. */
export function PriceTag({
  amount, compareAt, currency, from = false, size = "md",
}: {
  amount: string; compareAt?: string | null; currency: string;
  from?: boolean; size?: "md" | "lg";
}) {
  const symbol = symbolFor(currency);
  return (
    <p className={size === "lg" ? "text-2xl font-medium" : "text-sm font-medium"}>
      {from && <span className="mr-1 text-muted font-normal">from</span>}
      <span>{formatMoney(amount, currency, symbol)}</span>
      {compareAt && (
        <>
          {" "}
          <span className="sr-only">was</span>
          <s className="ml-2 text-muted font-normal">{formatMoney(compareAt, currency, symbol)}</s>
        </>
      )}
    </p>
  );
}
```

`storefront/src/components/product/ReviewStars.tsx` (server component):

```tsx
/** Gold stars (design token --color-gold). rating is the API string ("4.50"). */
export function ReviewStars({ rating, count, showCount = true }: {
  rating: string; count: number; showCount?: boolean;
}) {
  const value = Number(rating);
  if (count === 0) return null;
  return (
    <span className="inline-flex items-center gap-1 text-sm"
      aria-label={`Rated ${rating} out of 5 from ${count} reviews`}>
      <span aria-hidden className="tracking-tight text-gold">
        {[1, 2, 3, 4, 5].map((i) => (i <= Math.round(value) ? "★" : "☆")).join("")}
      </span>
      {showCount && <span className="text-muted">({count})</span>}
    </span>
  );
}
```

`storefront/src/components/product/WishlistHeart.tsx` (client island):

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

/** Heart toggle. Optimistic; a 401 from the BFF sends the visitor to /login.
 * sku is the default-variant sku (backend wishlist is sku-keyed). */
export function WishlistHeart({ sku, name }: { sku: string | null; name: string }) {
  const [saved, setSaved] = useState(false);
  const router = useRouter();
  if (!sku) return null;

  async function toggle(e: React.MouseEvent) {
    e.preventDefault(); // the heart sits inside the card <Link>
    const next = !saved;
    setSaved(next);
    const res = next
      ? await fetch("/api/wishlist", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ sku }),
        })
      : await fetch(`/api/wishlist/${encodeURIComponent(sku)}`, { method: "DELETE" });
    if (res.status === 401) { setSaved(false); router.push("/login"); }
    else if (!res.ok) setSaved(!next);
  }

  return (
    <button
      onClick={toggle}
      aria-pressed={saved}
      aria-label={saved ? `Remove ${name} from wishlist` : `Save ${name} to wishlist`}
      className="absolute right-3 top-3 z-10 rounded-full bg-surface/90 p-2 text-lg leading-none shadow-sm transition-transform hover:scale-110 focus-visible:outline-2"
    >
      <span aria-hidden className={saved ? "text-accent" : "text-muted"}>
        {saved ? "♥" : "♡"}
      </span>
    </button>
  );
}
```

`storefront/src/components/product/ProductCard.tsx` (server component):

```tsx
import Image from "next/image";
import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { WishlistHeart } from "@/components/product/WishlistHeart";

/** The one product card. Hover: image swaps to hover_image (pure CSS, no JS) and
 * the card lifts. Gold "Bestseller" badge for featured products (gold = seasoning,
 * per design-direction.md). NOTE: the list API's `brand` field is the brand SLUG
 * (SlugRelatedField) — title-case it for display. */
function brandLabel(slug: string): string {
  return slug.split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
}

export function ProductCard({ product, priority = false }: {
  product: ProductCardData; priority?: boolean;
}) {
  const img = mediaUrl(product.image);
  const hover = mediaUrl(product.hover_image);
  return (
    <div className="group relative">
      <WishlistHeart sku={product.default_sku} name={product.name} />
      <Link
        href={`/product/${product.slug}`}
        className="block rounded-[var(--radius-card)] bg-surface shadow-sm transition-shadow duration-300 hover:shadow-md"
      >
        <div className="relative aspect-[3/4] overflow-hidden rounded-t-[var(--radius-card)] bg-beige">
          {img && (
            <Image
              src={img} alt={product.name} fill priority={priority}
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
              className={`object-cover transition-opacity duration-300 ${hover ? "group-hover:opacity-0" : ""}`}
            />
          )}
          {hover && (
            <Image
              src={hover} alt="" aria-hidden fill
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
              className="object-cover opacity-0 transition-opacity duration-300 group-hover:opacity-100"
            />
          )}
          {product.is_featured && (
            <span className="absolute left-3 top-3 rounded-full bg-gold/90 px-2.5 py-0.5 text-xs font-medium text-surface">
              Bestseller
            </span>
          )}
        </div>
        <div className="space-y-1.5 p-4">
          {product.brand && (
            <p className="text-xs uppercase tracking-wide text-muted">{brandLabel(product.brand)}</p>
          )}
          <h3 className="font-display text-base leading-snug">{product.name}</h3>
          <ReviewStars rating={product.rating_avg} count={product.rating_count} />
          {product.from_price && (
            <PriceTag amount={product.from_price} currency={product.currency} from />
          )}
        </div>
      </Link>
    </div>
  );
}
```

- [ ] **Step 4: Write the failing wishlist BFF tests**

`storefront/src/app/api/wishlist/__tests__/route.test.ts` (same mocking pattern as the Plan-12 auth route test — mock `next/headers` cookies with an `access` token in the store, mock `global.fetch` as the Django upstream):

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "TOK"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET, POST, DELETE } from "@/app/api/wishlist/[[...sku]]/route";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const ctx = (sku?: string) => ({ params: Promise.resolve({ sku: sku ? [sku] : undefined }) });

describe("wishlist BFF", () => {
  it("POST forwards {sku} with the Bearer token", async () => {
    const f = upstream(201, { sku: "TOKE-X" });
    const res = await POST(new Request("http://localhost:3000/api/wishlist", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ sku: "TOKE-X" }),
    }), ctx());
    expect(res.status).toBe(201);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/wishlist/");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
  });

  it("DELETE targets the sku path", async () => {
    const f = upstream(204, null);
    const res = await DELETE(new Request("http://localhost:3000/api/wishlist/TOKE-X", {
      method: "DELETE",
    }), ctx("TOKE-X"));
    expect(res.status).toBe(204);
    expect(f.mock.calls[0][0]).toBe("http://backend:8000/api/v1/me/wishlist/TOKE-X/");
  });

  it("returns 401 without a session (no upstream call)", async () => {
    store.delete("access");
    const f = upstream(200, {});
    const res = await GET(new Request("http://localhost:3000/api/wishlist"), ctx());
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });
});
```

Run: `npm run test -- --run src/app/api/wishlist` — expected FAIL.

- [ ] **Step 5: Implement the wishlist BFF**

`storefront/src/app/api/wishlist/[[...sku]]/route.ts`:

```ts
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";

/** Authed wishlist proxy (backend is sku-keyed under /me/wishlist/). The browser
 * never sees the token — fetchWithAuth reads httpOnly cookies server-side. */
function json(data: unknown, status = 200) {
  return new Response(data === null ? null : JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

function onError(e: unknown) {
  if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
  return json({ detail: "Unexpected error." }, 500);
}

export async function GET(_req: Request, _ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  try { return json(await fetchWithAuth("/me/wishlist/")); } catch (e) { return onError(e); }
}

export async function POST(req: Request, _ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const body = await req.json().catch(() => ({}));
  try {
    return json(await fetchWithAuth("/me/wishlist/", { method: "POST", body }), 201);
  } catch (e) { return onError(e); }
}

export async function DELETE(_req: Request, ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const { sku } = await ctx.params;
  if (!sku?.[0]) return json({ detail: "sku required." }, 400);
  try {
    await fetchWithAuth(`/me/wishlist/${encodeURIComponent(sku[0])}/`, { method: "DELETE" });
    return new Response(null, { status: 204 });
  } catch (e) { return onError(e); }
}
```

- [ ] **Step 6: Run all new tests + build**

```bash
npm run test -- --run src/app/api/wishlist src/components/product/__tests__/PriceTag.test.tsx
npm run build
```
Expected: PASS, clean build.

- [ ] **Step 7: Mutation-verify**

In the wishlist route, remove the `hasSession` guard from `GET`. Confirm the "401 without a session" test goes RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add src/components/motion src/components/product src/components/providers.tsx src/app/api/wishlist
git commit -m "feat(storefront): product card primitives, motion islands, wishlist BFF

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Homepage part 1 — placeholder art, content module, announcement bar, shrinking header, hero, categories, concerns, brand story (sections 1–6)

**Why:** the first six sections of the design brief's 15-section homepage (docs/design-direction.md § Homepage structure), plus the two pieces of shell polish that belong to it (rotating announcement bar, header that shrinks on scroll). Editorial copy comes from `home-content.ts` (D3); artwork from generated brand-palette SVGs (D4). Visual work — verified by build + eyeball, not unit tests.

**Gated on:** D3, D4.

**Files:**
- Create: `storefront/scripts/gen-placeholders.mjs`, generated `storefront/public/home/**`
- Create: `storefront/src/lib/home-content.ts`
- Create: `storefront/src/components/layout/AnnouncementBar.tsx`, `storefront/src/components/layout/ScrollShrink.tsx`
- Create: `storefront/src/components/home/Hero.tsx`, `FeaturedCategories.tsx`, `SkinConcerns.tsx`, `BrandStory.tsx`
- Modify: `storefront/src/app/(shop)/layout.tsx` (announcement bar above header), `storefront/src/app/globals.css` (shrink rules), `storefront/src/app/(shop)/page.tsx` (assemble sections 1–6)

- [ ] **Step 1: Placeholder-art generator**

`storefront/scripts/gen-placeholders.mjs` — deterministic SVGs in the brand palette; run once, commit the output. Node-only, no deps:

```js
// Generates the homepage's placeholder art (Plan-13 D4) into public/home/.
// Deterministic: same input -> same files. Replace 1:1 with real photography later.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const OUT = join(import.meta.dirname, "..", "public", "home");
const P = { cream: "#FBF9F5", beige: "#F1EAE0", ink: "#1A1A1A",
            green: "#1C7A3E", dark: "#145F30", leaf: "#8CC63F", gold: "#C9A227" };

const grain = `<filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.05"/></feComponentTransfer><feComposite operator="over" in2="SourceGraphic"/></filter>`;

function gradientSvg(w, h, c1, c2, blobColor, seedX, seedY) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}">
<defs><linearGradient id="lg" x1="0" y1="0" x2="0.3" y2="1">
<stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient>
<radialGradient id="rg" cx="${seedX}" cy="${seedY}" r="0.6">
<stop offset="0" stop-color="${blobColor}" stop-opacity="0.55"/>
<stop offset="1" stop-color="${blobColor}" stop-opacity="0"/></radialGradient>${grain}</defs>
<rect width="${w}" height="${h}" fill="url(#lg)"/>
<rect width="${w}" height="${h}" fill="url(#rg)"/>
<rect width="${w}" height="${h}" filter="url(#g)" opacity="0.5"/></svg>`;
}

function avatarSvg(initial, bg) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="48" fill="${bg}"/>
<text x="48" y="60" text-anchor="middle" font-family="Georgia, serif" font-size="38" fill="#FBF9F5">${initial}</text></svg>`;
}

mkdirSync(join(OUT, "concerns"), { recursive: true });
mkdirSync(join(OUT, "community"), { recursive: true });
mkdirSync(join(OUT, "avatars"), { recursive: true });

writeFileSync(join(OUT, "hero.svg"), gradientSvg(1920, 1080, P.beige, P.green, P.gold, 0.75, 0.3));
writeFileSync(join(OUT, "story-1.svg"), gradientSvg(900, 1100, P.cream, P.leaf, P.green, 0.4, 0.35));
writeFileSync(join(OUT, "story-2.svg"), gradientSvg(900, 1100, P.beige, P.gold, P.green, 0.6, 0.5));
writeFileSync(join(OUT, "collection-banner.svg"), gradientSvg(1800, 700, P.green, P.dark, P.gold, 0.8, 0.4));
writeFileSync(join(OUT, "education.svg"), gradientSvg(1200, 700, P.cream, P.beige, P.leaf, 0.5, 0.4));

const concerns = ["acne", "hyperpigmentation", "dry-skin", "oily-skin",
                  "sensitive-skin", "eczema", "dark-spots", "uneven-tone"];
concerns.forEach((slug, i) => writeFileSync(
  join(OUT, "concerns", `${slug}.svg`),
  gradientSvg(600, 600, i % 2 ? P.beige : P.cream, i % 3 ? P.green : P.gold,
              i % 2 ? P.leaf : P.green, 0.3 + (i % 4) * 0.15, 0.3 + (i % 3) * 0.2)));

for (let i = 0; i < 6; i++) writeFileSync(
  join(OUT, "community", `post-${i + 1}.svg`),
  gradientSvg(700, i % 2 ? 900 : 700, i % 2 ? P.cream : P.beige,
              [P.green, P.gold, P.leaf, P.dark][i % 4], P.gold, 0.2 + i * 0.12, 0.5));

["A", "T", "Z", "C", "F"].forEach((ch, i) => writeFileSync(
  join(OUT, "avatars", `a${i + 1}.svg`), avatarSvg(ch, [P.green, P.gold, P.dark, P.leaf, P.ink][i])));

console.log("placeholder art written to public/home/");
```

Run it and commit the output:

```bash
node scripts/gen-placeholders.mjs
```
Expected: `public/home/` now holds hero/story/banner/education SVGs + `concerns/` (8) + `community/` (6) + `avatars/` (5).

- [ ] **Step 2: The content module (D3 — replaced by the Plan-19 CMS)**

`storefront/src/lib/home-content.ts`:

```ts
/** Homepage editorial content (Plan-13 D3). This module IS the "CMS" until
 * Plan-19 ships real content models — keep it typed and boring so Plan-19 can
 * swap each export for an API call without touching the section components.
 * Hammed: edit copy freely; image paths point at public/home/ (D4 placeholders). */

export const ANNOUNCEMENTS = [
  "Free delivery in Nigeria on orders over ₦50,000",
  "Worldwide shipping — UK · US · Canada · everywhere",
  "Dermatologist recommended, made for melanin-rich skin",
  "Secure worldwide checkout",
];

export const HERO = {
  headline: "Healthy Skin Begins Here.",
  sub: "Science-backed skincare with African botanicals — made for melanin-rich skin, trusted worldwide.",
  image: "/home/hero.svg",
  // "Take Skin Quiz" (design brief) has no route yet — it points at the concerns
  // grid anchor until the quiz exists (future plan).
  ctas: [
    { label: "Shop Now", href: "/products", primary: true },
    { label: "Take Skin Quiz", href: "#skin-concerns", primary: false },
  ],
};

export const SKIN_CONCERNS = [
  { name: "Acne", slug: "acne" }, { name: "Hyperpigmentation", slug: "hyperpigmentation" },
  { name: "Dry Skin", slug: "dry-skin" }, { name: "Oily Skin", slug: "oily-skin" },
  { name: "Sensitive Skin", slug: "sensitive-skin" }, { name: "Eczema", slug: "eczema" },
  { name: "Dark Spots", slug: "dark-spots" }, { name: "Uneven Tone", slug: "uneven-tone" },
].map((c) => ({ ...c, image: `/home/concerns/${c.slug}.svg`, href: `/products?tag=${c.slug}` }));

export const BRAND_STORY = {
  title: "Rooted in nature. Proven by science.",
  paragraphs: [
    "Toke Cosmetics blends cold-pressed African botanicals with clinically proven actives — shea from Kano, black soap from Ogun, formulations reviewed by dermatologists.",
    "Every product is made for melanin-rich skin first, and loved by families everywhere: mothers, babies, teens and men alike.",
  ],
  images: ["/home/story-1.svg", "/home/story-2.svg"],
  cta: { label: "Our story", href: "/page/about" },
};

export const WHY_CHOOSE = [
  { title: "Dermatologist approved", body: "Formulations reviewed by skin professionals." },
  { title: "Natural ingredients", body: "African botanicals, no parabens or sulphates." },
  { title: "Cruelty free", body: "Never tested on animals." },
  { title: "Worldwide shipping", body: "Lagos to London, New York to Nairobi." },
  { title: "Secure payments", body: "Bank-grade encryption on every order." },
  { title: "Money-back promise", body: "14-day returns, no questions asked." },
];

export const TESTIMONIALS = [
  { quote: "My hyperpigmentation faded in weeks. I have never trusted a brand like this.",
    name: "Amaka O.", where: "Lagos", avatar: "/home/avatars/a1.svg" },
  { quote: "Finally — skincare that understands melanin-rich skin AND ships to the UK fast.",
    name: "Tolu A.", where: "London", avatar: "/home/avatars/a2.svg" },
  { quote: "The whole family uses the baby oil. Gentle, rich, zero reactions.",
    name: "Zainab K.", where: "Abuja", avatar: "/home/avatars/a3.svg" },
  { quote: "Texture, scent, results. This is luxury without the luxury markup.",
    name: "Chidi N.", where: "Toronto", avatar: "/home/avatars/a4.svg" },
];

export const COMMUNITY = Array.from({ length: 6 }, (_, i) => ({
  image: `/home/community/post-${i + 1}.svg`,
  alt: "Toke community — real routines, real skin",
}));

export const EDUCATION = [
  { title: "The melanin-rich skin guide to vitamin C", href: "/page/blog", image: "/home/education.svg" },
  { title: "Hyperpigmentation: what actually works", href: "/page/blog", image: "/home/education.svg" },
  { title: "Building a 3-step routine that sticks", href: "/page/blog", image: "/home/education.svg" },
];

export const FEATURED_COLLECTION = {
  slug: "glow-naturally",
  title: "Glow Naturally",
  sub: "The curated edit for radiant, even-toned skin.",
  image: "/home/collection-banner.svg",
};
```

- [ ] **Step 3: Announcement bar + scroll shrink**

`storefront/src/components/layout/AnnouncementBar.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/** Section 1: rotating announcement bar. SSR renders the first message (no CLS);
 * rotation pauses for prefers-reduced-motion. aria-live=off — decorative rotation
 * must not spam screen readers. */
export function AnnouncementBar() {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setI((n) => (n + 1) % ANNOUNCEMENTS.length), 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="bg-accent text-surface" aria-live="off">
      <p key={i} className="mx-auto max-w-7xl px-4 py-2 text-center text-xs tracking-wide">
        {ANNOUNCEMENTS[i]}
      </p>
    </div>
  );
}
```

`storefront/src/components/layout/ScrollShrink.tsx`:

```tsx
"use client";
import { useEffect } from "react";

/** Sets data-scrolled on <html> past 24px; globals.css shrinks the header. Renders
 * nothing — the header itself stays a Server Component. */
export function ScrollShrink() {
  useEffect(() => {
    const onScroll = () =>
      document.documentElement.toggleAttribute("data-scrolled", window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return null;
}
```

Append to `storefront/src/app/globals.css`:

```css
/* Elegant header shrink (Plan-13): driven by ScrollShrink's data-scrolled flag. */
header[data-site-header] { transition: padding 0.25s ease; }
header[data-site-header] .site-logo { transition: transform 0.25s ease; transform-origin: left center; }
html[data-scrolled] header[data-site-header] > div { padding-top: 0.375rem; padding-bottom: 0.375rem; }
html[data-scrolled] header[data-site-header] .site-logo { transform: scale(0.85); }
```

In `storefront/src/components/layout/Header.tsx`: add `data-site-header` to the `<header>` element and `className="site-logo …"` on the logo `<Link>` (no other changes).

In `storefront/src/app/(shop)/layout.tsx`: render `<AnnouncementBar />` and `<ScrollShrink />` immediately above `<CountrySuggestionBanner …/>` (announcement is the topmost strip).

- [ ] **Step 4: Hero, categories, concerns, story sections**

`storefront/src/components/home/Hero.tsx` (server; LCP-critical — the image is `priority`, the motion is CSS-only so the hero needs zero JS):

```tsx
import Image from "next/image";
import Link from "next/link";
import { HERO } from "@/lib/home-content";

export function Hero() {
  return (
    <section className="relative flex min-h-[70vh] items-center overflow-hidden">
      <Image src={HERO.image} alt="" fill priority
        className="object-cover motion-safe:animate-[heroZoom_18s_ease-out_forwards]" />
      <div className="absolute inset-0 bg-gradient-to-r from-black/35 via-black/10 to-transparent" />
      <div className="relative mx-auto w-full max-w-7xl px-4 py-24">
        <h1 className="max-w-2xl font-display text-5xl leading-tight text-surface md:text-7xl">
          {HERO.headline}
        </h1>
        <p className="mt-5 max-w-xl text-lg text-surface/90">{HERO.sub}</p>
        <div className="mt-8 flex flex-wrap gap-4">
          {HERO.ctas.map((cta) => (
            <Link key={cta.label} href={cta.href}
              className={cta.primary
                ? "rounded-full bg-surface px-8 py-3.5 font-medium text-foreground transition hover:bg-cream"
                : "rounded-full border border-surface/70 px-8 py-3.5 font-medium text-surface transition hover:bg-surface/10"}>
              {cta.label}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
```

Add the keyframes to `globals.css`:

```css
@keyframes heroZoom { from { transform: scale(1); } to { transform: scale(1.06); } }
```

`storefront/src/components/home/FeaturedCategories.tsx` (server — section 4; data from the API):

```tsx
import Image from "next/image";
import Link from "next/link";
import type { CategoryNode } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { FadeUp } from "@/components/motion/Motion";

export function FeaturedCategories({ categories }: { categories: CategoryNode[] }) {
  const roots = categories.slice(0, 6);
  if (roots.length === 0) return null;
  return (
    <section aria-labelledby="cats-h" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <h2 id="cats-h" className="font-display text-3xl md:text-4xl">Shop by category</h2>
      </FadeUp>
      <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {roots.map((c, i) => (
          <FadeUp key={c.slug} delay={i * 0.05}>
            <Link href={`/category/${c.slug}`} className="group block text-center">
              <div className="relative aspect-square overflow-hidden rounded-full bg-beige">
                {mediaUrl(c.image) && (
                  <Image src={mediaUrl(c.image)!} alt="" fill sizes="(max-width:768px) 45vw, 15vw"
                    className="object-cover transition-transform duration-500 group-hover:scale-105" />
                )}
              </div>
              <p className="mt-3 text-sm font-medium group-hover:text-accent">{c.name}</p>
            </Link>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}
```

`storefront/src/components/home/SkinConcerns.tsx` (server — section 5; static tiles → `?tag=` PLPs):

```tsx
import Image from "next/image";
import Link from "next/link";
import { SKIN_CONCERNS } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

export function SkinConcerns() {
  return (
    <section id="skin-concerns" aria-labelledby="concerns-h" className="bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-16">
        <FadeUp>
          <h2 id="concerns-h" className="font-display text-3xl md:text-4xl">Shop by skin concern</h2>
        </FadeUp>
        <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {SKIN_CONCERNS.map((c, i) => (
            <FadeUp key={c.slug} delay={i * 0.04}>
              <Link href={c.href}
                className="group relative block overflow-hidden rounded-[var(--radius-card)]">
                <Image src={c.image} alt="" width={600} height={600}
                  className="aspect-square w-full object-cover transition-transform duration-500 group-hover:scale-105" />
                <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent p-4 font-medium text-surface">
                  {c.name}
                </span>
              </Link>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  );
}
```

`storefront/src/components/home/BrandStory.tsx` (server — section 6, split editorial):

```tsx
import Image from "next/image";
import Link from "next/link";
import { BRAND_STORY } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

export function BrandStory() {
  return (
    <section aria-labelledby="story-h" className="mx-auto max-w-7xl px-4 py-20">
      <div className="grid items-center gap-10 md:grid-cols-2">
        <div className="grid grid-cols-2 gap-4">
          {BRAND_STORY.images.map((src, i) => (
            <FadeUp key={src} delay={i * 0.1}>
              <Image src={src} alt="" width={900} height={1100}
                className={`rounded-[var(--radius-card)] object-cover ${i === 1 ? "mt-10" : ""}`} />
            </FadeUp>
          ))}
        </div>
        <FadeUp>
          <div className="max-w-lg">
            <h2 id="story-h" className="font-display text-3xl md:text-4xl">{BRAND_STORY.title}</h2>
            {BRAND_STORY.paragraphs.map((p) => (
              <p key={p.slice(0, 20)} className="mt-5 leading-relaxed text-muted">{p}</p>
            ))}
            <Link href={BRAND_STORY.cta.href}
              className="mt-8 inline-block border-b border-accent pb-0.5 font-medium text-accent hover:border-accent-strong">
              {BRAND_STORY.cta.label} →
            </Link>
          </div>
        </FadeUp>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Assemble sections 1–6 in the home page**

Replace `storefront/src/app/(shop)/page.tsx`:

```tsx
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getCategoryTree } from "@/lib/catalog";
import { Hero } from "@/components/home/Hero";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import { SkinConcerns } from "@/components/home/SkinConcerns";
import { BrandStory } from "@/components/home/BrandStory";

export default async function HomePage() {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const categories = await getCategoryTree(country).catch(() => []);
  return (
    <>
      <Hero />
      <FeaturedCategories categories={categories} />
      <SkinConcerns />
      <BrandStory />
      {/* Sections 7-14 land in Task 7 */}
    </>
  );
}
```

(The announcement bar — section 1 — and the shrinking nav — section 2 — live in the shop layout/header, sections 3–6 are above; the footer is section 15, upgraded in Task 7.)

- [ ] **Step 6: Build + eyeball**

```bash
npm run build && npm run dev
```
With the backend running + seeded, open `http://localhost:3000`: announcement bar rotates (and holds still with OS reduced-motion enabled), header shrinks on scroll, hero fills the viewport with the white serif headline and both CTAs, six circular category images from the API, the 8-tile concern grid links to `/products?tag=acne` etc., the split brand story fades up on scroll. Keyboard-tab through: every link/button has a visible focus ring.

- [ ] **Step 7: Commit**

```bash
git add scripts/gen-placeholders.mjs public/home src/lib/home-content.ts src/components/layout/AnnouncementBar.tsx src/components/layout/ScrollShrink.tsx src/components/layout/Header.tsx src/components/home src/app/globals.css "src/app/(shop)/layout.tsx" "src/app/(shop)/page.tsx"
git commit -m "feat(storefront): homepage sections 1-6 — announcement, shrink nav, hero, categories, concerns, story

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Homepage part 2 — product rows, collection banner, why-choose, testimonials, community, education, newsletter, big footer, home SEO (sections 7–15)

**Why:** the remaining nine sections, all data-driven ones fed by the seeded collections, plus the homepage's metadata and site-wide JSON-LD (Organization + WebSite/SearchAction — the master spec's site-wide layer starts here).

**Files:**
- Create: `storefront/src/components/home/Carousel.tsx`, `ProductRow.tsx`, `CollectionBanner.tsx`, `WhyChoose.tsx`, `Testimonials.tsx`, `CommunityGrid.tsx`, `EducationTeasers.tsx`, `NewsletterCta.tsx`
- Modify: `storefront/src/components/layout/Footer.tsx` (large-footer upgrade)
- Modify: `storefront/src/app/(shop)/page.tsx` (assemble + metadata + JSON-LD)

- [ ] **Step 1: Scroll-snap carousel shell (the only carousel mechanism in this plan)**

`storefront/src/components/home/Carousel.tsx`:

```tsx
"use client";
import { useRef, type ReactNode } from "react";

/** CSS scroll-snap carousel with arrow controls — no carousel library (Lighthouse
 * budget). Children are the slides; each gets snap-start + a fixed basis. */
export function Carousel({ children, label }: { children: ReactNode; label: string }) {
  const track = useRef<HTMLDivElement>(null);
  const nudge = (dir: 1 | -1) =>
    track.current?.scrollBy({ left: dir * track.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <div role="group" aria-label={label} className="relative">
      <div ref={track}
        className="flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth pb-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {children}
      </div>
      <button onClick={() => nudge(-1)} aria-label={`Scroll ${label} back`}
        className="absolute -left-3 top-1/3 hidden h-10 w-10 rounded-full bg-surface shadow-md transition hover:bg-cream md:block">←</button>
      <button onClick={() => nudge(1)} aria-label={`Scroll ${label} forward`}
        className="absolute -right-3 top-1/3 hidden h-10 w-10 rounded-full bg-surface shadow-md transition hover:bg-cream md:block">→</button>
    </div>
  );
}
```

- [ ] **Step 2: Product rows + banner + static sections**

`storefront/src/components/home/ProductRow.tsx` (server — sections 7 "Best sellers" and 9 "New arrivals"):

```tsx
import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { Carousel } from "@/components/home/Carousel";
import { FadeUp } from "@/components/motion/Motion";

export function ProductRow({ title, products, href, carousel = false }: {
  title: string; products: ProductCardData[]; href: string; carousel?: boolean;
}) {
  if (products.length === 0) return null;
  const cards = products.map((p) => (
    <div key={p.slug} className={carousel ? "w-[70vw] shrink-0 snap-start sm:w-72" : ""}>
      <ProductCard product={p} />
    </div>
  ));
  return (
    <section aria-label={title} className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp>
        <div className="flex items-end justify-between">
          <h2 className="font-display text-3xl md:text-4xl">{title}</h2>
          <Link href={href} className="text-sm font-medium text-accent hover:text-accent-strong">
            View all →
          </Link>
        </div>
      </FadeUp>
      <div className="mt-8">
        {carousel
          ? <Carousel label={title}>{cards}</Carousel>
          : <div className="grid grid-cols-2 gap-4 md:grid-cols-4">{cards}</div>}
      </div>
    </section>
  );
}
```

`storefront/src/components/home/CollectionBanner.tsx` (server — section 8):

```tsx
import Image from "next/image";
import Link from "next/link";
import { FEATURED_COLLECTION } from "@/lib/home-content";

export function CollectionBanner() {
  const c = FEATURED_COLLECTION;
  return (
    <section aria-label={c.title} className="mx-auto max-w-7xl px-4 py-8">
      <Link href={`/products?collection=${c.slug}`}
        className="group relative block overflow-hidden rounded-[var(--radius-card)]">
        <Image src={c.image} alt="" width={1800} height={700}
          className="h-[340px] w-full object-cover transition-transform duration-700 group-hover:scale-[1.03] md:h-[420px]" />
        <div className="absolute inset-0 flex flex-col items-start justify-center bg-black/25 p-8 md:p-16">
          <h2 className="font-display text-4xl text-surface md:text-5xl">{c.title}</h2>
          <p className="mt-3 max-w-md text-surface/90">{c.sub}</p>
          <span className="mt-6 rounded-full bg-surface px-7 py-3 font-medium text-foreground transition group-hover:bg-cream">
            Shop the edit
          </span>
        </div>
      </Link>
    </section>
  );
}
```

`storefront/src/components/home/WhyChoose.tsx` (server — section 10; inline SVG leaf/shield/heart icons or simple glyphs, gold thin-rule details):

```tsx
import { WHY_CHOOSE } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

export function WhyChoose() {
  return (
    <section aria-labelledby="why-h" className="bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-16">
        <FadeUp><h2 id="why-h" className="font-display text-3xl md:text-4xl">Why choose Toke</h2></FadeUp>
        <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
          {WHY_CHOOSE.map((w, i) => (
            <FadeUp key={w.title} delay={i * 0.04}>
              <div className="h-full rounded-[var(--radius-card)] bg-surface p-5 text-center shadow-sm">
                <div className="mx-auto h-px w-8 bg-gold" aria-hidden />
                <h3 className="mt-3 text-sm font-semibold">{w.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-muted">{w.body}</p>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  );
}
```

`storefront/src/components/home/Testimonials.tsx` (server shell + the Carousel island — section 11):

```tsx
import Image from "next/image";
import { TESTIMONIALS } from "@/lib/home-content";
import { Carousel } from "@/components/home/Carousel";
import { FadeUp } from "@/components/motion/Motion";

export function Testimonials() {
  return (
    <section aria-labelledby="reviews-h" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp><h2 id="reviews-h" className="font-display text-3xl md:text-4xl">Loved worldwide</h2></FadeUp>
      <div className="mt-8">
        <Carousel label="Customer reviews">
          {TESTIMONIALS.map((t) => (
            <figure key={t.name}
              className="w-[85vw] shrink-0 snap-start rounded-[var(--radius-card)] bg-surface p-8 shadow-sm sm:w-[420px]">
              <div aria-hidden className="text-gold">★★★★★</div>
              <blockquote className="mt-4 font-display text-lg leading-relaxed">“{t.quote}”</blockquote>
              <figcaption className="mt-5 flex items-center gap-3 text-sm text-muted">
                <Image src={t.avatar} alt="" width={40} height={40} className="rounded-full" />
                <span>{t.name} · {t.where}</span>
              </figcaption>
            </figure>
          ))}
        </Carousel>
      </div>
    </section>
  );
}
```

`storefront/src/components/home/CommunityGrid.tsx` (server — section 12, masonry via CSS columns):

```tsx
import Image from "next/image";
import { COMMUNITY } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

export function CommunityGrid() {
  return (
    <section aria-labelledby="community-h" className="bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-16">
        <FadeUp>
          <h2 id="community-h" className="font-display text-3xl md:text-4xl">#TokeGlow community</h2>
          <p className="mt-2 text-muted">Real routines from Lagos to London — tag us to be featured.</p>
        </FadeUp>
        <div className="mt-8 columns-2 gap-4 md:columns-3 [&>*]:mb-4">
          {COMMUNITY.map((c, i) => (
            <Image key={i} src={c.image} alt={c.alt} width={700} height={i % 2 ? 900 : 700}
              className="w-full break-inside-avoid rounded-[var(--radius-card)]" loading="lazy" />
          ))}
        </div>
      </div>
    </section>
  );
}
```

`storefront/src/components/home/EducationTeasers.tsx` (server — section 13) and `NewsletterCta.tsx` (server — section 14, reusing the Plan-12 `NewsletterForm`):

```tsx
import Image from "next/image";
import Link from "next/link";
import { EDUCATION } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

export function EducationTeasers() {
  return (
    <section aria-labelledby="edu-h" className="mx-auto max-w-7xl px-4 py-16">
      <FadeUp><h2 id="edu-h" className="font-display text-3xl md:text-4xl">The skincare journal</h2></FadeUp>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {EDUCATION.map((a, i) => (
          <FadeUp key={a.title} delay={i * 0.06}>
            <Link href={a.href} className="group block">
              <Image src={a.image} alt="" width={1200} height={700}
                className="aspect-[16/10] w-full rounded-[var(--radius-card)] object-cover transition-transform duration-500 group-hover:scale-[1.02]" loading="lazy" />
              <h3 className="mt-4 font-display text-lg group-hover:text-accent">{a.title}</h3>
            </Link>
          </FadeUp>
        ))}
      </div>
    </section>
  );
}
```

```tsx
import { NewsletterForm } from "@/components/layout/NewsletterForm";
import { FadeUp } from "@/components/motion/Motion";

export function NewsletterCta() {
  return (
    <section aria-labelledby="nl-h" className="bg-accent">
      <FadeUp>
        <div className="mx-auto max-w-2xl px-4 py-16 text-center text-surface">
          <h2 id="nl-h" className="font-display text-3xl md:text-4xl">Glow, delivered.</h2>
          <p className="mt-3 text-surface/85">Skincare science, launches and members-only offers. No spam, ever.</p>
          <div className="mt-6">
            <NewsletterForm />
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
```

(If `NewsletterForm`'s styling clashes on the green background, give it an optional `variant="onAccent"` prop rather than duplicating the form.)

- [ ] **Step 3: Big-footer upgrade (section 15)**

Rework `storefront/src/components/layout/Footer.tsx` into the large four-column layout **preserving everything it already does** (policy links to `/page/[slug]`, the working `NewsletterForm`, payment logos): columns "Shop" (top categories — pass no props; keep it static links to `/products`, `/category/face`, `/category/body`, `/category/hair`), "Company" (About, Blog, Community, Wholesale, Affiliates → `/page/...` routes), "Support" (Shipping, Returns, Contact, FAQs → `/page/...`), "Legal" (Privacy, Terms), then the newsletter block, social icon links (Instagram/Facebook/TikTok as text-icons), payment logos, and a bottom strip: `© {new Date().getFullYear()} Toke Cosmetics · Lagos, Nigeria`. Keep it a Server Component; keep every existing test green.

- [ ] **Step 4: Assemble the full homepage + metadata + site-wide JSON-LD**

Replace `storefront/src/app/(shop)/page.tsx`:

```tsx
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getCategoryTree, getProducts } from "@/lib/catalog";
import { pageMetadata, organizationJsonLd, webSiteJsonLd, DEFAULT_DESCRIPTION } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { Hero } from "@/components/home/Hero";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import { SkinConcerns } from "@/components/home/SkinConcerns";
import { BrandStory } from "@/components/home/BrandStory";
import { ProductRow } from "@/components/home/ProductRow";
import { CollectionBanner } from "@/components/home/CollectionBanner";
import { WhyChoose } from "@/components/home/WhyChoose";
import { Testimonials } from "@/components/home/Testimonials";
import { CommunityGrid } from "@/components/home/CommunityGrid";
import { EducationTeasers } from "@/components/home/EducationTeasers";
import { NewsletterCta } from "@/components/home/NewsletterCta";

export const metadata: Metadata = pageMetadata({
  title: "Toke Cosmetics — Premium Skincare for Melanin-Rich Skin",
  description: DEFAULT_DESCRIPTION,
  path: "/",
});

export default async function HomePage() {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const [categories, bestSellers, newArrivals] = await Promise.all([
    getCategoryTree(country).catch(() => []),
    getProducts({ collection: "best-sellers" }, country).then((p) => p.results).catch(() => []),
    getProducts({ collection: "new-arrivals", ordering: "newest" }, country).then((p) => p.results).catch(() => []),
  ]);
  return (
    <>
      <JsonLd data={organizationJsonLd()} />
      <JsonLd data={webSiteJsonLd()} />
      <Hero />
      <FeaturedCategories categories={categories} />
      <SkinConcerns />
      <BrandStory />
      <ProductRow title="Best sellers" products={bestSellers} href="/products?collection=best-sellers" carousel />
      <CollectionBanner />
      <ProductRow title="New arrivals" products={newArrivals.slice(0, 8)} href="/products?ordering=newest" />
      <WhyChoose />
      <Testimonials />
      <CommunityGrid />
      <EducationTeasers />
      <NewsletterCta />
    </>
  );
}
```

- [ ] **Step 5: Build + eyeball + a11y pass**

```bash
npm run test -- --run     # Plan-12 layout tests must still pass after the Footer rework
npm run build && npm run dev
```
Eyeball on `http://localhost:3000` (backend running): all 15 sections render in order with real seeded products in rows 7/9; carousels scroll by arrow AND swipe; heading levels are h1 (hero) → h2 (sections) → h3 (cards); tab order sane; view page source → both JSON-LD scripts present. Resize to 375px: no horizontal scroll anywhere (design non-negotiable).

- [ ] **Step 6: Commit**

```bash
git add src/components/home src/components/layout/Footer.tsx src/components/layout/NewsletterForm.tsx "src/app/(shop)/page.tsx"
git commit -m "feat(storefront): homepage sections 7-15 + big footer + home SEO (Org/WebSite JSON-LD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: PLP engine + `/products` listing page

**Why:** one server-rendered listing engine (grid, filters, sort, pagination — all as crawlable URL params per the master spec) reused by `/products`, `/category/[slug]` (Task 9) and `/search` (Task 10). Filters offered = what the backend really supports on `/products/`: price and brand (+ tag/collection passthrough); sort = the four backend orderings. **No rating or availability filter here** (flagged risk — backend doesn't support them on this endpoint).

**Files:**
- Create: `storefront/src/components/plp/ProductGrid.tsx`, `FiltersBar.tsx`, `SortSelect.tsx`, `Pagination.tsx`, `plpParams.ts`
- Modify: `storefront/src/app/(shop)/products/page.tsx` (replace skeleton)
- Test: `storefront/src/components/plp/__tests__/plpParams.test.ts`

- [ ] **Step 1: Write the failing params test**

The PLP reads `searchParams` (untrusted). One helper normalises them; test it.

`storefront/src/components/plp/__tests__/plpParams.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { parsePlpParams, plpHref } from "@/components/plp/plpParams";

describe("parsePlpParams", () => {
  it("keeps known params, coerces page, drops junk", () => {
    expect(parsePlpParams({ brand: "toke-naturals", page: "3", evil: "x", ordering: "price_asc" }))
      .toEqual({ brand: "toke-naturals", page: 3, ordering: "price_asc" });
  });
  it("rejects a non-numeric or <1 page and unknown orderings", () => {
    expect(parsePlpParams({ page: "abc", ordering: "hack" })).toEqual({ page: 1 });
  });
  it("array params (?brand=a&brand=b) take the first value", () => {
    expect(parsePlpParams({ brand: ["a", "b"] })).toEqual({ brand: "a", page: 1 });
  });
});

describe("plpHref", () => {
  it("builds an URL keeping current filters and swapping one key", () => {
    expect(plpHref("/products", { brand: "x", page: 3 }, { page: 4 }))
      .toBe("/products?brand=x&page=4");
    expect(plpHref("/products", { brand: "x", page: 3 }, { ordering: "price_desc" }))
      .toBe("/products?brand=x&ordering=price_desc");  // changing a filter resets page
  });
});
```

Run: `npm run test -- --run src/components/plp` — expected FAIL.

- [ ] **Step 2: Implement the params helper**

`storefront/src/components/plp/plpParams.ts`:

```ts
/** searchParams (untrusted URL input) -> a safe, typed PLP state, and back to hrefs.
 * Shareable/crawlable URLs are the master-spec requirement — ALL state is in the URL. */
export const ORDERINGS = ["newest", "price_asc", "price_desc", "best_selling"] as const;
export type Ordering = (typeof ORDERINGS)[number];

export interface PlpState {
  brand?: string; tag?: string; collection?: string;
  price_min?: string; price_max?: string;
  ordering?: Ordering; page: number;
}
type Raw = Record<string, string | string[] | undefined>;

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export function parsePlpParams(raw: Raw): PlpState {
  const state: PlpState = { page: 1 };
  const page = Number(first(raw.page));
  if (Number.isInteger(page) && page > 1) state.page = page;
  for (const key of ["brand", "tag", "collection", "price_min", "price_max"] as const) {
    const v = first(raw[key]);
    if (v) state[key] = v;
  }
  const ord = first(raw.ordering);
  if (ord && (ORDERINGS as readonly string[]).includes(ord)) state.ordering = ord as Ordering;
  return state;
}

/** Href for the same PLP with one key changed. Changing anything but `page` resets
 * to page 1 (a new filter set is a new result set). */
export function plpHref(base: string, current: PlpState, patch: Partial<PlpState>): string {
  const next = { ...current, ...patch };
  if (!("page" in patch)) next.page = 1;
  const qs = new URLSearchParams();
  for (const key of ["brand", "tag", "collection", "price_min", "price_max", "ordering"] as const) {
    if (next[key]) qs.set(key, String(next[key]));
  }
  if (next.page > 1) qs.set("page", String(next.page));
  const s = qs.toString();
  return s ? `${base}?${s}` : base;
}
```

Run the tests again — expected PASS. Mutation-verify: remove the `next.page = 1` reset, confirm the second `plpHref` assertion goes RED, revert.

- [ ] **Step 3: Grid, filters, sort, pagination components**

`storefront/src/components/plp/ProductGrid.tsx` (server):

```tsx
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";

export function ProductGrid({ products }: { products: ProductCardData[] }) {
  if (products.length === 0) {
    return (
      <div className="rounded-[var(--radius-card)] bg-beige px-6 py-16 text-center">
        <p className="font-display text-xl">Nothing matches those filters.</p>
        <p className="mt-2 text-sm text-muted">Try widening the price range or clearing filters.</p>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
      {products.map((p, i) => <ProductCard key={p.slug} product={p} priority={i < 4} />)}
    </div>
  );
}
```

`storefront/src/components/plp/FiltersBar.tsx` (server — a plain GET form so filters work without JS and produce crawlable URLs):

```tsx
import type { BrandRow } from "@/lib/catalog";
import type { PlpState } from "@/components/plp/plpParams";
import { SortSelect } from "@/components/plp/SortSelect";

/** GET-method form: submitting rewrites the URL params (SSR round-trip, no JS
 * required). Hidden inputs preserve context params owned by the page (tag/collection). */
export function FiltersBar({ base, state, brands, showBrand = true, resultCount }: {
  base: string; state: PlpState; brands: BrandRow[]; showBrand?: boolean; resultCount: number;
}) {
  return (
    <form method="GET" action={base}
      className="flex flex-wrap items-end gap-3 rounded-[var(--radius-card)] bg-surface p-4 shadow-sm">
      {state.tag && <input type="hidden" name="tag" value={state.tag} />}
      {state.collection && <input type="hidden" name="collection" value={state.collection} />}
      {showBrand && (
        <label className="text-xs text-muted">
          Brand
          <select name="brand" defaultValue={state.brand ?? ""}
            className="mt-1 block rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-foreground">
            <option value="">All brands</option>
            {brands.map((b) => <option key={b.slug} value={b.slug}>{b.name}</option>)}
          </select>
        </label>
      )}
      <label className="text-xs text-muted">
        Min price
        <input name="price_min" type="number" min="0" step="any" defaultValue={state.price_min ?? ""}
          className="mt-1 block w-24 rounded-md border border-line px-2 py-1.5 text-sm text-foreground" />
      </label>
      <label className="text-xs text-muted">
        Max price
        <input name="price_max" type="number" min="0" step="any" defaultValue={state.price_max ?? ""}
          className="mt-1 block w-24 rounded-md border border-line px-2 py-1.5 text-sm text-foreground" />
      </label>
      <SortSelect current={state.ordering ?? "newest"} />
      <button type="submit"
        className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong">
        Apply
      </button>
      <a href={base} className="text-sm text-muted underline hover:text-foreground">Clear</a>
      <span className="ml-auto text-sm text-muted" aria-live="polite">{resultCount} products</span>
    </form>
  );
}
```

`storefront/src/components/plp/SortSelect.tsx` (client sliver — auto-submits the parent form on change; without JS the Apply button still works):

```tsx
"use client";
export function SortSelect({ current }: { current: string }) {
  return (
    <label className="text-xs text-muted">
      Sort
      <select name="ordering" defaultValue={current}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className="mt-1 block rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-foreground">
        <option value="newest">Newest</option>
        <option value="best_selling">Best selling</option>
        <option value="price_asc">Price: low to high</option>
        <option value="price_desc">Price: high to low</option>
      </select>
    </label>
  );
}
```

`storefront/src/components/plp/Pagination.tsx` (server — plain links; the canonical policy in `lib/seo.ts` already handles the page param):

```tsx
import Link from "next/link";
import { plpHref, type PlpState } from "@/components/plp/plpParams";

export function Pagination({ base, state, count, pageSize = 24 }: {
  base: string; state: PlpState; count: number; pageSize?: number;
}) {
  const pages = Math.ceil(count / pageSize);
  if (pages <= 1) return null;
  const page = state.page;
  return (
    <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
      {page > 1 && (
        <Link rel="prev" href={plpHref(base, state, { page: page - 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">← Prev</Link>
      )}
      <span className="px-3 text-sm text-muted">Page {page} of {pages}</span>
      {page < pages && (
        <Link rel="next" href={plpHref(base, state, { page: page + 1 })}
          className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent">Next →</Link>
      )}
    </nav>
  );
}
```

- [ ] **Step 4: The `/products` page**

Replace `storefront/src/app/(shop)/products/page.tsx`:

```tsx
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getBrands, getProducts } from "@/lib/catalog";
import { pageMetadata } from "@/lib/seo";
import { parsePlpParams } from "@/components/plp/plpParams";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { FiltersBar } from "@/components/plp/FiltersBar";
import { Pagination } from "@/components/plp/Pagination";

type Search = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const raw = await searchParams;
  return pageMetadata({
    title: "Shop All Products",
    description: "Browse the full Toke Cosmetics range — face, body, hair and family skincare made for melanin-rich skin.",
    path: "/products",
    searchParams: Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]),
    ),
  });
}

export default async function ProductsPage({ searchParams }: { searchParams: Search }) {
  const state = parsePlpParams(await searchParams);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const [page, brands] = await Promise.all([
    getProducts(state, country),
    getBrands(country).catch(() => []),
  ]);
  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">All products</h1>
      <div className="mt-6">
        <FiltersBar base="/products" state={state} brands={brands} resultCount={page.count} />
      </div>
      <div className="mt-6">
        <ProductGrid products={page.results} />
      </div>
      <Pagination base="/products" state={state} count={page.count} />
    </section>
  );
}
```

(`plpHref` is only used by `Pagination` — do not import it in the page.)

- [ ] **Step 5: Build + eyeball**

```bash
npm run test -- --run src/components/plp
npm run build && npm run dev
```
On `http://localhost:3000/products`: 24 cards page 1, pagination appears (seed = 24+4 products), brand filter + price range narrow the grid via URL params (check the address bar shows `?brand=...`), sort flips order, `Clear` resets, hover on a card swaps to the second image, empty-state shows for an impossible price range. View source: canonical is `https://…/products` when filtered, `…/products?page=2` on page 2.

- [ ] **Step 6: Commit**

```bash
git add src/components/plp "src/app/(shop)/products/page.tsx"
git commit -m "feat(storefront): PLP engine (URL-param filters/sort/pagination) + /products page

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Category PLP — `/category/[slug]` with breadcrumbs + BreadcrumbList JSON-LD

**Why:** the category page is the SEO workhorse (WP slugs must keep working — slug parity note below). It reuses the whole Task-8 engine and adds: category lookup from the tree (404 when absent), a visible breadcrumb trail, `BreadcrumbList` JSON-LD, and category metadata. **Slug parity:** category/product slugs are IDENTICAL to the migrated WP slugs (guaranteed later by Plan-21/24); nothing in this task may transform, prettify, or re-case a slug — use them verbatim in URLs and lookups.

**Files:**
- Create: `storefront/src/components/plp/Breadcrumbs.tsx`
- Modify: `storefront/src/app/(shop)/category/[slug]/page.tsx` (replace skeleton)

- [ ] **Step 1: Breadcrumbs component**

`storefront/src/components/plp/Breadcrumbs.tsx` (server):

```tsx
import Link from "next/link";

export interface Crumb { name: string; path: string }

export function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="text-sm text-muted">
      <ol className="flex flex-wrap items-center gap-1.5">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={c.path} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden>/</span>}
              {last
                ? <span aria-current="page" className="text-foreground">{c.name}</span>
                : <Link href={c.path} className="hover:text-accent">{c.name}</Link>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
```

- [ ] **Step 2: The category page**

Replace `storefront/src/app/(shop)/category/[slug]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { findCategory, getBrands, getCategoryTree, getProducts } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { breadcrumbJsonLd, pageMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { parsePlpParams } from "@/components/plp/plpParams";
import { Breadcrumbs, type Crumb } from "@/components/plp/Breadcrumbs";
import { ProductGrid } from "@/components/plp/ProductGrid";
import { FiltersBar } from "@/components/plp/FiltersBar";
import { Pagination } from "@/components/plp/Pagination";

type Params = Promise<{ slug: string }>;
type Search = Promise<Record<string, string | string[] | undefined>>;

async function loadCategory(slug: string, country: string) {
  const tree = await getCategoryTree(country).catch(() => []);
  return findCategory(tree, slug);
}

export async function generateMetadata(
  { params, searchParams }: { params: Params; searchParams: Search },
): Promise<Metadata> {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const hit = await loadCategory(slug, country);
  if (!hit) return { title: "Category not found" };
  const raw = await searchParams;
  // Category seo_title/seo_description are NOT exposed by the API yet (Plan-13
  // flagged risk) — a name-based template stands in until a later backend change.
  return pageMetadata({
    title: `${hit.node.name} — Skincare & Beauty`,
    description: `Shop ${hit.node.name.toLowerCase()} by Toke Cosmetics — premium, science-backed care for melanin-rich skin. Ships from Nigeria worldwide.`,
    path: `/category/${slug}`,
    searchParams: Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, Array.isArray(v) ? v[0] : v]),
    ),
    image: mediaUrl(hit.node.image),
  });
}

export default async function CategoryPage(
  { params, searchParams }: { params: Params; searchParams: Search },
) {
  const { slug } = await params;
  const state = parsePlpParams(await searchParams);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const hit = await loadCategory(slug, country);
  if (!hit) notFound();

  const [page, brands] = await Promise.all([
    getProducts({ ...state, category: slug }, country),
    getBrands(country).catch(() => []),
  ]);

  const crumbs: Crumb[] = [
    { name: "Home", path: "/" },
    ...hit.ancestors.map((a) => ({ name: a.name, path: `/category/${a.slug}` })),
    { name: hit.node.name, path: `/category/${slug}` },
  ];

  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      <Breadcrumbs crumbs={crumbs} />
      <h1 className="mt-4 font-display text-4xl">{hit.node.name}</h1>
      {hit.node.children.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {hit.node.children.map((c) => (
            <a key={c.slug} href={`/category/${c.slug}`}
              className="rounded-full border border-line px-4 py-1.5 text-sm transition hover:border-accent hover:text-accent">
              {c.name}
            </a>
          ))}
        </div>
      )}
      <div className="mt-6">
        <FiltersBar base={`/category/${slug}`} state={state} brands={brands} resultCount={page.count} />
      </div>
      <div className="mt-6">
        <ProductGrid products={page.results} />
      </div>
      <Pagination base={`/category/${slug}`} state={state} count={page.count} />
    </section>
  );
}
```

- [ ] **Step 3: Build + eyeball**

```bash
npm run build && npm run dev
```
Open `/category/face`: breadcrumb `Home / Face`, child-category pills (Cleansers/Serums/Moisturisers), filtered grid; `/category/serums` shows `Home / Face / Serums`; `/category/nonsense` → the Plan-12 404 page. View source on `/category/face?brand=toke-naturals`: canonical is the bare `/category/face`; the BreadcrumbList JSON-LD is present.

- [ ] **Step 4: Commit**

```bash
git add src/components/plp/Breadcrumbs.tsx "src/app/(shop)/category/[slug]/page.tsx"
git commit -m "feat(storefront): category PLP with breadcrumbs + BreadcrumbList JSON-LD

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Search — `/search` page + suggest BFF + header autocomplete

**Why:** real search uses the trigram `/search/` endpoint (not the naive `?q=` on `/products/`). The page is server-rendered (crawlable results) but **noindex,follow** (thin/duplicate content policy; it stays out of the sitemap too). The header SearchBar upgrades to an accessible debounced autocomplete backed by a suggest BFF that forwards the client IP (the backend throttles suggest 60/min/IP — proxying from one server IP would count all users as one, the exact problem Plan-12 D5 solved for newsletter).

**Files:**
- Create: `storefront/src/app/api/search/suggest/route.ts`
- Modify: `storefront/src/components/layout/SearchBar.tsx` (autocomplete upgrade)
- Modify: `storefront/src/app/(shop)/search/page.tsx` (replace skeleton)
- Test: `storefront/src/app/api/search/__tests__/suggest.test.ts`

- [ ] **Step 1: Write the failing suggest BFF test**

`storefront/src/app/api/search/__tests__/suggest.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["country", "GB"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET } from "@/app/api/search/suggest/route";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("country", "GB"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status: 200, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("suggest BFF", () => {
  it("forwards q, the country cookie, and the caller IP", async () => {
    const f = upstream([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }]);
    const res = await GET(new Request("http://localhost:3000/api/search/suggest?q=rad", {
      headers: { "x-forwarded-for": "203.0.113.9" },
    }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/search/suggest/?q=rad");
    const h = new Headers((init as RequestInit).headers);
    expect(h.get("X-Country")).toBe("GB");
    expect(h.get("X-Forwarded-For")).toBe("203.0.113.9");
    expect(await res.json()).toEqual([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }]);
  });

  it("short-circuits an empty q without an upstream call", async () => {
    const f = upstream([]);
    const res = await GET(new Request("http://localhost:3000/api/search/suggest?q="));
    expect(await res.json()).toEqual([]);
    expect(f).not.toHaveBeenCalled();
  });
});
```

Run: `npm run test -- --run src/app/api/search` — expected FAIL.

- [ ] **Step 2: Implement the suggest BFF**

`storefront/src/app/api/search/suggest/route.ts`:

```ts
import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Debounced-autocomplete proxy. Forwards the caller's IP so the backend's
 * 60/min/IP suggest throttle stays per-user (prod proxy-trust note: Plan-02/22). */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") ?? "").trim();
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
  if (!q) return json([]);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const ip = req.headers.get("x-forwarded-for") ?? "";
  try {
    const data = await apiFetch(`/search/suggest/?q=${encodeURIComponent(q)}`, {
      country, cache: "no-store",
      headers: ip ? { "X-Forwarded-For": ip } : {},
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) return json([]); // throttled -> quiet
    return json([], 200); // suggestions are best-effort; never surface errors
  }
}
```

Run the tests — expected PASS.

- [ ] **Step 3: Upgrade the header SearchBar to an accessible autocomplete**

Replace `storefront/src/components/layout/SearchBar.tsx` (keeps the existing submit → `/search?q=` behaviour; adds a debounced combobox — ARIA pattern: `role="combobox"` input + `role="listbox"` popup):

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface Suggestion { name: string; slug: string }

export function SearchBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const debounce = useRef<ReturnType<typeof setTimeout>>(undefined);
  const rootRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    clearTimeout(debounce.current);
    if (q.trim().length < 2) { setItems([]); setOpen(false); return; }
    debounce.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/suggest?q=${encodeURIComponent(q.trim())}`);
        const data: Suggestion[] = res.ok ? await res.json() : [];
        setItems(data); setOpen(data.length > 0); setActive(-1);
      } catch { setItems([]); }
    }, 300);
    return () => clearTimeout(debounce.current);
  }, [q]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
    else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); setOpen(false); router.push(`/product/${items[active].slug}`);
    } else if (e.key === "Escape") setOpen(false);
  }

  return (
    <form
      ref={rootRef}
      role="search"
      className="relative hidden flex-1 md:block"
      onSubmit={(e) => {
        e.preventDefault(); setOpen(false);
        if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
      }}
    >
      <label className="sr-only" htmlFor="site-search">Search products</label>
      <input
        id="site-search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
        role="combobox" aria-expanded={open} aria-controls="search-listbox" aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `search-opt-${active}` : undefined}
        placeholder="Search products…" autoComplete="off"
        className="w-full rounded-full border border-line bg-surface px-4 py-2 text-sm"
      />
      {open && (
        <ul id="search-listbox" role="listbox" aria-label="Product suggestions"
          className="absolute z-50 mt-2 w-full overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-lg">
          {items.map((s, i) => (
            <li key={s.slug} id={`search-opt-${i}`} role="option" aria-selected={i === active}>
              <button type="button"
                className={`block w-full px-4 py-2.5 text-left text-sm ${i === active ? "bg-beige" : "hover:bg-beige"}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => { setOpen(false); router.push(`/product/${s.slug}`); }}>
                {s.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
```

- [ ] **Step 4: The `/search` page**

Replace `storefront/src/app/(shop)/search/page.tsx` (reuses the PLP grid/pagination; its own in-stock toggle + sort because the search endpoint's param names differ — `sort`, `in_stock`):

```tsx
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { searchProducts } from "@/lib/catalog";
import { pageMetadata } from "@/lib/seo";
import { ProductGrid } from "@/components/plp/ProductGrid";

type Search = Promise<Record<string, string | string[] | undefined>>;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const q = first((await searchParams).q) ?? "";
  return pageMetadata({
    title: q ? `Search: ${q}` : "Search",
    description: "Search the Toke Cosmetics range.",
    path: "/search",
    noindex: true, // thin-content policy; /search is also excluded from the sitemap
  });
}

export default async function SearchPage({ searchParams }: { searchParams: Search }) {
  const raw = await searchParams;
  const q = (first(raw.q) ?? "").trim();
  const pageNum = Math.max(1, Number(first(raw.page)) || 1);
  const inStock = first(raw.in_stock) === "1" ? ("1" as const) : undefined;
  const sortRaw = first(raw.sort);
  const sort = sortRaw === "price_asc" || sortRaw === "price_desc" || sortRaw === "newest"
    ? sortRaw : undefined;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;

  const page = q
    ? await searchProducts({ q, page: pageNum, in_stock: inStock, sort }, country)
        .catch(() => ({ count: 0, next: null, previous: null, results: [] }))
    : { count: 0, next: null, previous: null, results: [] };

  const baseQs = (over: Record<string, string | undefined>) => {
    const qs = new URLSearchParams();
    const merged = { q, in_stock: inStock, sort, ...over };
    for (const [k, v] of Object.entries(merged)) if (v) qs.set(k, v);
    return `/search?${qs.toString()}`;
  };
  const pages = Math.ceil(page.count / 24);

  return (
    <section className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">
        {q ? <>Results for “{q}”</> : "Search"}
      </h1>
      {q && (
        <form method="GET" action="/search" className="mt-6 flex flex-wrap items-center gap-4 text-sm">
          <input type="hidden" name="q" value={q} />
          <label className="flex items-center gap-2">
            <input type="checkbox" name="in_stock" value="1" defaultChecked={inStock === "1"} />
            In stock only
          </label>
          <label className="text-muted">
            Sort{" "}
            <select name="sort" defaultValue={sort ?? ""} className="rounded-md border border-line bg-surface px-2 py-1.5 text-foreground">
              <option value="">Relevance</option>
              <option value="newest">Newest</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
            </select>
          </label>
          <button className="rounded-full bg-accent px-5 py-2 font-medium text-surface hover:bg-accent-strong">Apply</button>
          <span className="ml-auto text-muted" aria-live="polite">{page.count} results</span>
        </form>
      )}
      <div className="mt-6">
        {q
          ? <ProductGrid products={page.results} />
          : <p className="text-muted">Type in the search bar above to find products.</p>}
      </div>
      {pages > 1 && (
        <nav aria-label="Pagination" className="mt-10 flex items-center justify-center gap-2">
          {pageNum > 1 && <a rel="prev" className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent" href={baseQs({ page: String(pageNum - 1) })}>← Prev</a>}
          <span className="px-3 text-sm text-muted">Page {pageNum} of {pages}</span>
          {pageNum < pages && <a rel="next" className="rounded-full border border-line px-4 py-2 text-sm hover:border-accent" href={baseQs({ page: String(pageNum + 1) })}>Next →</a>}
        </nav>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Build + eyeball**

```bash
npm run test -- --run src/app/api/search
npm run build && npm run dev
```
Type "rad" in the header search: after ~300 ms a dropdown lists "Radiance Glow Serum"; arrow-down + Enter navigates to the PDP skeleton; Escape closes; submitting goes to `/search?q=rad` with results, in-stock toggle and sort working via URL params. View source of `/search?q=rad`: `<meta name="robots" content="noindex, follow">` (exact attribute rendering per the bundled metadata docs).

- [ ] **Step 6: Commit**

```bash
git add src/app/api/search src/components/layout/SearchBar.tsx "src/app/(shop)/search/page.tsx"
git commit -m "feat(storefront): search page + suggest BFF + accessible header autocomplete

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: PDP part 1 — gallery, variant picker, buy-box display, accordions, delivery line, full PDP SEO

**Why:** the Amazon-pattern PDP (master Decision 14): left gallery with zoom, right buy-box card. This task builds everything that *displays* (price, compare-at, stars, variant picker, stock state, delivery estimate line, qty selector UI, accordion sections) plus the PDP's complete SEO (metadata from product seo fields, Product + BreadcrumbList + FAQPage JSON-LD). The *actions* (Add to Cart / Buy Now / reviews / related / recently-viewed) land in Task 12 — the buttons render disabled-less but wire up next task.

**Files:**
- Create: `storefront/src/lib/delivery-estimates.ts` (+ test)
- Create: `storefront/src/components/product/PdpContext.tsx`, `ProductGallery.tsx`, `VariantPicker.tsx`, `QtySelector.tsx`, `PdpAccordions.tsx`, `BuyBox.tsx`
- Modify: `storefront/src/app/(shop)/product/[slug]/page.tsx` (replace skeleton)
- Test: `storefront/src/lib/__tests__/delivery-estimates.test.ts`, `storefront/src/components/product/__tests__/variantPick.test.ts`

- [ ] **Step 1: Delivery estimate copy (D5) — failing test first**

`storefront/src/lib/__tests__/delivery-estimates.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";

describe("deliveryEstimateFor", () => {
  it("has copy for every live market", () => {
    for (const code of ["NG", "GB", "US", "CA"]) {
      expect(deliveryEstimateFor(code)).toBeTruthy();
    }
  });
  it("falls back to the international line for ZZ/unknown", () => {
    expect(deliveryEstimateFor("ZZ")).toMatch(/international/i);
    expect(deliveryEstimateFor("FR")).toMatch(/international/i);
  });
});
```

`storefront/src/lib/delivery-estimates.ts`:

```ts
/** Static per-country delivery lines (Plan-13 D5). The delivery-options endpoint
 * needs an authed user + a cart with lines, so a live PDP quote is impossible until
 * Plan-14 checkout. Hammed owns this copy — edit freely. RoW quotes after payment
 * is the Plan-14a flow; the ZZ line must NOT promise a price. */
const ESTIMATES: Record<string, string> = {
  NG: "Delivery in Nigeria: 1–3 days, from ₦1,500",
  GB: "Delivery to the UK: 5–10 business days, calculated at checkout",
  US: "Delivery to the US: 5–10 business days, calculated at checkout",
  CA: "Delivery to Canada: 5–10 business days, calculated at checkout",
};
const INTERNATIONAL = "International delivery: quoted after checkout";

export function deliveryEstimateFor(countryCode: string): string {
  return ESTIMATES[countryCode] ?? INTERNATIONAL;
}
```

Run → red → implement → green (`npm run test -- --run src/lib/__tests__/delivery-estimates.test.ts`).

- [ ] **Step 2: Variant selection logic — failing test first**

Selection rules live in a pure helper so they're testable without rendering: initial = first in-stock default-ish variant; picking updates price/sku/stock.

`storefront/src/components/product/__tests__/variantPick.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { initialVariant } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

const v = (id: number, in_stock: boolean, price = true): Variant => ({
  id, sku: `S${id}`, name: `${id}0ml`, option_values: { Size: `${id}0ml` },
  in_stock, low_stock: false,
  price: price ? { amount: "1000.00", compare_at: null, currency: "NGN",
                   tax_rate: "0.00", prices_include_tax: true } : null,
});

describe("initialVariant", () => {
  it("prefers the first in-stock, priced variant", () => {
    expect(initialVariant([v(1, false), v(2, true)])?.id).toBe(2);
  });
  it("falls back to the first priced variant when all are out of stock", () => {
    expect(initialVariant([v(1, false), v(2, false)])?.id).toBe(1);
  });
  it("ignores unpriced variants; null when none priced", () => {
    expect(initialVariant([v(1, true, false)])).toBeNull();
  });
});
```

- [ ] **Step 3: PDP context + islands**

`storefront/src/components/product/PdpContext.tsx`:

```tsx
"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { Variant } from "@/lib/catalog";

/** Shared selected-variant state between the gallery (left column) and the buy box
 * (right column) — the two client islands of the PDP. */
export function initialVariant(variants: Variant[]): Variant | null {
  const priced = variants.filter((v) => v.price !== null);
  return priced.find((v) => v.in_stock) ?? priced[0] ?? null;
}

interface PdpState {
  variant: Variant | null;
  setVariant: (v: Variant) => void;
  qty: number;
  setQty: (n: number) => void;
}
const Ctx = createContext<PdpState | null>(null);

export function PdpProvider({ variants, children }: { variants: Variant[]; children: ReactNode }) {
  const [variant, setVariant] = useState<Variant | null>(() => initialVariant(variants));
  const [qty, setQty] = useState(1);
  return <Ctx.Provider value={{ variant, setVariant, qty, setQty }}>{children}</Ctx.Provider>;
}

export function usePdp(): PdpState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePdp must be used inside PdpProvider");
  return ctx;
}
```

`storefront/src/components/product/ProductGallery.tsx` (client — thumbnails + hover-zoom; native pinch on mobile; highlights the selected variant's image when `variant_id` matches):

```tsx
"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import type { ProductDetail } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { usePdp } from "@/components/product/PdpContext";

export function ProductGallery({ product }: { product: ProductDetail }) {
  const { variant } = usePdp();
  const images = product.images;
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState<{ x: number; y: number } | null>(null);

  // Variant picked -> jump to its image if one is linked.
  useEffect(() => {
    if (!variant) return;
    const i = images.findIndex((img) => img.variant_id === variant.id);
    if (i >= 0) setIndex(i);
  }, [variant, images]);

  const current = images[index];
  if (!current) {
    return <div className="aspect-[3/4] rounded-[var(--radius-card)] bg-beige" aria-hidden />;
  }
  return (
    <div>
      <div
        className="relative aspect-[3/4] cursor-zoom-in overflow-hidden rounded-[var(--radius-card)] bg-beige"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setZoom({ x: ((e.clientX - r.left) / r.width) * 100, y: ((e.clientY - r.top) / r.height) * 100 });
        }}
        onMouseLeave={() => setZoom(null)}
      >
        <Image
          key={current.url}
          src={mediaUrl(current.url)!} alt={current.alt || product.name} fill priority
          sizes="(max-width: 1024px) 100vw, 50vw"
          className="object-cover transition-transform duration-200"
          style={zoom ? { transform: "scale(1.8)", transformOrigin: `${zoom.x}% ${zoom.y}%` } : undefined}
        />
      </div>
      {images.length > 1 && (
        <div className="mt-3 flex gap-2 overflow-x-auto" role="tablist" aria-label="Product images">
          {images.map((img, i) => (
            <button key={img.url} role="tab" aria-selected={i === index}
              aria-label={`Image ${i + 1}`}
              onClick={() => setIndex(i)}
              className={`relative h-20 w-16 shrink-0 overflow-hidden rounded-md border-2 ${i === index ? "border-accent" : "border-transparent"}`}>
              <Image src={mediaUrl(img.url)!} alt="" fill sizes="64px" className="object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

`storefront/src/components/product/VariantPicker.tsx` (client):

```tsx
"use client";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  const { variant, setVariant } = usePdp();
  if (variants.length <= 1) return null;
  return (
    <fieldset className="mt-5">
      <legend className="text-sm font-medium">Size</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {variants.map((v) => {
          const selected = variant?.id === v.id;
          const disabled = v.price === null;
          return (
            <button key={v.id} type="button" onClick={() => setVariant(v)} disabled={disabled}
              aria-pressed={selected}
              className={`rounded-full border px-4 py-2 text-sm transition
                ${selected ? "border-accent bg-accent text-surface" : "border-line hover:border-accent"}
                ${disabled ? "cursor-not-allowed opacity-40" : ""}
                ${!v.in_stock && !disabled ? "line-through" : ""}`}>
              {v.name}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
```

`storefront/src/components/product/QtySelector.tsx` (client):

```tsx
"use client";
import { usePdp } from "@/components/product/PdpContext";

const MAX_QTY = 10; // UI cap; the server re-caps against real stock on add

export function QtySelector() {
  const { qty, setQty } = usePdp();
  return (
    <div className="mt-5 inline-flex items-center rounded-full border border-line">
      <button type="button" aria-label="Decrease quantity" disabled={qty <= 1}
        onClick={() => setQty(Math.max(1, qty - 1))}
        className="px-4 py-2 text-lg disabled:opacity-30">−</button>
      <span aria-live="polite" className="w-10 text-center text-sm font-medium">{qty}</span>
      <button type="button" aria-label="Increase quantity" disabled={qty >= MAX_QTY}
        onClick={() => setQty(Math.min(MAX_QTY, qty + 1))}
        className="px-4 py-2 text-lg disabled:opacity-30">+</button>
    </div>
  );
}
```

`storefront/src/components/product/PdpAccordions.tsx` (server — native `<details>`: accessible, zero JS):

```tsx
import type { ProductDetail } from "@/lib/catalog";

/** Description / ingredients / directions / warnings / FAQs straight from product
 * fields (master spec). Native details/summary — keyboard + SR support for free.
 * `description` is backend-authored rich HTML (trusted admin content). */
export function PdpAccordions({ product }: { product: ProductDetail }) {
  const sections: { title: string; html?: string; text?: string }[] = [
    { title: "Description", html: product.description },
    { title: "Ingredients", text: product.ingredients },
    { title: "How to use", text: product.directions },
    { title: "Warnings", text: product.warnings },
  ];
  return (
    <div className="mt-10 divide-y divide-line border-y border-line">
      {sections.filter((s) => s.html || s.text).map((s, i) => (
        <details key={s.title} open={i === 0} className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium marker:hidden">
            {s.title}
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          {s.html
            ? <div className="prose-sm mt-3 max-w-none leading-relaxed text-muted"
                dangerouslySetInnerHTML={{ __html: s.html }} />
            : <p className="mt-3 leading-relaxed text-muted">{s.text}</p>}
        </details>
      ))}
      {product.faqs.length > 0 && (
        <details className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            FAQs
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          <dl className="mt-3 space-y-4">
            {product.faqs.map((f) => (
              <div key={f.q}>
                <dt className="text-sm font-medium">{f.q}</dt>
                <dd className="mt-1 text-sm leading-relaxed text-muted">{f.a}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {product.specs.length > 0 && (
        <details className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            Details
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            {product.specs.map((s) => (
              <div key={s.label} className="contents">
                <dt className="text-muted">{s.label}</dt><dd>{s.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
```

`storefront/src/components/product/BuyBox.tsx` (client — Task 11 renders the display; the two buttons get their onClick wiring in Task 12, so for now they render with `disabled` and a `data-task12` marker):

```tsx
"use client";
import type { ProductDetail } from "@/lib/catalog";
import { PriceTag } from "@/components/product/PriceTag";
import { ReviewStars } from "@/components/product/ReviewStars";
import { VariantPicker } from "@/components/product/VariantPicker";
import { QtySelector } from "@/components/product/QtySelector";
import { usePdp } from "@/components/product/PdpContext";

export function BuyBox({ product, deliveryLine }: {
  product: ProductDetail; deliveryLine: string;
}) {
  const { variant } = usePdp();
  const price = variant?.price ?? null;
  return (
    <div className="rounded-[var(--radius-card)] bg-surface p-6 shadow-sm lg:sticky lg:top-24">
      {product.brand && (
        <p className="text-xs uppercase tracking-wide text-muted">{product.brand.name}</p>
      )}
      <h1 className="mt-1 font-display text-3xl leading-tight">{product.name}</h1>
      <div className="mt-2">
        <ReviewStars rating={product.rating_avg} count={product.rating_count} />
      </div>
      {price ? (
        <div className="mt-4">
          <PriceTag amount={price.amount} compareAt={price.compare_at} currency={price.currency} size="lg" />
        </div>
      ) : (
        <p className="mt-4 text-muted">Currently unavailable in your region.</p>
      )}
      <VariantPicker variants={product.variants} />
      {variant && (
        <p className="mt-4 text-sm" aria-live="polite">
          {!variant.in_stock
            ? <span className="font-medium text-muted">Out of stock</span>
            : variant.low_stock
              ? <span className="font-medium text-gold">Only a few left</span>
              : <span className="font-medium text-accent">In stock</span>}
        </p>
      )}
      <p className="mt-3 flex items-start gap-2 text-sm text-muted">
        <span aria-hidden>🚚</span>{deliveryLine}
      </p>
      <QtySelector />
      <div className="mt-6 space-y-3">
        {/* onClick wiring lands in Task 12 (cart-ui event + buy-now BFF). */}
        <button type="button" disabled data-task12="buy-now"
          className="w-full rounded-full bg-accent py-3.5 font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50">
          Buy Now
        </button>
        <button type="button" disabled data-task12="add-to-cart"
          className="w-full rounded-full border border-accent py-3.5 font-medium text-accent transition-colors hover:bg-accent/5 disabled:opacity-50">
          Add to Cart
        </button>
      </div>
      <p className="mt-4 text-center text-xs text-muted">Secure worldwide checkout · 14-day returns</p>
    </div>
  );
}
```

- [ ] **Step 4: Assemble the PDP page with full SEO**

Replace `storefront/src/app/(shop)/product/[slug]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getProduct, type ProductDetail } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";
import { fetchWithAuth, getAccessToken } from "@/lib/session";
import { breadcrumbJsonLd, faqJsonLd, pageMetadata, productJsonLd } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { Breadcrumbs } from "@/components/plp/Breadcrumbs";
import { PdpProvider } from "@/components/product/PdpContext";
import { ProductGallery } from "@/components/product/ProductGallery";
import { BuyBox } from "@/components/product/BuyBox";
import { PdpAccordions } from "@/components/product/PdpAccordions";

type Params = Promise<{ slug: string }>;

async function loadProduct(slug: string, country: string): Promise<ProductDetail | null> {
  try {
    return await getProduct(slug, country);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const product = await loadProduct(slug, country);
  if (!product) return { title: "Product not found" };
  return pageMetadata({
    title: product.seo_title || product.name,
    description: product.seo_description || product.short_description,
    path: `/product/${slug}`,
    image: mediaUrl(product.images[0]?.url ?? null),
  });
}

/** Personalised delivery label: "Delivery to <Ikeja>: …" for logged-in users with a
 * default address; the generic country line otherwise (D5). Never throws. */
async function deliveryLineFor(country: string): Promise<string> {
  const generic = deliveryEstimateFor(country);
  if (!(await getAccessToken())) return generic;
  try {
    const addresses = await fetchWithAuth<
      { label: string; city_text: string; is_default_shipping: boolean }[]
    >("/me/addresses/", { cache: "no-store" });
    const def = addresses.find((a) => a.is_default_shipping) ?? addresses[0];
    const place = def?.city_text || def?.label;
    return place ? `${generic.replace(/^Delivery[^:]*:/, `Delivery to ${place}:`)}` : generic;
  } catch {
    return generic;
  }
}

export default async function ProductPage({ params }: { params: Params }) {
  const { slug } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const product = await loadProduct(slug, country);
  if (!product) notFound();
  const deliveryLine = await deliveryLineFor(country);

  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Shop", path: "/products" },
    { name: product.name, path: `/product/${slug}` },
  ];

  return (
    <section className="mx-auto max-w-7xl px-4 py-8">
      <JsonLd data={productJsonLd(product, `/product/${slug}`)} />
      <JsonLd data={breadcrumbJsonLd(crumbs)} />
      {product.faqs.length > 0 && <JsonLd data={faqJsonLd(product.faqs)} />}
      <Breadcrumbs crumbs={crumbs} />
      <PdpProvider variants={product.variants}>
        <div className="mt-6 grid gap-10 lg:grid-cols-2">
          <ProductGallery product={product} />
          <div>
            <BuyBox product={product} deliveryLine={deliveryLine} />
          </div>
        </div>
      </PdpProvider>
      <div className="mx-auto max-w-3xl">
        <PdpAccordions product={product} />
      </div>
      {/* Task 12 appends: ReviewList, RelatedProducts, RecentlyViewed */}
    </section>
  );
}
```

- [ ] **Step 5: Run tests + build + eyeball**

```bash
npm run test -- --run src/lib/__tests__/delivery-estimates.test.ts src/components/product/__tests__
npm run build && npm run dev
```
Open `/product/radiance-glow-serum`: gallery zooms on hover and switches via thumbnails; picking "50ml" updates the price (~1.6×) and SKU-dependent stock line; the low-stock product (`/product/clear-skin-turmeric-bar`) shows "Only a few left" in gold; the out-of-stock product (`/product/black-soap-deep-cleanse`) shows "Out of stock"; delivery line matches the country cookie (switch NG→GB in the header and watch it change); accordions expand/collapse with keyboard. Switch to GB: prices show £ amounts. View source: three JSON-LD blocks (Product with offers + AggregateRating, BreadcrumbList, FAQPage), `<title>` from seo_title/name, canonical absolute.

- [ ] **Step 6: Commit**

```bash
git add src/lib/delivery-estimates.ts src/lib/__tests__/delivery-estimates.test.ts src/components/product "src/app/(shop)/product/[slug]/page.tsx"
git commit -m "feat(storefront): PDP — gallery, variant picker, buy-box display, accordions, full JSON-LD

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: PDP part 2 — Add to Cart, Buy Now (D6), reviews, related, recently-viewed, revalidate route (D7)

**Why:** the PDP's actions and below-the-fold content. Add to Cart uses the existing `useCart().addItem` and must **open the cart drawer** — the drawer currently opens only from the header button's local state, so a tiny event bus decouples them. Buy Now proxies the authed express-cart endpoint. Recently-viewed is a localStorage client strip (master spec). The revalidate route completes the storefront half of on-demand invalidation.

**Files:**
- Create: `storefront/src/lib/cart-ui.ts`, `storefront/src/lib/recently-viewed.ts` (+ tests)
- Create: `storefront/src/app/api/checkout/buy-now/route.ts` (+ test)
- Create: `storefront/src/app/api/revalidate/route.ts` (+ test)
- Create: `storefront/src/components/product/BuyButtons.tsx`, `ReviewList.tsx`, `RelatedProducts.tsx`, `RecentlyViewed.tsx`, `RecentlyViewedTracker.tsx`
- Modify: `storefront/src/components/product/BuyBox.tsx` (swap disabled buttons for `BuyButtons`), `storefront/src/components/layout/CartButton.tsx` (listen for the open event), `storefront/src/app/(shop)/product/[slug]/page.tsx` (append sections), `storefront/.env.local.example` + `.env.local` (`REVALIDATE_SECRET`)

- [ ] **Step 1: Cart-UI event bus — failing test first**

`storefront/src/lib/__tests__/cart-ui.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { CART_OPEN_EVENT, openCartDrawer, onCartDrawerOpen } from "@/lib/cart-ui";

describe("cart-ui event bus", () => {
  it("openCartDrawer dispatches; onCartDrawerOpen subscribes and unsubscribes", () => {
    const cb = vi.fn();
    const off = onCartDrawerOpen(cb);
    openCartDrawer();
    expect(cb).toHaveBeenCalledTimes(1);
    off();
    openCartDrawer();
    expect(cb).toHaveBeenCalledTimes(1);
  });
  it("uses a namespaced event name", () => {
    expect(CART_OPEN_EVENT).toBe("toke:cart-open");
  });
});
```

`storefront/src/lib/cart-ui.ts`:

```ts
/** Micro event-bus so ANY island (PDP buy box, future quick-add) can open the
 * header's cart drawer without prop-drilling through the server layout. */
export const CART_OPEN_EVENT = "toke:cart-open";

export function openCartDrawer(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(CART_OPEN_EVENT));
}

export function onCartDrawerOpen(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = () => cb();
  window.addEventListener(CART_OPEN_EVENT, handler);
  return () => window.removeEventListener(CART_OPEN_EVENT, handler);
}
```

Run red → implement → green. Then subscribe in `storefront/src/components/layout/CartButton.tsx` — add inside the component:

```tsx
  useEffect(() => onCartDrawerOpen(() => setOpen(true)), []);
```

(with `import { useEffect } from "react";` and `import { onCartDrawerOpen } from "@/lib/cart-ui";`).

- [ ] **Step 2: Buy-Now BFF — failing test first**

`storefront/src/app/api/checkout/__tests__/buy-now.test.ts` (same mock pattern as the wishlist test):

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { POST } from "@/app/api/checkout/buy-now/route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK"); store.set("country", "NG");
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const req = (body: unknown) => new Request("http://localhost:3000/api/checkout/buy-now", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});

describe("buy-now BFF", () => {
  it("forwards variant+qty with Bearer and country; returns the express cart", async () => {
    const f = upstream(200, { id: "c1", kind: "express", items: [{ variant_id: 5 }] });
    const res = await POST(req({ variant_id: 5, quantity: 2 }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/buy-now/");
    const h = new Headers((init as RequestInit).headers);
    expect(h.get("Authorization")).toBe("Bearer TOK");
    expect(h.get("X-Country")).toBe("NG");
    expect((await res.json()).kind).toBe("express");
  });

  it("401 without a session, no upstream call (guest flow is client-side, D6)", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(req({ variant_id: 5, quantity: 1 }));
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects a missing variant_id with 400", async () => {
    const res = await POST(req({ quantity: 1 }));
    expect(res.status).toBe(400);
  });
});
```

`storefront/src/app/api/checkout/buy-now/route.ts`:

```ts
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Buy-Now proxy (Plan-13 D6). Authed-only by backend design: creates/refills the
 * user's express cart with exactly this item. Guests never reach here — the client
 * stashes intent and routes to /login. NOT a checkout placement — Plan-14 owns that. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  if (!body.variant_id) return json({ variant_id: ["This field is required."] }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const cart = await fetchWithAuth("/checkout/buy-now/", {
      method: "POST", country,
      body: { variant_id: body.variant_id, quantity: body.quantity ?? 1 },
    });
    return json(cart);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

Run red → implement → green: `npm run test -- --run src/app/api/checkout`.

- [ ] **Step 3: The live buy buttons**

`storefront/src/components/product/BuyButtons.tsx`:

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useCart } from "@/hooks/useCart";
import { openCartDrawer } from "@/lib/cart-ui";
import { usePdp } from "@/components/product/PdpContext";

export const BUYNOW_INTENT_KEY = "toke-buynow-intent";

/** Amazon-pattern pair (Decision 14): Buy Now = primary (straight to checkout),
 * Add to Cart = secondary (opens the drawer). Guest Buy Now stashes intent and
 * routes to /login — the resume-into-checkout path is Plan-14 (D6). */
export function BuyButtons() {
  const { variant, qty } = usePdp();
  const { addItem } = useCart();
  const router = useRouter();
  const [busy, setBusy] = useState<"buy" | "add" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const disabled = !variant || !variant.in_stock || variant.price === null;

  async function addToCart() {
    if (!variant) return;
    setBusy("add"); setError(null);
    try {
      await addItem.mutateAsync({ variantId: variant.id, quantity: qty });
      openCartDrawer();
    } catch {
      setError("Could not add to bag — please try again.");
    } finally { setBusy(null); }
  }

  async function buyNow() {
    if (!variant) return;
    setBusy("buy"); setError(null);
    try {
      const res = await fetch("/api/checkout/buy-now", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: variant.id, quantity: qty }),
      });
      if (res.status === 401) {
        sessionStorage.setItem(BUYNOW_INTENT_KEY,
          JSON.stringify({ variant_id: variant.id, quantity: qty }));
        router.push("/login?next=/checkout");
        return;
      }
      if (!res.ok) throw new Error();
      router.push("/checkout");
    } catch {
      setError("Buy Now is unavailable right now — try Add to Cart.");
      setBusy(null);
    }
  }

  return (
    <div className="mt-6 space-y-3">
      <button type="button" onClick={buyNow} disabled={disabled || busy !== null}
        className="w-full rounded-full bg-accent py-3.5 font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50">
        {busy === "buy" ? "Preparing checkout…" : "Buy Now"}
      </button>
      <button type="button" onClick={addToCart} disabled={disabled || busy !== null}
        className="w-full rounded-full border border-accent py-3.5 font-medium text-accent transition-colors hover:bg-accent/5 disabled:opacity-50">
        {busy === "add" ? "Adding…" : "Add to Cart"}
      </button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>
  );
}
```

In `BuyBox.tsx`, replace the two disabled placeholder buttons (the `data-task12` block) with `<BuyButtons />` (import it).

- [ ] **Step 4: Reviews, related, recently-viewed**

`storefront/src/components/product/ReviewList.tsx` (server):

```tsx
import { getReviews } from "@/lib/catalog";
import { ReviewStars } from "@/components/product/ReviewStars";

/** Approved reviews. Every one is a verified purchase by backend construction
 * (only verified purchasers can post), so the badge is unconditional. */
export async function ReviewList({ slug, ratingAvg, ratingCount }: {
  slug: string; ratingAvg: string; ratingCount: number;
}) {
  const reviews = await getReviews(slug).catch(() => []);
  if (reviews.length === 0) return null;
  return (
    <section aria-labelledby="reviews-heading" className="mx-auto mt-16 max-w-3xl">
      <div className="flex items-baseline justify-between">
        <h2 id="reviews-heading" className="font-display text-2xl">Customer reviews</h2>
        <ReviewStars rating={ratingAvg} count={ratingCount} />
      </div>
      <ul className="mt-6 space-y-6">
        {reviews.map((r) => (
          <li key={`${r.author}-${r.created_at}`} className="rounded-[var(--radius-card)] bg-surface p-5 shadow-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span aria-label={`${r.rating} out of 5 stars`} className="text-gold" role="img">
                {"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)}
              </span>
              <span className="rounded-full bg-accent/10 px-2.5 py-0.5 text-xs font-medium text-accent">
                Verified purchase
              </span>
            </div>
            {r.title && <h3 className="mt-2 font-medium">{r.title}</h3>}
            <p className="mt-1.5 text-sm leading-relaxed text-muted">{r.body}</p>
            <p className="mt-3 text-xs text-muted">
              {r.author} · {new Date(r.created_at).toLocaleDateString("en", { year: "numeric", month: "long" })}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

`storefront/src/components/product/RelatedProducts.tsx` (server — reuses the home Carousel):

```tsx
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { Carousel } from "@/components/home/Carousel";

export function RelatedProducts({ products }: { products: ProductCardData[] }) {
  if (products.length === 0) return null;
  return (
    <section aria-label="You may also like" className="mt-16">
      <h2 className="font-display text-2xl">You may also like</h2>
      <div className="mt-6">
        <Carousel label="Related products">
          {products.map((p) => (
            <div key={p.slug} className="w-[60vw] shrink-0 snap-start sm:w-64">
              <ProductCard product={p} />
            </div>
          ))}
        </Carousel>
      </div>
    </section>
  );
}
```

Recently-viewed lib — failing test first. `storefront/src/lib/__tests__/recently-viewed.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { pushRecentlyViewed, listRecentlyViewed, RECENT_KEY } from "@/lib/recently-viewed";

const entry = (slug: string) => ({
  slug, name: slug, image: null, from_price: "100.00", currency: "NGN",
});

describe("recently-viewed", () => {
  beforeEach(() => localStorage.clear());

  it("stores newest-first and dedupes by slug", () => {
    pushRecentlyViewed(entry("a"));
    pushRecentlyViewed(entry("b"));
    pushRecentlyViewed(entry("a"));
    expect(listRecentlyViewed().map((e) => e.slug)).toEqual(["a", "b"]);
  });
  it("caps at 8 entries", () => {
    for (let i = 0; i < 12; i++) pushRecentlyViewed(entry(`p${i}`));
    expect(listRecentlyViewed()).toHaveLength(8);
    expect(listRecentlyViewed()[0].slug).toBe("p11");
  });
  it("survives corrupt storage", () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    expect(listRecentlyViewed()).toEqual([]);
  });
});
```

`storefront/src/lib/recently-viewed.ts`:

```ts
/** localStorage ring buffer for the PDP "recently viewed" strip (master spec —
 * client-side only, nothing tracked server-side). Snapshots are display-only;
 * prices may go stale, which is acceptable for this strip. */
export const RECENT_KEY = "toke-recently-viewed";
const MAX = 8;

export interface RecentEntry {
  slug: string; name: string; image: string | null;
  from_price: string | null; currency: string;
}

export function listRecentlyViewed(): RecentEntry[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(raw) ? (raw as RecentEntry[]) : [];
  } catch {
    return [];
  }
}

export function pushRecentlyViewed(entry: RecentEntry): void {
  if (typeof localStorage === "undefined") return;
  const next = [entry, ...listRecentlyViewed().filter((e) => e.slug !== entry.slug)].slice(0, MAX);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
}
```

`storefront/src/components/product/RecentlyViewedTracker.tsx` (client, renders nothing — records the current PDP) and `RecentlyViewed.tsx` (client strip):

```tsx
"use client";
import { useEffect } from "react";
import { pushRecentlyViewed, type RecentEntry } from "@/lib/recently-viewed";

export function RecentlyViewedTracker({ entry }: { entry: RecentEntry }) {
  useEffect(() => { pushRecentlyViewed(entry); }, [entry]);
  return null;
}
```

```tsx
"use client";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { listRecentlyViewed, type RecentEntry } from "@/lib/recently-viewed";
import { formatMoney, symbolFor } from "@/lib/country";

export function RecentlyViewed({ excludeSlug }: { excludeSlug: string }) {
  const [items, setItems] = useState<RecentEntry[]>([]);
  useEffect(() => {
    setItems(listRecentlyViewed().filter((e) => e.slug !== excludeSlug).slice(0, 6));
  }, [excludeSlug]);
  if (items.length === 0) return null;
  return (
    <section aria-label="Recently viewed" className="mt-16">
      <h2 className="font-display text-2xl">Recently viewed</h2>
      <div className="mt-6 flex gap-4 overflow-x-auto pb-2">
        {items.map((e) => (
          <Link key={e.slug} href={`/product/${e.slug}`} className="w-36 shrink-0">
            <div className="relative aspect-[3/4] overflow-hidden rounded-[var(--radius-card)] bg-beige">
              {e.image && <Image src={e.image} alt={e.name} fill sizes="144px" className="object-cover" />}
            </div>
            <p className="mt-2 line-clamp-2 text-xs">{e.name}</p>
            {e.from_price && (
              <p className="text-xs font-medium">
                {formatMoney(e.from_price, e.currency, symbolFor(e.currency))}
              </p>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}
```

Append to the PDP page (inside the outer `<section>`, after the accordions `div`):

```tsx
      <RecentlyViewedTracker entry={{
        slug, name: product.name,
        image: mediaUrl(product.images[0]?.url ?? null),
        from_price: product.variants.find((v) => v.price)?.price?.amount ?? null,
        currency: product.variants.find((v) => v.price)?.price?.currency ?? "NGN",
      }} />
      <ReviewList slug={slug} ratingAvg={product.rating_avg} ratingCount={product.rating_count} />
      <RelatedProducts products={product.related} />
      <RecentlyViewed excludeSlug={slug} />
```

(with the matching imports).

- [ ] **Step 5: Revalidate route (D7) — failing test first**

`storefront/src/app/api/revalidate/__tests__/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";

const revalidateTag = vi.fn();
vi.mock("next/cache", () => ({ revalidateTag: (t: string) => revalidateTag(t) }));

import { POST } from "@/app/api/revalidate/route";

const req = (body: unknown, secret?: string) =>
  new Request("http://localhost:3000/api/revalidate", {
    method: "POST",
    headers: { "content-type": "application/json",
               ...(secret ? { "x-revalidate-secret": secret } : {}) },
    body: JSON.stringify(body),
  });

describe("revalidate route", () => {
  beforeEach(() => { process.env.REVALIDATE_SECRET = "s3cret"; revalidateTag.mockClear(); });

  it("revalidates the given tags with the right secret", async () => {
    const res = await POST(req({ tags: ["catalog", "product:serum"] }, "s3cret"));
    expect(res.status).toBe(200);
    expect(revalidateTag).toHaveBeenCalledWith("catalog");
    expect(revalidateTag).toHaveBeenCalledWith("product:serum");
  });
  it("401 on a wrong/missing secret, nothing revalidated", async () => {
    const res = await POST(req({ tags: ["catalog"] }, "wrong"));
    expect(res.status).toBe(401);
    expect(revalidateTag).not.toHaveBeenCalled();
  });
  it("400 when tags is not a non-empty string array", async () => {
    const res = await POST(req({ tags: [] }, "s3cret"));
    expect(res.status).toBe(400);
  });
});
```

`storefront/src/app/api/revalidate/route.ts`:

```ts
import { revalidateTag } from "next/cache";

/** On-demand data-cache invalidation (Plan-13 D7 — the storefront half). Django's
 * post_save webhook will call this in production (deferred to Plan-22); until then
 * it can be driven manually. Tags: "catalog" (lists/tree/brands), "product:<slug>".
 * timingSafeEqual is overkill for a long random secret; simple compare is fine. */
export async function POST(req: Request) {
  const secret = process.env.REVALIDATE_SECRET;
  const given = req.headers.get("x-revalidate-secret");
  if (!secret || given !== secret) {
    return Response.json({ detail: "Invalid secret." }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const tags: unknown = body?.tags;
  if (!Array.isArray(tags) || tags.length === 0 || !tags.every((t) => typeof t === "string")) {
    return Response.json({ detail: "tags must be a non-empty string array." }, { status: 400 });
  }
  for (const tag of tags as string[]) revalidateTag(tag);
  return Response.json({ revalidated: tags });
}
```

Add to `storefront/.env.local.example` and `.env.local`:

```bash
# Secret for POST /api/revalidate (on-demand cache invalidation). Generate a long
# random value for prod; Django will send it as X-Revalidate-Secret (Plan-22).
REVALIDATE_SECRET=dev-only-change-me
```

- [ ] **Step 6: Run everything, mutation-verify, verify live**

```bash
npm run test -- --run
npm run build
```
Expected: full suite green, clean build. Mutation-verify: in the buy-now route, delete the auth guard — the 401 test goes RED; revert. In `pushRecentlyViewed`, drop the `.slice(0, MAX)` — the cap test goes RED; revert.

Live check (backend + `npm run dev`, seeded): on a PDP, **Add to Cart** slides the drawer open with the correct line; qty selector value is respected. **Buy Now** logged-out → lands on `/login?next=/checkout` and `sessionStorage["toke-buynow-intent"]` holds the intent. Log in (`curl` flow from Plan-12 or the account flow), retry Buy Now → lands on the `/checkout` skeleton; `curl -s localhost:8000/api/v1/cart/ -H "Authorization: Bearer …"` style check optional — simpler: the backend admin or `manage.py shell` shows an `express` cart with exactly that item. Revalidate: `curl -X POST localhost:3000/api/revalidate -H "x-revalidate-secret: dev-only-change-me" -H "content-type: application/json" -d "{\"tags\":[\"catalog\"]}"` → `{"revalidated":["catalog"]}`.

- [ ] **Step 7: Commit**

```bash
git add src/lib/cart-ui.ts src/lib/recently-viewed.ts src/lib/__tests__ src/app/api/checkout src/app/api/revalidate src/components/product src/components/layout/CartButton.tsx "src/app/(shop)/product/[slug]/page.tsx" .env.local.example
git commit -m "feat(storefront): PDP actions — add-to-cart drawer, Buy Now BFF, reviews, related, recently-viewed, revalidate route

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: `sitemap.ts` + `robots.ts` + architecture docs (canonical policy, hreflang omission)

**Why:** the crawl-control layer. One `app/sitemap.ts` covering home, `/products`, every category, and every product (paging through the API); `app/robots.ts` per the master spec. The catalog is well under the 50k-URL sitemap limit — a single sitemap file is correct today; switch to `generateSitemaps()` sharding only when the catalog approaches ~10k URLs (leave that as a comment, not code — YAGNI). `/search` is noindexed (Task 10) and excluded here. The i18n stance (single locale, no hreflang) gets documented.

**Files:**
- Create: `storefront/src/app/sitemap.ts`, `storefront/src/app/robots.ts`
- Modify: `tokecosmetics-platform/docs/architecture.md` (append § Storefront catalog + SEO)

- [ ] **Step 1: Read the bundled conventions first**

Read `storefront/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/sitemap.md` and `robots.md`. Confirm the return types (`MetadataRoute.Sitemap`, `MetadataRoute.Robots`) and that the files serve at `/sitemap.xml` and `/robots.txt`.

- [ ] **Step 2: Implement `sitemap.ts`**

`storefront/src/app/sitemap.ts`:

```ts
import type { MetadataRoute } from "next";
import { flattenCategories, getCategoryTree, getProducts } from "@/lib/catalog";
import { absoluteUrl } from "@/lib/seo";
import { DEFAULT_COUNTRY } from "@/lib/country";

/** Single sitemap (catalog << 50k URLs; shard with generateSitemaps() only if the
 * catalog ever approaches ~10k). Uses the NG default market — URLs are country-
 * agnostic (one URL set; currency is an in-session choice, see architecture.md).
 * CMS pages (/page/*) join in Plan-19 when a pages API exists. /search and /cart
 * and /checkout are deliberately absent. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), changeFrequency: "daily", priority: 1 },
    { url: absoluteUrl("/products"), changeFrequency: "daily", priority: 0.9 },
  ];

  const tree = await getCategoryTree(DEFAULT_COUNTRY).catch(() => []);
  for (const cat of flattenCategories(tree)) {
    entries.push({
      url: absoluteUrl(`/category/${cat.slug}`),
      changeFrequency: "daily", priority: 0.8,
    });
  }

  // Page through /products/ (24/page). Hard cap of 100 pages (=2400 products) as a
  // runaway guard; revisit when the WP migration (Plan-21) lands the full catalog.
  let page = 1;
  for (;;) {
    const batch = await getProducts({ page, ordering: "newest" }, DEFAULT_COUNTRY)
      .catch(() => null);
    if (!batch) break;
    for (const p of batch.results) {
      entries.push({
        url: absoluteUrl(`/product/${p.slug}`),
        changeFrequency: "weekly", priority: 0.7,
      });
    }
    if (!batch.next || page >= 100) break;
    page += 1;
  }
  return entries;
}
```

- [ ] **Step 3: Implement `robots.ts`**

`storefront/src/app/robots.ts` (master spec: allow all; disallow `/checkout`, `/account`, `/api`; sitemap ref — `/cart` added for the same user-specific reason):

```ts
import type { MetadataRoute } from "next";
import { absoluteUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{
      userAgent: "*",
      allow: "/",
      disallow: ["/checkout", "/account", "/api/", "/cart"],
    }],
    sitemap: absoluteUrl("/sitemap.xml"),
  };
}
```

- [ ] **Step 4: Verify both endpoints**

```bash
npm run build && npm run dev
curl -s http://localhost:3000/robots.txt
curl -s http://localhost:3000/sitemap.xml | head -c 1500
```
Expected: robots.txt shows the four disallows + the absolute sitemap URL; sitemap.xml is valid XML containing `/`, `/products`, every `/category/...`, and ≥ 24 `/product/...` URLs (backend must be running). Paste the sitemap into an XML validator (or `python -c "import sys,xml.dom.minidom; xml.dom.minidom.parseString(sys.stdin.read())" < curl-output` style check) — well-formed.

- [ ] **Step 5: Document the SEO architecture**

Append to `tokecosmetics-platform/docs/architecture.md` a `## Storefront catalog + SEO (Plan-13)` section (~35 lines):
- **Canonical policy:** PLP canonicals keep only `page` (>1); any filter/sort param present → canonical is the bare base path. PDPs/home/category bases are self-canonical, always absolute.
- **hreflang deliberately omitted:** single locale (en), ONE URL set; country/currency is an in-session choice (cookie + `X-Country`), so there are no per-country URLs to alternate between (master spec §5).
- **Slug parity:** product/category slugs are used verbatim — they will be byte-identical to the migrated WP slugs (Plan-21/24 guarantee); the Plan-24 redirect middleware handles the old URL *shapes*. Never transform a slug in the storefront.
- **JSON-LD inventory:** Organization + WebSite/SearchAction (home), BreadcrumbList (category + PDP), Product/offers/AggregateRating + FAQPage (PDP). Emitted by `lib/seo.ts` builders through `<JsonLd>`.
- **Caching:** dynamic pages + tagged fetch data-cache (`catalog`, `product:<slug>`); `POST /api/revalidate` (secret header) → `revalidateTag`; Django webhook wiring deferred to Plan-22 (D7). `priceValidUntil` omitted (API exposes no sale windows).
- **Search:** `/search` is noindex,follow and absent from the sitemap.

- [ ] **Step 6: Commit**

```bash
git add src/app/sitemap.ts src/app/robots.ts ../docs/architecture.md
git commit -m "feat(storefront): sitemap + robots + SEO architecture docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: Verification checkpoint — suites, production build, Lighthouse, structured data, design walkthrough 🚦

**Why:** the master Plan-13 verification + checkpoint: prove SSR + JSON-LD with `curl`, Lighthouse mobile ≥ 95 with SEO 100 on home/PLP/PDP, structured-data validity, and a design walkthrough for Hammed. **No new feature code.** All interactive verification runs against a **production build (`npm start`)** — the Claude preview browser does not hydrate the Next dev server, and Lighthouse numbers only mean anything on a prod build anyway.

**Files:** none created (verification artefacts: `storefront/lighthouse-*.json`).

- [ ] **Step 1: Full suites + lint + clean build**

```bash
cd tokecosmetics-platform/storefront
npm run test -- --run      # every Vitest suite green
npm run lint               # clean
npm run build              # clean — no type errors, no build warnings you introduced
cd ../backend
uv run pytest -q           # backend still fully green (Tasks 1-2 regression)
```

- [ ] **Step 2: Production server + curl SSR/JSON-LD checks**

Terminal A: `cd backend && uv run python manage.py runserver 0.0.0.0:8000` (seeded). Terminal B: `cd storefront && npm start` (serves the production build on :3000). Then:

```bash
# PDP is fully server-rendered with all three JSON-LD blocks:
curl -s http://localhost:3000/product/radiance-glow-serum -o pdp.html
grep -c "application/ld+json" pdp.html          # -> 3 (Product, BreadcrumbList, FAQPage)
grep -o '"@type":"Product"' pdp.html            # present
grep -o "Radiance Glow Serum" pdp.html | head -1  # real content in the HTML, not hydrated later
# Home has Organization + WebSite:
curl -s http://localhost:3000/ | grep -c "application/ld+json"   # -> 2
# Category page:
curl -s http://localhost:3000/category/face | grep -o '"@type":"BreadcrumbList"'
# Canonicals:
curl -s "http://localhost:3000/category/face?brand=toke-naturals" | grep -o '<link rel="canonical"[^>]*>'
#   -> canonical ends exactly at /category/face (no query)
# Search noindex:
curl -s "http://localhost:3000/search?q=serum" | grep -io 'noindex[^"]*'
# Crawl-control:
curl -s http://localhost:3000/robots.txt
curl -s http://localhost:3000/sitemap.xml | head -c 800
```
Record each result.

- [ ] **Step 3: Structured-data validation**

Paste the saved `pdp.html` (and the home-page HTML) into the Schema.org validator at `https://validator.schema.org` (browser). Expected: **zero errors** for Product (with offers + aggregateRating), BreadcrumbList, FAQPage, Organization, WebSite. Screenshot the results. **Google's Rich Results Test needs a public URL** — it runs at the Vercel-preview moment (deployment plan); note that explicitly in the checkpoint message rather than skipping silently.

- [ ] **Step 4: Lighthouse (mobile) on the three page types**

Against the running **production** server:

```bash
npx --yes lighthouse http://localhost:3000/ --form-factor=mobile --screenEmulation.mobile --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lighthouse-home.json
npx --yes lighthouse http://localhost:3000/category/face --form-factor=mobile --screenEmulation.mobile --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lighthouse-plp.json
npx --yes lighthouse http://localhost:3000/product/radiance-glow-serum --form-factor=mobile --screenEmulation.mobile --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lighthouse-pdp.json
```
Extract the four scores from each JSON (`.categories.*.score`). **Gate: performance ≥ 95 and SEO = 100 on all three; accessibility ≥ 95.** If performance misses: the usual Plan-13 suspects are the hero image weight (SVG should be tiny — check it didn't get rasterised), non-lazy below-fold images (everything below the hero must be `loading="lazy"` or non-priority), and framer-motion leaking outside `LazyMotion`. Fix the cheap ones, re-run, and only then move on. Do not lower the gate.

- [ ] **Step 5: Driven walkthrough (production build)**

Using the Claude preview browser against `npm start` (NOT `npm run dev` — the preview browser does not hydrate the dev server), walk and record:
1. Home: all 15 sections, announcement rotation, header shrink, carousels, mobile 375px width (no horizontal scroll).
2. `/products` → filter by brand → price range → sort → page 2 → URL params update at every step; card hover swap.
3. `/category/face` → breadcrumb → child pill → `/category/serums`.
4. Search "rad" → suggestion dropdown → keyboard select → PDP.
5. PDP: variant switch (price + stock line change), zoom, accordions, Add to Cart → drawer opens with the line; recently-viewed strip appears on the *next* PDP visited.
6. Buy Now logged-out → `/login?next=/checkout` with the intent in sessionStorage; logged-in → `/checkout` skeleton + an `express` cart in the backend.
7. Country switch NG → GB on a PDP: prices flip to £, delivery line changes.
8. Keyboard-only pass on home + PDP: focus visible everywhere, drawer/dropdown escapable.

- [ ] **Step 6: Commit verification artefacts**

```bash
cd tokecosmetics-platform
git add storefront/lighthouse-home.json storefront/lighthouse-plp.json storefront/lighthouse-pdp.json
git commit -m "docs: Plan-13 verification artefacts (Lighthouse home/PLP/PDP)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 7: 🚦 CHECKPOINT — Hammed reviews look & feel + SEO evidence (BLOCKS merge + Plan-14)**

Stop. Present to Hammed, in plain language:
- The running homepage/PLP/PDP (screen-share or recording of the Step-5 walkthrough) — this is the "aesthetic, modern, best UI/UX" review against his Rhode/Aesop/Fenty/Typology/Sephora bar. Call out D4 explicitly: **all imagery is generated placeholder art; the design's final quality depends on his real photography.**
- The Lighthouse scores (three pages, four categories each) and the schema-validator screenshots. Note that Google's Rich Results Test + a Vercel preview run at deployment.
- The seven decisions D1–D7 as implemented, for retro sign-off of any he hadn't answered.
- Known gaps carried forward: guest Buy-Now resume (Plan-14), live delivery quotes (Plan-14), rating/availability PLP filters + category SEO fields (future backend), Django revalidate webhook + prod throttle/proxy config (Plan-22).

**Do not merge to main or start Plan-14 until Hammed signs off on the design.** On sign-off: merge `plan-13-storefront-catalog-seo` → `main` (no push without his say-so, per standing repo practice).

---

## Self-review notes (author checklist — delete on execution)

- **Spec coverage (master lines 919–941):** Home 15 sections → Tasks 6–7 (announcement=1, shrink-nav=2, hero=3, categories=4, concerns=5, story=6, best-sellers=7, banner=8, new-arrivals=9, why=10, testimonials=11, community=12, education=13, newsletter=14, footer=15). PLP filters/sort/pagination as URL params + hover second image + wishlist heart + compare-at → Tasks 5/8/9 (rating+availability filters flagged — backend gap). PDP Amazon buy box: gallery+zoom, price+compare-at, stars, variant picker (price/SKU/stock/image), delivery line (D5), stock state, qty, Add-to-Cart-opens-drawer + Buy-Now (D6), accordions, reviews+verified badge, related carousel, recently-viewed → Tasks 11–12. SEO layer: `lib/seo.ts`, generateMetadata everywhere (home/products/category/search/product), title template (root layout already has it), canonical policy, OG/Twitter, all six JSON-LD types, sitemap+robots, slug parity note → Tasks 4/13. Currency/i18n note documented → Task 13. Verification incl. Lighthouse SEO 100 + curl SSR + checkpoint → Task 14. ISR-per-product replaced by tagged data-cache + revalidate route because pages are cookie-dynamic — documented in D7/architecture.
- **Guardrails:** no checkout/payment/shipping code (buy-now proxy only, master-sanctioned); JWTs stay server-side (wishlist/buy-now routes use fetchWithAuth; tests assert 401 without upstream call); money strings verbatim (PriceTag/JSON-LD tests assert exact strings); backend edits confined to Tasks 1–2.
- **Type consistency:** `ProductCard`/`ProductDetail`/`Variant` in `lib/catalog.ts` match the Task-2 serializer fields; `PlpState`/`parsePlpParams`/`plpHref` used by Tasks 8–9; `usePdp`/`initialVariant` shared by gallery/picker/buttons; `RecentEntry` shape consistent between tracker and strip; cookie/env names match Plan-12 (`country`, `API_URL`, `NEXT_PUBLIC_*`); `REVALIDATE_SECRET` used in route + env example.
- **Placeholder scan:** every code step carries real code; the two "mirror the existing test setup" pointers (Task 2 fixture, Footer rework) name the exact file to copy from and what must hold true — deliberate, since inventing a fixture blind against an unseen factory API would be worse. No TBD/TODO left.
