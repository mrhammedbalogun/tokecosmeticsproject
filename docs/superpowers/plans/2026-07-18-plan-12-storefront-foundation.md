# Plan-12 — Storefront foundation (design system, layout shell, auth/cart BFF, country switcher) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the app shell every storefront page will reuse — a premium-beauty design system, a header/footer/nav with a country/currency switcher, a typed API client generated from the backend's OpenAPI schema, a BFF (Backend-For-Frontend) layer that keeps JWTs and the guest-cart id in httpOnly cookies (the browser never sees a token), a cart drawer with optimistic updates, skeleton routes for every top-level page, and error/loading UX — then stop at a design-direction checkpoint before Plan-13 builds the real pages.

**Architecture:** Server Components by default; client components only where interactivity demands them (cart drawer, switchers, forms). Server Components and Route Handlers fetch Django **server-side** with a typed `lib/api.ts` client, so the browser makes **same-origin** calls only (to `/api/*` Route Handlers) and never talks to Django directly — this deliberately keeps CORS a non-issue and keeps tokens server-side. Auth + cart go through Next.js Route Handlers under `src/app/api/` that proxy to Django and read/write httpOnly cookies (`access`, `refresh`, `cart_id`, `country`). Country context is a plain `country` cookie (NG default) read by `middleware.ts`; a first-visit banner *suggests* a country from the geo header but never forces it.

**Tech Stack:** Next.js 16.2.10 (App Router) · React 19.2 · TypeScript 5 · Tailwind CSS v4 (CSS-first `@theme`, no `tailwind.config.js`) · TanStack Query v5 (client cart mutations only) · `openapi-typescript` (build-time type generation) · Vitest + React Testing Library + `@testing-library/jest-dom` (unit/route tests) · next/font (Playfair Display + Inter). Backend is **already built** (Plan-00…11) and unchanged by this plan — the storefront only *consumes* it.

**Spec:** `master-tokerebuild.md` lines 890–918 (general storefront rules + Plan-12). Read them before Task 1.

**Branch:** `plan-12-storefront-foundation` off `main`.

---

## ⚠️ Read this first — Next.js 16 is not the Next.js you know

`storefront/AGENTS.md` warns: **this is Next.js 16.2.10, which has breaking changes vs. older App Router versions.** Before writing route handlers, `middleware.ts`, `layout.tsx`, or `generateMetadata`, read the bundled docs that ship in the repo:

- `storefront/node_modules/next/dist/docs/01-app/index.md` and the `01-app/` tree (App Router, route handlers, middleware, fonts, metadata).

Specifically confirm, in the installed version, the current signatures for: **`cookies()` / `headers()` (async in recent Next — `await cookies()`)**, Route Handler `GET/POST(request: NextRequest)` exports, `middleware.ts` matcher config, and `next/font/google` usage. If a snippet in this plan uses `cookies()` synchronously but the installed docs show it returns a Promise, follow the docs — treat the plan's code as the shape/intent and the bundled docs as the authority on the exact API. **Do not fetch these facts from memory or the public web; the pinned version's own docs are in `node_modules`.**

---

## Decisions needing sign-off

Get Hammed's answers before the tasks noted. Most of the plan does not block on these.

**D1 — Accent colour (blocks Task 2, the design tokens). RECOMMENDED: Toke forest green as the accent, on a cream/off-white + near-black neutral base.**
`TokeLogo.png` is a green brand: a **deep forest-green** oval, a **lighter lime/leaf green** rim-and-leaf, white lettering. The master guide says "one accent — pick from existing Toke branding." So the palette is:
- Background: warm off-white / cream (`#FBF9F5`-ish).
- Text: near-black (`#1A1A1A`-ish, not pure `#000`).
- **Accent: Toke forest green.** Candidate values sampled from the logo (confirm one, or Hammed supplies exact brand hex): deep green **`#1C7A3E`** (buttons, links, active states) with a lighter leaf green **`#8CC63F`** for subtle highlights/hover. A neutral warm-grey ramp fills the rest.
- Because the brand colour is a *green* (not the pink/rose a "beauty" site defaults to), Task 2 uses green as the single accent and leans on typography + whitespace for the premium feel — **do not introduce a second brand colour (no rose/gold) without sign-off.**
Hammed: confirm the accent hex(es), or send the official brand green(s) from the Toke brand kit if one exists.

**D2 — Dev target = local backend on `localhost:8000`. No deployed API exists yet. RECOMMENDED: `NEXT_PUBLIC_API_URL`/`API_URL` → `http://localhost:8000`, and NO backend CORS change.**
There is no `api.tokecosmetics.com` yet. The storefront dev server runs against the Django dev server on `localhost:8000`. **Because this plan routes every browser request through same-origin Next Route Handlers and Server Components (both server-side), CORS never engages** — the existing `CORS_ALLOWED_ORIGINS = [localhost:3000, localhost:3001]` in `backend/config/settings/base.py:191` is already sufficient and **needs no edit.** The only way this plan would need a backend CORS tweak is if we let a *browser* fetch Django directly with the custom `X-Country`/`X-Cart-Id` headers (which are not in `django-cors-headers`' default allow-list). This plan deliberately does **not** do that. Flag: confirm we keep all Django calls server-side (recommended); if Hammed later wants client-side catalog fetching, that is a one-line `CORS_ALLOW_HEADERS` + `CORS_ALLOW_CREDENTIALS` backend change — out of scope here.

**D3 — Test framework = Vitest + React Testing Library. RECOMMENDED, no Playwright yet.**
The storefront has zero tests today. Plan-12's own verification (per the master guide) is `npm run build` clean + manual flows + Lighthouse — not a heavy e2e suite. So this plan adds **Vitest** for the parts where a unit test genuinely pays: `lib/api.ts` (URL building, `X-Country` header, error mapping), the auth/cart/newsletter Route Handlers (cookie set/clear, upstream mapping — with `fetch` mocked), the country/cookie helpers, and the middleware suggestion logic. Layout/design/skeleton work is verified by build + eyeballing, not snapshot tests. **Playwright is intentionally deferred to Plan-14** (checkout e2e stage) — do not stand up a Playwright harness here. Confirm Vitest is acceptable.

**D4 — Deployment / checkpoint format. RECOMMENDED: local walkthrough now; Vercel preview when Hammed connects an account.**
The master guide's checkpoint is "deploy preview URL (Vercel preview)." **Deploying needs Hammed's Vercel account + the GitHub repo connected to it — we don't have that yet.** So Task 15's checkpoint is a **driven local walkthrough** (dev server on `localhost:3000` against the local Django) plus a local Lighthouse run, and the Vercel preview happens the moment Hammed connects Vercel. Flag: confirm the checkpoint may be local until Vercel is wired, or stop and get Vercel access first.

**D5 — Newsletter throttle through the BFF (minor, affects Task 10). RECOMMENDED: forward the client IP.**
Django's `POST /api/v1/newsletter/` is throttled **5/min/IP** (`ScopedRateThrottle`, scope `newsletter`). If the footer posts through our Next Route Handler, every request reaches Django from the *server's* IP, so the per-IP throttle would count all users as one. The Route Handler therefore forwards the caller's IP as `X-Forwarded-For` (Django must be configured to trust it for throttling to be per-user — note for Plan-02/prod, `NUM_PROXIES`/`USE_X_FORWARDED_FOR`). In local dev this is cosmetic. Recommendation: forward the header now, record the prod-trust requirement as a Plan-02 note; do not try to solve proxy-trust config in this storefront plan.

---

## Critical context for the implementer

You know nothing about this codebase. Read this before touching anything.

**The backend is done and must not be modified by this plan.** Everything below is the *shape of what you consume*. Base URL in dev: `http://localhost:8000`. All API paths are under `/api/v1/`. The interactive schema is at `http://localhost:8000/api/schema/` (drf-spectacular) and Swagger UI at `/api/docs/`.

**Auth (JWT via SimpleJWT):**
- `POST /api/v1/auth/register/` — body `{email, password, first_name?, last_name?, phone?, marketing_consent?}`. Creates the user and **emails a verify link. It does NOT return tokens.** So "register then log in" is two calls (register, then token). Duplicate email → `400 {"email": ["Account already exists"]}`.
- `POST /api/v1/auth/token/` — body `{email, password}` → `{access, refresh}` (this is *login*). Inactive/soft-deleted users get `401`.
- `POST /api/v1/auth/token/refresh/` — body `{refresh}` → `{access}` (and a rotated `refresh` if rotation is on — read what comes back, don't assume).
- `POST /api/v1/auth/logout/` — **requires the access token in `Authorization: Bearer …` AND `{refresh}` in the body**; blacklists the refresh token. Returns `205`.
- `GET/PATCH /api/v1/auth/me/` — requires `Authorization: Bearer …`. Returns `{email, first_name, last_name, phone, marketing_consent, toke_id}` (`email`, `toke_id` read-only).

**Cart (guest-cart id is a HEADER, not a backend cookie):**
- `GET /api/v1/cart/` — returns the cart JSON (see shape below). For a **guest**, the cart is identified by the request header **`X-Cart-Id: <uuid>`**; if absent/unknown, the backend creates a fresh cart and returns its `id`. For an **authed** user (Bearer token) the backend uses their single active cart and ignores `X-Cart-Id`.
- `POST /api/v1/cart/items/` — body `{variant_id, quantity}` → full cart JSON. Quantity is capped at available stock server-side.
- `PATCH /api/v1/cart/items/<variant_id>/` — body `{quantity}` (absolute; `0` removes) → full cart JSON.
- `DELETE /api/v1/cart/items/<variant_id>/` → full cart JSON.
- `POST /api/v1/cart/merge/` — authed; body `{cart_id}`; folds a guest cart into the user's cart (used at login).
- **Every cart call also honours `X-Country`** (prices are re-resolved per country). Cart JSON shape:
  ```json
  {"id":"<uuid>","kind":"standard","status":"active","country":"NG","currency":"NGN",
   "items":[{"id":1,"variant_id":10,"sku":"…","name":"…","variant_name":{},"quantity":2,
             "unit_price":"1500.00","line_total":"3000.00","unavailable":false}],
   "subtotal":"3000.00","has_unavailable":false}
  ```
  **BFF cart-id lifecycle:** the browser holds the guest cart id in an httpOnly `cart_id` cookie. The Route Handler reads that cookie → sends it as `X-Cart-Id` → and writes the `id` from the response back into the cookie (so a first, cookie-less call adopts the backend-created cart). When a user logs in, call `/cart/merge/` with the old `cart_id`, then clear the `cart_id` cookie (the authed cart is server-owned).

**Country / markets:**
- `GET /api/v1/meta/countries/` — public, unpaginated list of **active markets** for the switcher. Each: `{code, name, currency:{code,symbol,decimal_places}, is_default, is_rest_of_world, tax_rate_percent, prices_include_tax, area_label}`. Active markets are **NG (default, NGN), GB (GBP), US (USD), CA (CAD), and ZZ = "Rest of World / International" (USD, `is_rest_of_world: true`)**.
- The backend resolves the `X-Country` header thus (`apps/core/country_context.py`): missing/blank → default (NG); an active market code → that market; anything else → ZZ. So the switcher's options are exactly this endpoint's rows; ZZ is the label to show as "International (USD)".

**Catalog (for nav):**
- `GET /api/v1/categories/` — public, unpaginated **category tree** (roots with nested `children`). Each node: `{name, slug, image, sort_order, children:[…]}`. This feeds the header nav. Cache it (ISR/`revalidate: 3600`).
- `GET /api/v1/products/` and `GET /api/v1/products/<slug>/` also honour `X-Country` (used by Plan-13, not built here — just make the client ready).

**Newsletter (footer capture):**
- `POST /api/v1/newsletter/` — public, body `{email, source?}` → `201 {"detail":"Subscribed."}` (or `200` if already subscribed). Throttled 5/min/IP (see D5).

**Cookies this plan introduces (all set by Route Handlers / middleware):**
| Cookie | httpOnly | Set by | Purpose |
|---|---|---|---|
| `access` | yes | auth Route Handlers | JWT access token; short life; sent server-side as Bearer |
| `refresh` | yes | auth Route Handlers | JWT refresh token; used by the silent-refresh wrapper |
| `cart_id` | yes | cart Route Handlers | guest cart UUID → forwarded as `X-Cart-Id` |
| `country` | **no** | middleware / switcher | market code (`NG` default); readable by client for UI; forwarded as `X-Country` |

`country` is intentionally **not** httpOnly — it is not a secret and the client UI reads it to show the current flag/currency. `access`/`refresh`/`cart_id` are httpOnly + `sameSite:'lax'` + `path:'/'` (+ `secure` in production).

**Money / scope guardrails (standing project rules — do not break):**
- **Do NOT touch payments, checkout, shipping, or delivery pricing code** (backend or storefront). This plan builds skeleton `/checkout` and `/cart` routes only — placeholder content, no money math, no gateway calls. Plan-14 owns checkout.
- **The browser must never receive a JWT.** Tokens live only in httpOnly cookies and are only ever read server-side. No token in `localStorage`, no token in a non-httpOnly cookie, no token in client JS. Any task that seems to need a token in the browser is wrong — stop and flag.
- **Do NOT add price/amount formatting that rounds or fuzzes money.** Display prices exactly as the API returns the string; format with `Intl.NumberFormat` for grouping/symbol only.

**Commands (run from `storefront/`):**
```bash
cd tokecosmetics-platform/storefront
npm run test           # Vitest (added in Task 1)
npm run test -- --run  # single-shot (CI style)
npm run build          # MUST be clean before the checkpoint
npm run dev            # dev server on http://localhost:3000
npm run gen:api        # regenerate src/lib/api-types.ts from the running backend schema
npm run lint
```

**Running the backend for integration/verification** (from `backend/`, in a second terminal):
```bash
cd tokecosmetics-platform/backend
uv run python manage.py runserver 0.0.0.0:8000
```
The dev DB is seeded (countries/currencies via migrations; catalog may need a fixture/seed — if `/api/v1/categories/` returns `[]`, that is fine for the shell, and Plan-13 seeds real catalog).

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `storefront/.env.local.example`, `.env.local` | `NEXT_PUBLIC_SITE_URL`, `API_URL`, `NEXT_PUBLIC_API_URL` | 1 |
| `storefront/vitest.config.mts`, `vitest.setup.ts` | test runner + RTL/jest-dom setup | 1 |
| `storefront/package.json` | deps + scripts (`test`, `gen:api`) | 1 |
| `storefront/src/app/globals.css` | Tailwind v4 `@theme` design tokens (colours, fonts, radius) | 2 |
| `storefront/src/app/layout.tsx` | Playfair+Inter via next/font, metadata, `<Providers>`, shell mount | 2, 8, 12 |
| `storefront/src/lib/api-types.ts` | **generated** OpenAPI types (do not hand-edit) | 3 |
| `storefront/src/lib/api.ts` | `apiFetch<T>` server-side client (`X-Country`, Bearer, error mapping) | 3 |
| `storefront/src/lib/country.ts` | market list types, `getCountry()`/cookie helpers, currency format | 4 |
| `storefront/src/lib/auth.ts` | cookie names + set/clear helpers + `getAccessToken()` | 5 |
| `storefront/src/app/api/auth/[action]/route.ts` | login/register/logout/refresh/me BFF | 6 |
| `storefront/src/lib/session.ts` | `fetchWithAuth` server helper w/ silent refresh | 6 |
| `storefront/src/app/api/cart/[[...path]]/route.ts` | cart BFF (GET/POST/PATCH/DELETE) + `cart_id` cookie | 7 |
| `storefront/src/app/api/newsletter/route.ts` | newsletter capture BFF (forwards IP) | 10 |
| `storefront/src/components/providers.tsx` | TanStack Query client provider | 8 |
| `storefront/src/hooks/useCart.ts` | cart query + optimistic add/update/remove | 8 |
| `storefront/src/components/layout/CartDrawer.tsx` | slide-over cart (client) | 8 |
| `storefront/src/components/layout/Header.tsx` | logo, nav, switcher, account menu, cart button (server) | 9 |
| `storefront/src/components/layout/CountrySwitcher.tsx` | client switcher → sets `country` cookie, refreshes | 9 |
| `storefront/src/components/layout/AccountMenu.tsx`, `CartButton.tsx` | client bits of the header | 9 |
| `storefront/src/components/layout/Footer.tsx` | policy links, newsletter form, payment logos | 10 |
| `storefront/src/components/layout/NewsletterForm.tsx` | client form → `/api/newsletter` | 10 |
| `storefront/src/components/layout/MobileNav.tsx`, `SearchBar.tsx` | mobile drawer nav + search stub | 11 |
| `storefront/src/app/(shop)/layout.tsx` + route folders | Header/Footer wrapper + skeleton pages | 12 |
| `storefront/src/app/(auth)/login/page.tsx`, `register/page.tsx` | skeleton auth pages | 12 |
| `storefront/src/app/error.tsx`, `not-found.tsx`, `loading.tsx` | root error/404/loading UX | 13 |
| `storefront/src/app/(shop)/**/loading.tsx` | per-route skeletons | 13 |
| `storefront/src/middleware.ts` | `country` cookie default + geo suggestion header | 14 |
| `storefront/src/components/layout/CountrySuggestionBanner.tsx` | first-visit "shop in GBP?" banner | 14 |
| `storefront/public/logos/` | `toke-logo.svg`/png + payment logos | 2, 10 |
| `tokecosmetics-platform/docs/architecture.md` | § Storefront (BFF, cookies, country model) | 15 |

**Task order is a dependency chain.** Tokens/tooling (1) → design tokens + fonts (2) → typed client (3) → country + auth cookie libs (4, 5) → auth BFF (6) → cart BFF (7) → cart UI (8) → Header (9) → Footer (10) → mobile/search (11) → skeleton routes wiring the shell (12) → error/loading (13) → middleware + banner (14) → checkpoint (15).

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
cd tokecosmetics-platform
git checkout main
git status --short          # must be empty
git checkout -b plan-12-storefront-foundation
```

---

### Task 1: Tooling — deps, env files, Vitest, scripts

**Why:** the scaffold has no test runner, no API-type generator, no TanStack Query, and no env wiring. Set all of it up once, with a trivial passing test to prove Vitest actually runs (so later tasks fail for real reasons, not a broken harness).

**Files:**
- Modify: `storefront/package.json`
- Create: `storefront/vitest.config.mts`, `storefront/vitest.setup.ts`, `storefront/src/lib/__tests__/smoke.test.ts`
- Create: `storefront/.env.local.example`, `storefront/.env.local`

- [ ] **Step 1: Install dependencies**

```bash
cd tokecosmetics-platform/storefront
npm install @tanstack/react-query@^5 clsx
npm install -D vitest@^3 @vitejs/plugin-react @testing-library/react @testing-library/jest-dom @testing-library/dom jsdom openapi-typescript
```

(If a version is unavailable, take the latest that resolves — pin whatever npm writes to `package.json`.)

- [ ] **Step 2: Add scripts**

In `storefront/package.json`, set the `scripts` block to:

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "test": "vitest",
    "gen:api": "openapi-typescript http://localhost:8000/api/schema/ -o src/lib/api-types.ts"
  },
```

- [ ] **Step 3: Vitest config**

`storefront/vitest.config.mts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
```

`storefront/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 4: Env files**

`storefront/.env.local.example`:

```bash
# Server-side base URL for Django (used by Route Handlers + Server Components).
API_URL=http://localhost:8000
# Public base URL of the storefront itself (metadata, absolute links).
NEXT_PUBLIC_SITE_URL=http://localhost:3000
# Exposed to the browser ONLY if a client ever needs the API origin. Same value in dev.
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Copy it to `storefront/.env.local` (same contents for local dev). **Do not commit `.env.local`** — confirm it is gitignored (Next's default `.gitignore` already ignores `.env*.local`).

- [ ] **Step 5: Smoke test**

`storefront/src/lib/__tests__/smoke.test.ts`:

```ts
import { describe, it, expect } from "vitest";

describe("vitest harness", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 6: Run it**

```bash
npm run test -- --run
```

Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add storefront/package.json storefront/package-lock.json storefront/vitest.config.mts storefront/vitest.setup.ts storefront/src/lib/__tests__/smoke.test.ts storefront/.env.local.example
git commit -m "chore(storefront): add vitest, tanstack-query, openapi-typescript, env scaffolding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Design tokens + fonts (premium-beauty theme)

**Why:** every later component reads these tokens. Tailwind v4 is CSS-first — the theme lives in `globals.css` via `@theme`, not a `tailwind.config.js`. Set the neutral cream/near-black base + the single Toke-green accent (D1) and wire Playfair Display (headings) + Inter (body) through next/font so there is no layout-shift and no external font request (Lighthouse). This task is verified by build + eyeballing, not a unit test.

**Depends on:** D1 (accent hex).

**Files:**
- Modify: `storefront/src/app/globals.css`
- Modify: `storefront/src/app/layout.tsx`
- Modify: `storefront/src/app/page.tsx` (temporary token/price demo — replaced in Task 12)
- Create: `storefront/public/logos/toke-logo.png` (copy the brand asset)

- [ ] **Step 1: Copy the brand logo into the app**

```bash
cp "C:/Users/Hammed/Desktop/TokeCosmeticsDev/TokeLogo.png" "tokecosmetics-platform/storefront/public/logos/toke-logo.png"
```

- [ ] **Step 2: Replace `globals.css` with the token set**

`storefront/src/app/globals.css`:

```css
@import "tailwindcss";

/* Toke Cosmetics design tokens — premium beauty: warm cream base, near-black ink,
   single Toke-green accent (see Plan-12 D1). Confirm accent hexes with Hammed. */
:root {
  --color-cream: #fbf9f5;      /* page background */
  --color-ink: #1a1a1a;        /* primary text */
  --color-ink-soft: #6b6862;   /* secondary text / captions */
  --color-line: #e7e2d8;       /* hairline borders */
  --color-accent: #1c7a3e;     /* Toke forest green — buttons, links, active */
  --color-accent-strong: #145f30;
  --color-leaf: #8cc63f;       /* light leaf green — subtle highlights */
  --color-surface: #ffffff;    /* cards, drawers */
  --radius-card: 0.75rem;
}

@theme inline {
  --color-background: var(--color-cream);
  --color-foreground: var(--color-ink);
  --color-muted: var(--color-ink-soft);
  --color-line: var(--color-line);
  --color-accent: var(--color-accent);
  --color-accent-strong: var(--color-accent-strong);
  --color-leaf: var(--color-leaf);
  --color-surface: var(--color-surface);
  --font-sans: var(--font-inter);
  --font-display: var(--font-playfair);
  --radius-card: var(--radius-card);
}

body {
  background: var(--color-background);
  color: var(--color-foreground);
  font-family: var(--font-sans), system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, .font-display {
  font-family: var(--font-display), Georgia, serif;
}
```

(Note: the storefront is a light-only premium brand at launch — the master guide specifies a cream/near-black palette, not a dark theme. Do **not** add a `prefers-color-scheme: dark` block; it fought the brand and was removed from the scaffold's default.)

- [ ] **Step 3: Fonts + metadata in `layout.tsx`**

`storefront/src/app/layout.tsx` (verify `next/font/google` usage against the bundled docs first):

```tsx
import type { Metadata } from "next";
import { Playfair_Display, Inter } from "next/font/google";
import "./globals.css";

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Toke Cosmetics", template: "%s | Toke Cosmetics" },
  description: "Premium beauty and cosmetics — shop skincare, makeup and more.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${playfair.variable} ${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-background text-foreground">{children}</body>
    </html>
  );
}
```

- [ ] **Step 4: Temporary token demo on the home page**

Replace `storefront/src/app/page.tsx` with a swatch + type + price sample so the tokens are visibly correct (this whole file is replaced in Task 12):

```tsx
export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="font-display text-5xl text-foreground">Toke Cosmetics</h1>
      <p className="mt-3 text-lg text-muted">Premium beauty. Design-system preview.</p>
      <div className="mt-10 flex gap-3">
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-accent)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-leaf)" }} />
        <span className="h-12 w-12 rounded-full border border-line" style={{ background: "var(--color-cream)" }} />
        <span className="h-12 w-12 rounded-full" style={{ background: "var(--color-ink)" }} />
      </div>
      <button className="mt-8 rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Add to bag
      </button>
      <p className="mt-6 text-2xl font-medium">₦12,500.00</p>
    </main>
  );
}
```

- [ ] **Step 5: Build + eyeball**

```bash
npm run build
```
Expected: build succeeds. Then `npm run dev` and open `http://localhost:3000`: heading is a serif (Playfair), body is Inter, background is cream, the button is Toke green and darkens on hover, the four swatches show accent/leaf/cream/ink.

- [ ] **Step 6: Commit**

```bash
git add storefront/src/app/globals.css storefront/src/app/layout.tsx storefront/src/app/page.tsx storefront/public/logos/toke-logo.png
git commit -m "feat(storefront): premium-beauty design tokens + Playfair/Inter fonts

Cream/near-black neutral base with a single Toke-green accent (D1); Tailwind v4
@theme tokens; fonts self-hosted via next/font (no external request, no CLS).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Typed API client (`lib/api.ts`) + OpenAPI type generation

**Why:** one server-side fetch helper that every Server Component and Route Handler uses — so the `X-Country` header, the base URL, JSON handling, and error shape are defined in exactly one place, and the request/response types come straight from the backend's OpenAPI schema (regenerate, never hand-write). This is the seam the whole storefront is built on, so it is unit-tested.

**Files:**
- Create: `storefront/src/lib/api.ts`
- Create (generated): `storefront/src/lib/api-types.ts`
- Test: `storefront/src/lib/__tests__/api.test.ts`

- [ ] **Step 1: Generate the types (backend must be running)**

In a second terminal start the backend (`cd backend && uv run python manage.py runserver 0.0.0.0:8000`), then:

```bash
cd tokecosmetics-platform/storefront
npm run gen:api
```

Expected: `src/lib/api-types.ts` is written with a `paths` interface. If the backend is not running the command fails — start it and retry. Commit the generated file (it is a build input; regenerating is a documented script).

- [ ] **Step 2: Write the failing tests**

`storefront/src/lib/__tests__/api.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, ApiError } from "@/lib/api";

const originalFetch = global.fetch;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("apiFetch", () => {
  it("prefixes API_URL and the /api/v1 path", async () => {
    const f = mockFetch(200, { ok: true });
    await apiFetch("/meta/countries/");
    expect(f).toHaveBeenCalledOnce();
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/meta/countries/");
  });

  it("sends X-Country from the option (default NG)", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/cart/", { country: "GB" });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Country")).toBe("GB");

    await apiFetch("/cart/");
    const init2 = (f.mock.calls[1][1] as RequestInit);
    expect(new Headers(init2.headers).get("X-Country")).toBe("NG");
  });

  it("adds a Bearer header when a token is given", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/auth/me/", { token: "abc.def.ghi" });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc.def.ghi");
  });

  it("returns parsed JSON on success", async () => {
    mockFetch(200, { code: "NG" });
    const data = await apiFetch<{ code: string }>("/meta/countries/");
    expect(data.code).toBe("NG");
  });

  it("throws ApiError with status + parsed body on 4xx", async () => {
    mockFetch(400, { email: ["Account already exists"] });
    await expect(apiFetch("/auth/register/", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 400,
      data: { email: ["Account already exists"] },
    });
  });

  it("does not send a Bearer header when no token", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/meta/countries/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/api.test.ts
```
Expected: FAIL — cannot import `apiFetch`/`ApiError`.

- [ ] **Step 4: Implement `lib/api.ts`**

`storefront/src/lib/api.ts`:

```ts
/**
 * Server-side Django client. Used by Server Components and Route Handlers ONLY
 * (it reads process.env.API_URL, which is not exposed to the browser). Centralises
 * the base URL, the /api/v1 prefix, the X-Country header, the Bearer header, JSON
 * encode/decode, and the error shape so no other file re-implements any of it.
 */
const DEFAULT_COUNTRY = "NG";

export class ApiError extends Error {
  constructor(
    public status: number,
    public data: unknown,
  ) {
    super(`API ${status}`);
    this.name = "ApiError";
  }
}

export interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  /** Market code forwarded as X-Country (defaults to NG). */
  country?: string;
  /** JWT access token → Authorization: Bearer. Omit for anonymous calls. */
  token?: string;
  /** Guest cart id → X-Cart-Id (cart calls only). */
  cartId?: string;
  /** Next.js fetch cache options, e.g. { next: { revalidate: 3600 } }. */
  next?: NextFetchRequestConfig;
  cache?: RequestCache;
  headers?: Record<string, string>;
}

function baseUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const headers = new Headers(opts.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Country", opts.country ?? DEFAULT_COUNTRY);
  if (opts.token) headers.set("Authorization", `Bearer ${opts.token}`);
  if (opts.cartId) headers.set("X-Cart-Id", opts.cartId);

  const init: RequestInit = { method: opts.method ?? "GET", headers };
  if (opts.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(opts.body);
  }
  if (opts.next) (init as { next?: NextFetchRequestConfig }).next = opts.next;
  if (opts.cache) init.cache = opts.cache;

  const res = await fetch(`${baseUrl()}/api/v1${path}`, init);

  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
```

- [ ] **Step 5: Run tests**

```bash
npm run test -- --run src/lib/__tests__/api.test.ts
```
Expected: PASS.

- [ ] **Step 6: Mutation-verify**

In `apiFetch`, temporarily change `headers.set("X-Country", opts.country ?? DEFAULT_COUNTRY)` to always `"US"`. Confirm the X-Country tests go RED. Revert.

- [ ] **Step 7: Commit**

```bash
git add storefront/src/lib/api.ts storefront/src/lib/api-types.ts storefront/src/lib/__tests__/api.test.ts
git commit -m "feat(storefront): typed server-side api client + generated OpenAPI types

apiFetch centralises base URL, /api/v1 prefix, X-Country, Bearer, X-Cart-Id and
the ApiError shape. Types generated from the live schema via 'npm run gen:api'.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Country library (`lib/country.ts`)

**Why:** one module owns the market list contract, the `country` cookie name, the default (NG), the "is this a valid market?" check, and currency formatting — so the switcher, middleware, and any price display agree. The market list itself comes from the API (`/meta/countries/`); this module fetches + caches it and provides the formatting.

**Files:**
- Create: `storefront/src/lib/country.ts`
- Test: `storefront/src/lib/__tests__/country.test.ts`

- [ ] **Step 1: Write the failing tests**

`storefront/src/lib/__tests__/country.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, normalizeCountry, formatMoney } from "@/lib/country";

const MARKETS = ["NG", "GB", "US", "CA", "ZZ"];

describe("country helpers", () => {
  it("exposes the cookie name and NG default", () => {
    expect(COUNTRY_COOKIE).toBe("country");
    expect(DEFAULT_COUNTRY).toBe("NG");
  });

  it("normalizes a known market (case-insensitive)", () => {
    expect(normalizeCountry("gb", MARKETS)).toBe("GB");
  });

  it("falls back to ZZ (rest of world) for an unknown but non-empty code", () => {
    expect(normalizeCountry("FR", MARKETS)).toBe("ZZ");
  });

  it("falls back to the NG default for a missing code", () => {
    expect(normalizeCountry(undefined, MARKETS)).toBe("NG");
  });

  it("formats money per currency", () => {
    expect(formatMoney("12500.00", "NGN", "₦")).toBe("₦12,500.00");
    expect(formatMoney("19.99", "GBP", "£")).toBe("£19.99");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/country.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `lib/country.ts`**

`storefront/src/lib/country.ts`:

```ts
import { apiFetch } from "@/lib/api";

export const COUNTRY_COOKIE = "country";
export const DEFAULT_COUNTRY = "NG";
/** Backend rest-of-world market code — shown as "International (USD)". */
export const REST_OF_WORLD = "ZZ";

export interface Currency {
  code: string;
  symbol: string;
  decimal_places: number;
}
export interface Market {
  code: string;
  name: string;
  currency: Currency;
  is_default: boolean;
  is_rest_of_world: boolean;
  area_label: string;
}

/** Active markets for the switcher. Cached 1h (ISR) — the list rarely changes. */
export async function getMarkets(): Promise<Market[]> {
  return apiFetch<Market[]>("/meta/countries/", { next: { revalidate: 3600 } });
}

/**
 * Resolve an arbitrary code to a valid market code, mirroring the backend's
 * resolve_country: missing -> NG default; known market -> itself; unknown but
 * present -> ZZ (rest of world).
 */
export function normalizeCountry(
  code: string | undefined | null,
  validCodes: string[],
): string {
  if (!code) return DEFAULT_COUNTRY;
  const upper = code.toUpperCase();
  if (validCodes.includes(upper)) return upper;
  return validCodes.includes(REST_OF_WORLD) ? REST_OF_WORLD : DEFAULT_COUNTRY;
}

/** Group/symbol formatting only — never rounds; the API already fixed the decimals. */
export function formatMoney(amount: string, currencyCode: string, symbol: string): string {
  const n = Number(amount);
  const grouped = new Intl.NumberFormat("en", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
  return `${symbol}${grouped}`;
}

export function labelFor(market: Market): string {
  return market.is_rest_of_world ? "International (USD)" : market.name;
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/lib/__tests__/country.test.ts
```
Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Change `if (!code) return DEFAULT_COUNTRY;` to `return "GB"`. Confirm the "missing code" test goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add storefront/src/lib/country.ts storefront/src/lib/__tests__/country.test.ts
git commit -m "feat(storefront): country/market helpers (cookie, normalize, money format)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Auth cookie helpers (`lib/auth.ts`)

**Why:** the token cookies are security-sensitive — their names, flags (httpOnly, sameSite, secure-in-prod, path), and set/clear logic must be defined once so no Route Handler gets the flags subtly wrong (a non-httpOnly token cookie would be an XSS token-theft hole). This module is the single source for those flags; the Route Handlers (Task 6, 7) call it.

**Files:**
- Create: `storefront/src/lib/auth.ts`
- Test: `storefront/src/lib/__tests__/auth.test.ts`

- [ ] **Step 1: Write the failing tests**

`storefront/src/lib/__tests__/auth.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { ACCESS_COOKIE, REFRESH_COOKIE, CART_COOKIE, cookieOptions } from "@/lib/auth";

describe("auth cookie contract", () => {
  it("names the token cookies", () => {
    expect(ACCESS_COOKIE).toBe("access");
    expect(REFRESH_COOKIE).toBe("refresh");
    expect(CART_COOKIE).toBe("cart_id");
  });

  it("token cookies are httpOnly, lax, path=/", () => {
    const o = cookieOptions();
    expect(o.httpOnly).toBe(true);
    expect(o.sameSite).toBe("lax");
    expect(o.path).toBe("/");
  });

  it("is secure in production, not in dev", () => {
    expect(cookieOptions({ nodeEnv: "production" }).secure).toBe(true);
    expect(cookieOptions({ nodeEnv: "development" }).secure).toBe(false);
  });

  it("passes through a maxAge", () => {
    expect(cookieOptions({ maxAge: 3600 }).maxAge).toBe(3600);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/auth.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `lib/auth.ts`**

`storefront/src/lib/auth.ts`:

```ts
/**
 * Single source of truth for the storefront's auth/cart cookies. The token cookies
 * MUST stay httpOnly so a JWT is never reachable from browser JS (XSS token theft).
 * Route Handlers set/clear them via these helpers — never hand-roll the flags.
 */
export const ACCESS_COOKIE = "access";
export const REFRESH_COOKIE = "refresh";
export const CART_COOKIE = "cart_id";

// Access tokens are short-lived; refresh long-lived. Match your SimpleJWT lifetimes.
export const ACCESS_MAX_AGE = 60 * 30; // 30 min
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 14; // 14 days

export interface CookieOptions {
  httpOnly: boolean;
  sameSite: "lax";
  secure: boolean;
  path: string;
  maxAge?: number;
}

export function cookieOptions(
  opts: { nodeEnv?: string; maxAge?: number } = {},
): CookieOptions {
  const env = opts.nodeEnv ?? process.env.NODE_ENV;
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: env === "production",
    path: "/",
    ...(opts.maxAge !== undefined ? { maxAge: opts.maxAge } : {}),
  };
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/lib/__tests__/auth.test.ts
```
Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Change `httpOnly: true` to `false`. Confirm the httpOnly test goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add storefront/src/lib/auth.ts storefront/src/lib/__tests__/auth.test.ts
git commit -m "feat(storefront): auth/cart cookie contract (httpOnly, secure-in-prod)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Auth BFF Route Handlers + silent-refresh helper

**Why:** the browser posts credentials to *our* same-origin `/api/auth/*` handlers; those handlers talk to Django, and put `access`/`refresh` into httpOnly cookies. The browser never sees a token. A `fetchWithAuth` server helper retries once through `/token/refresh/` when the access token is expired, so Server Components don't each re-implement refresh.

**Files:**
- Create: `storefront/src/app/api/auth/[action]/route.ts`
- Create: `storefront/src/lib/session.ts`
- Test: `storefront/src/app/api/auth/__tests__/route.test.ts`
- Test: `storefront/src/lib/__tests__/session.test.ts`

- [ ] **Step 1: Write the failing tests (route handler)**

`storefront/src/app/api/auth/__tests__/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock next/headers cookies() so we can assert what the handler sets.
const store = new Map<string, string>();
const setSpy = vi.fn((name: string, value: string) => store.set(name, value));
const deleteSpy = vi.fn((name: string) => store.delete(name));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => deleteSpy(n),
  }),
}));

import { POST } from "@/app/api/auth/[action]/route";

const originalFetch = global.fetch;
beforeEach(() => {
  store.clear();
  setSpy.mockClear();
  deleteSpy.mockClear();
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function upstream(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  ) as unknown as typeof fetch;
}
function req(body: unknown) {
  return new Request("http://localhost:3000/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("auth BFF", () => {
  it("login stores access+refresh cookies and does NOT leak tokens in the body", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });
    const res = await POST(req({ email: "a@b.com", password: "pw" }), { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(200);
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
    const json = await res.json();
    expect(JSON.stringify(json)).not.toContain("AAA");
    expect(JSON.stringify(json)).not.toContain("RRR");
  });

  it("login forwards a 401 as 401 without setting cookies", async () => {
    upstream(401, { detail: "No active account found with the given credentials" });
    const res = await POST(req({ email: "a@b.com", password: "bad" }), { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(401);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("logout clears cookies", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    upstream(205, {});
    const res = await POST(req({}), { params: Promise.resolve({ action: "logout" }) });
    expect(res.status).toBe(200);
    expect(deleteSpy).toHaveBeenCalledWith("access");
    expect(deleteSpy).toHaveBeenCalledWith("refresh");
  });

  it("register forwards the 400 duplicate-email error", async () => {
    upstream(400, { email: ["Account already exists"] });
    const res = await POST(req({ email: "a@b.com", password: "pw" }), { params: Promise.resolve({ action: "register" }) });
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.email).toContain("Account already exists");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/app/api/auth
```
Expected: FAIL — handler module not found.

- [ ] **Step 3: Implement the auth Route Handler**

`storefront/src/app/api/auth/[action]/route.ts` (verify `cookies()` await-ness against the bundled Next 16 docs):

```ts
import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import {
  ACCESS_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";

type Action = "login" | "register" | "logout" | "refresh" | "me";

async function setTokens(access?: string, refresh?: string) {
  const jar = await cookies();
  if (access) jar.set(ACCESS_COOKIE, access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (refresh) jar.set(REFRESH_COOKIE, refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
}
async function clearTokens() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  const jar = await cookies();
  const body = await req.json().catch(() => ({}));

  try {
    switch (action as Action) {
      case "login": {
        const tokens = await apiFetch<{ access: string; refresh: string }>("/auth/token/", {
          method: "POST", body,
        });
        await setTokens(tokens.access, tokens.refresh);
        // Fold any guest cart into the user's cart, then drop the guest cart cookie.
        return json({ ok: true });
      }
      case "register": {
        // Django register does NOT return tokens; create the account, then log in.
        await apiFetch("/auth/register/", { method: "POST", body });
        const tokens = await apiFetch<{ access: string; refresh: string }>("/auth/token/", {
          method: "POST", body: { email: body.email, password: body.password },
        });
        await setTokens(tokens.access, tokens.refresh);
        return json({ ok: true }, 201);
      }
      case "logout": {
        const access = jar.get(ACCESS_COOKIE)?.value;
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (refresh && access) {
          await apiFetch("/auth/logout/", { method: "POST", body: { refresh }, token: access })
            .catch(() => undefined); // best-effort blacklist; clear cookies regardless
        }
        await clearTokens();
        return json({ ok: true });
      }
      case "refresh": {
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (!refresh) return json({ detail: "No session." }, 401);
        const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
          method: "POST", body: { refresh },
        });
        await setTokens(out.access, out.refresh);
        return json({ ok: true });
      }
      case "me": {
        const access = jar.get(ACCESS_COOKIE)?.value;
        if (!access) return json({ detail: "Not authenticated." }, 401);
        const me = await apiFetch("/auth/me/", { token: access });
        return json(me);
      }
      default:
        return json({ detail: "Unknown action." }, 404);
    }
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/app/api/auth
```
Expected: PASS.

- [ ] **Step 5: Write the failing test (session helper)**

`storefront/src/lib/__tests__/session.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "OLD"], ["refresh", "RRR"]]);
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { fetchWithAuth } from "@/lib/session";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; setSpy.mockClear(); store.set("access", "OLD"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("fetchWithAuth silent refresh", () => {
  it("refreshes once on a 401, stores the new access token, and retries", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push(url);
      if (url.endsWith("/auth/me/") && new Headers(init?.headers).get("Authorization") === "Bearer OLD")
        return Promise.resolve(new Response("{}", { status: 401 }));
      if (url.endsWith("/auth/token/refresh/"))
        return Promise.resolve(new Response(JSON.stringify({ access: "NEW" }), { status: 200, headers: { "content-type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify({ email: "a@b.com" }), { status: 200, headers: { "content-type": "application/json" } }));
    }) as unknown as typeof fetch;

    const data = await fetchWithAuth<{ email: string }>("/auth/me/");
    expect(data.email).toBe("a@b.com");
    expect(setSpy).toHaveBeenCalledWith("access", "NEW");
    expect(calls.some((u) => u.endsWith("/auth/token/refresh/"))).toBe(true);
  });
});
```

- [ ] **Step 6: Implement `lib/session.ts`**

`storefront/src/lib/session.ts`:

```ts
import { cookies } from "next/headers";
import { apiFetch, ApiError, type ApiFetchOptions } from "@/lib/api";
import { ACCESS_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, cookieOptions } from "@/lib/auth";

/** Read the current access token (server-only). */
export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

/**
 * Authenticated server-side fetch with a single silent refresh: if the access token
 * is rejected (401), swap the refresh token for a fresh access token, persist it, and
 * retry once. Used by Server Components that need the logged-in user.
 */
export async function fetchWithAuth<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const jar = await cookies();
  const token = jar.get(ACCESS_COOKIE)?.value;
  try {
    return await apiFetch<T>(path, { ...opts, token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    const refresh = jar.get(REFRESH_COOKIE)?.value;
    if (!refresh) throw e;
    const out = await apiFetch<{ access: string }>("/auth/token/refresh/", {
      method: "POST", body: { refresh },
    });
    jar.set(ACCESS_COOKIE, out.access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
    return apiFetch<T>(path, { ...opts, token: out.access });
  }
}
```

- [ ] **Step 7: Run tests**

```bash
npm run test -- --run src/lib/__tests__/session.test.ts src/app/api/auth
```
Expected: PASS.

- [ ] **Step 8: Mutation-verify**

In the `login` case, add `access` to the JSON response body (`return json({ ok: true, access: tokens.access })`). Confirm the "does NOT leak tokens" test goes RED. Revert.

- [ ] **Step 9: Commit**

```bash
git add storefront/src/app/api/auth storefront/src/lib/session.ts storefront/src/lib/__tests__/session.test.ts
git commit -m "feat(storefront): auth BFF route handlers + silent-refresh session helper

Login/register/logout/refresh/me proxy Django; access+refresh live only in httpOnly
cookies (never in a response body or browser JS). fetchWithAuth retries once on 401.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Cart BFF Route Handler + `cart_id` cookie lifecycle

**Why:** the guest cart id must live in an httpOnly cookie and be forwarded to Django as `X-Cart-Id`; the backend returns the authoritative cart (creating one if the cookie was empty), and we persist its `id` back into the cookie. The browser calls same-origin `/api/cart/*`; only the server knows the cart id and the country.

**Files:**
- Create: `storefront/src/app/api/cart/[[...path]]/route.ts`
- Test: `storefront/src/app/api/cart/__tests__/route.test.ts`

- [ ] **Step 1: Write the failing tests**

`storefront/src/app/api/cart/__tests__/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET, POST } from "@/app/api/cart/[[...path]]/route";

const CART = { id: "11111111-1111-1111-1111-111111111111", items: [], subtotal: "0.00", currency: "NGN" };
const originalFetch = global.fetch;
beforeEach(() => { store.clear(); setSpy.mockClear(); process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(body: unknown, status = 200) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  ) as unknown as typeof fetch;
  return global.fetch as unknown as ReturnType<typeof vi.fn>;
}

describe("cart BFF", () => {
  it("GET forwards X-Country and persists the returned cart id into the cookie", async () => {
    store.set("country", "GB");
    const f = upstream(CART);
    const res = await GET(new Request("http://localhost:3000/api/cart"), { params: Promise.resolve({ path: [] }) });
    expect(res.status).toBe(200);
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Country")).toBe("GB");
    expect(setSpy).toHaveBeenCalledWith("cart_id", CART.id);
  });

  it("GET forwards an existing cart_id cookie as X-Cart-Id", async () => {
    store.set("cart_id", "22222222-2222-2222-2222-222222222222");
    const f = upstream(CART);
    await GET(new Request("http://localhost:3000/api/cart"), { params: Promise.resolve({ path: [] }) });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Cart-Id")).toBe("22222222-2222-2222-2222-222222222222");
  });

  it("POST items proxies the body to /cart/items/", async () => {
    const f = upstream(CART);
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: 10, quantity: 2 }),
      }),
      { params: Promise.resolve({ path: ["items"] }) },
    );
    expect(res.status).toBe(200);
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/cart/items/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ variant_id: 10, quantity: 2 });
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/app/api/cart
```
Expected: FAIL — handler not found.

- [ ] **Step 3: Implement the cart Route Handler**

`storefront/src/app/api/cart/[[...path]]/route.ts`:

```ts
import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { ACCESS_COOKIE, CART_COOKIE, cookieOptions } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

interface Cart { id: string; [k: string]: unknown }

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

async function proxy(method: string, segments: string[], body: unknown | undefined) {
  const jar = await cookies();
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const token = jar.get(ACCESS_COOKIE)?.value;
  const cartId = jar.get(CART_COOKIE)?.value;

  // Map /api/cart[/items[/:variantId]] -> Django /cart/[items/[:variantId/]]
  const path = segments.length ? `/cart/${segments.join("/")}/` : "/cart/";
  const cart = await apiFetch<Cart>(path, { method, body, country, token, cartId });

  // Persist the authoritative guest cart id (backend creates one on first call).
  // For an authed user the cart is server-owned; we still cache the id harmlessly.
  if (cart?.id && cart.id !== cartId) {
    jar.set(CART_COOKIE, cart.id, cookieOptions());
  }
  return json(cart);
}

async function handle(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const body = req.method === "GET" || req.method === "DELETE"
    ? undefined
    : await req.json().catch(() => ({}));
  try {
    return await proxy(req.method, path, body);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Cart error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/app/api/cart
```
Expected: PASS.

- [ ] **Step 5: Mutation-verify**

In `proxy`, remove the `jar.set(CART_COOKIE, cart.id, …)` line. Confirm the "persists the returned cart id" test goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add storefront/src/app/api/cart
git commit -m "feat(storefront): cart BFF route handler with httpOnly cart_id lifecycle

Reads country + access + cart_id from cookies, forwards X-Country/X-Cart-Id/Bearer
to Django, and persists the authoritative cart id back into an httpOnly cookie.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: TanStack Query provider + `useCart` hook + CartDrawer

**Why:** the cart is the one piece of genuinely interactive, optimistic client state. TanStack Query owns it: `useCart` reads `/api/cart` and mutates through the BFF with optimistic updates + rollback. `CartDrawer` is the slide-over UI. Everything else stays server-rendered. Verified by build + a hook-reducer unit test (optimistic math), not full DOM snapshots.

**Files:**
- Create: `storefront/src/components/providers.tsx`
- Create: `storefront/src/hooks/useCart.ts`
- Create: `storefront/src/lib/cart-types.ts`
- Create: `storefront/src/components/layout/CartDrawer.tsx`
- Modify: `storefront/src/app/layout.tsx` (wrap children in `<Providers>`)
- Test: `storefront/src/hooks/__tests__/useCart.test.ts` (optimistic reducer only)

- [ ] **Step 1: Cart types**

`storefront/src/lib/cart-types.ts`:

```ts
export interface CartLine {
  id: number;
  variant_id: number;
  sku: string;
  name: string;
  variant_name: Record<string, string>;
  quantity: number;
  unit_price: string | null;
  line_total: string | null;
  unavailable: boolean;
}
export interface Cart {
  id: string;
  kind: string;
  status: string;
  country: string;
  currency: string;
  items: CartLine[];
  subtotal: string;
  has_unavailable: boolean;
}
export const EMPTY_CART: Cart = {
  id: "", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [], subtotal: "0.00", has_unavailable: false,
};
```

- [ ] **Step 2: Write the failing test (optimistic reducer)**

`storefront/src/hooks/__tests__/useCart.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { applyOptimisticQty } from "@/hooks/useCart";
import type { Cart } from "@/lib/cart-types";

const cart: Cart = {
  id: "c1", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [
    { id: 1, variant_id: 10, sku: "A", name: "A", variant_name: {}, quantity: 2, unit_price: "100.00", line_total: "200.00", unavailable: false },
  ],
  subtotal: "200.00", has_unavailable: false,
};

describe("applyOptimisticQty", () => {
  it("updates a line quantity and recomputes its line total + subtotal", () => {
    const next = applyOptimisticQty(cart, 10, 3);
    expect(next.items[0].quantity).toBe(3);
    expect(next.items[0].line_total).toBe("300.00");
    expect(next.subtotal).toBe("300.00");
  });

  it("removes the line when quantity hits 0", () => {
    const next = applyOptimisticQty(cart, 10, 0);
    expect(next.items).toHaveLength(0);
    expect(next.subtotal).toBe("0.00");
  });

  it("is a no-op for an unknown variant", () => {
    const next = applyOptimisticQty(cart, 999, 5);
    expect(next.items[0].quantity).toBe(2);
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
npm run test -- --run src/hooks/__tests__/useCart.test.ts
```
Expected: FAIL — `applyOptimisticQty` not exported.

- [ ] **Step 4: Implement `useCart.ts`**

`storefront/src/hooks/useCart.ts`:

```ts
"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Cart } from "@/lib/cart-types";
import { EMPTY_CART } from "@/lib/cart-types";

const KEY = ["cart"] as const;

/** Pure optimistic recompute — exported for unit testing. Never rounds; the server
 * re-resolves and returns authoritative strings, this is just instant UI feedback. */
export function applyOptimisticQty(cart: Cart, variantId: number, qty: number): Cart {
  const items = cart.items
    .map((l) => {
      if (l.variant_id !== variantId) return l;
      if (qty <= 0) return null;
      const unit = Number(l.unit_price ?? "0");
      return { ...l, quantity: qty, line_total: (unit * qty).toFixed(2) };
    })
    .filter((l): l is Cart["items"][number] => l !== null);
  const subtotal = items
    .filter((l) => !l.unavailable)
    .reduce((s, l) => s + Number(l.line_total ?? "0"), 0)
    .toFixed(2);
  return { ...cart, items, subtotal };
}

async function fetchCart(): Promise<Cart> {
  const res = await fetch("/api/cart", { method: "GET" });
  return res.ok ? res.json() : EMPTY_CART;
}

export function useCart() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: KEY, queryFn: fetchCart, staleTime: 30_000 });

  const setQty = useMutation({
    mutationFn: async (v: { variantId: number; quantity: number }) => {
      const res = await fetch(`/api/cart/items/${v.variantId}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ quantity: v.quantity }),
      });
      return res.json() as Promise<Cart>;
    },
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: KEY });
      const prev = qc.getQueryData<Cart>(KEY);
      if (prev) qc.setQueryData(KEY, applyOptimisticQty(prev, v.variantId, v.quantity));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(KEY, ctx.prev); },
    onSettled: (data) => { if (data) qc.setQueryData(KEY, data); },
  });

  const addItem = useMutation({
    mutationFn: async (v: { variantId: number; quantity: number }) => {
      const res = await fetch("/api/cart/items", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: v.variantId, quantity: v.quantity }),
      });
      return res.json() as Promise<Cart>;
    },
    onSuccess: (data) => qc.setQueryData(KEY, data),
  });

  return { cart: query.data ?? EMPTY_CART, isLoading: query.isLoading, addItem, setQty };
}
```

- [ ] **Step 5: Providers + CartDrawer**

`storefront/src/components/providers.tsx`:

```tsx
"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

`storefront/src/components/layout/CartDrawer.tsx`:

```tsx
"use client";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";

export function CartDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { cart, setQty } = useCart();
  return (
    <div
      aria-hidden={!open}
      className={`fixed inset-0 z-50 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
    >
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside
        role="dialog"
        aria-label="Shopping bag"
        className={`absolute right-0 top-0 h-full w-full max-w-md bg-surface shadow-xl transition-transform ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <header className="flex items-center justify-between border-b border-line p-5">
          <h2 className="font-display text-xl">Your bag</h2>
          <button onClick={onClose} aria-label="Close bag" className="text-muted hover:text-foreground">✕</button>
        </header>
        <div className="max-h-[calc(100%-9rem)] overflow-y-auto p-5">
          {cart.items.length === 0 ? (
            <p className="text-muted">Your bag is empty.</p>
          ) : (
            cart.items.map((l) => (
              <div key={l.id} className="flex items-center justify-between border-b border-line py-3">
                <div>
                  <p className="font-medium">{l.name}</p>
                  <p className="text-sm text-muted">Qty {l.quantity}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span>{l.line_total ? formatMoney(l.line_total, cart.currency, "") : "—"}</span>
                  <button
                    aria-label={`Remove ${l.name}`}
                    onClick={() => setQty.mutate({ variantId: l.variant_id, quantity: 0 })}
                    className="text-muted hover:text-foreground"
                  >✕</button>
                </div>
              </div>
            ))
          )}
        </div>
        <footer className="absolute bottom-0 w-full border-t border-line p-5">
          <div className="mb-3 flex justify-between font-medium">
            <span>Subtotal</span>
            <span>{formatMoney(cart.subtotal, cart.currency, "")}</span>
          </div>
          <a href="/checkout" className="block rounded-[var(--radius-card)] bg-accent py-3 text-center text-surface hover:bg-accent-strong transition-colors">
            Checkout
          </a>
        </footer>
      </aside>
    </div>
  );
}
```

- [ ] **Step 6: Wrap the app in Providers**

In `storefront/src/app/layout.tsx`, import `{ Providers }` and wrap `{children}`:

```tsx
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Providers>{children}</Providers>
      </body>
```

- [ ] **Step 7: Run tests + build**

```bash
npm run test -- --run src/hooks/__tests__/useCart.test.ts
npm run build
```
Expected: tests PASS; build clean.

- [ ] **Step 8: Mutation-verify**

In `applyOptimisticQty`, change `(unit * qty).toFixed(2)` to `l.line_total`. Confirm the "recomputes its line total + subtotal" test goes RED. Revert.

- [ ] **Step 9: Commit**

```bash
git add storefront/src/components/providers.tsx storefront/src/hooks storefront/src/lib/cart-types.ts storefront/src/components/layout/CartDrawer.tsx storefront/src/app/layout.tsx
git commit -m "feat(storefront): TanStack Query provider, useCart (optimistic) + CartDrawer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Header — logo, category nav, country switcher, account menu, cart button

**Why:** the top of every page. It is a Server Component (fetches the category tree + market list + the logged-in user server-side) that renders small client islands: the country switcher (writes the `country` cookie and refreshes), the account menu, and the cart button (opens the drawer, shows the live count). Verified by build + eyeballing against the running backend.

**Files:**
- Create: `storefront/src/components/layout/Header.tsx` (server)
- Create: `storefront/src/components/layout/CountrySwitcher.tsx` (client)
- Create: `storefront/src/components/layout/AccountMenu.tsx` (client)
- Create: `storefront/src/components/layout/CartButton.tsx` (client)
- Create: `storefront/src/app/api/country/route.ts` (sets the `country` cookie)
- Test: `storefront/src/app/api/country/__tests__/route.test.ts`

- [ ] **Step 1: Failing test — the country-set route**

`storefront/src/app/api/country/__tests__/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({ set: (n: string, v: string) => setSpy(n, v) }),
}));

import { POST } from "@/app/api/country/route";

beforeEach(() => { store.clear(); setSpy.mockClear(); });

describe("country set route", () => {
  it("stores an uppercased known market in the country cookie (not httpOnly)", async () => {
    const res = await POST(new Request("http://localhost:3000/api/country", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: "gb" }),
    }));
    expect(res.status).toBe(200);
    expect(setSpy).toHaveBeenCalled();
    expect(setSpy.mock.calls[0][0]).toBe("country");
    expect(setSpy.mock.calls[0][1]).toBe("GB");
    const options = setSpy.mock.calls[0][2] as { httpOnly?: boolean };
    expect(options.httpOnly).toBeFalsy();
  });

  it("rejects an empty code", async () => {
    const res = await POST(new Request("http://localhost:3000/api/country", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({}),
    }));
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/app/api/country
```
Expected: FAIL — route not found.

- [ ] **Step 3: Implement the country-set route**

`storefront/src/app/api/country/route.ts`:

```ts
import { cookies } from "next/headers";
import { COUNTRY_COOKIE } from "@/lib/country";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const code = typeof body.code === "string" ? body.code.trim().toUpperCase() : "";
  if (!code) return new Response(JSON.stringify({ detail: "code required" }), { status: 400 });
  // country is NOT httpOnly: it is not a secret and client UI reads it. 1 year.
  (await cookies()).set(COUNTRY_COOKIE, code, {
    httpOnly: false, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 365,
    secure: process.env.NODE_ENV === "production",
  });
  return new Response(JSON.stringify({ ok: true }), { status: 200 });
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/app/api/country
```
Expected: PASS.

- [ ] **Step 5: Client islands**

`storefront/src/components/layout/CountrySwitcher.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { Market } from "@/lib/country";
import { labelFor } from "@/lib/country";

export function CountrySwitcher({ markets, current }: { markets: Market[]; current: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [value, setValue] = useState(current);

  function change(code: string) {
    setValue(code);
    start(async () => {
      await fetch("/api/country", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ code }),
      });
      router.refresh(); // re-render server components with the new country -> new prices
    });
  }

  return (
    <label className="flex items-center gap-1 text-sm">
      <span className="sr-only">Country and currency</span>
      <select
        value={value}
        disabled={pending}
        onChange={(e) => change(e.target.value)}
        className="bg-transparent text-foreground focus:outline-none"
      >
        {markets.map((m) => (
          <option key={m.code} value={m.code}>
            {labelFor(m)} — {m.currency.code}
          </option>
        ))}
      </select>
    </label>
  );
}
```

`storefront/src/components/layout/CartButton.tsx`:

```tsx
"use client";
import { useState } from "react";
import { useCart } from "@/hooks/useCart";
import { CartDrawer } from "@/components/layout/CartDrawer";

export function CartButton() {
  const [open, setOpen] = useState(false);
  const { cart } = useCart();
  const count = cart.items.reduce((n, l) => n + l.quantity, 0);
  return (
    <>
      <button onClick={() => setOpen(true)} className="relative" aria-label={`Bag, ${count} items`}>
        Bag
        {count > 0 && (
          <span className="absolute -right-3 -top-2 rounded-full bg-accent px-1.5 text-xs text-surface">
            {count}
          </span>
        )}
      </button>
      <CartDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
```

`storefront/src/components/layout/AccountMenu.tsx`:

```tsx
"use client";
import Link from "next/link";

export function AccountMenu({ signedIn }: { signedIn: boolean }) {
  return signedIn ? (
    <Link href="/account" className="text-sm hover:text-accent">Account</Link>
  ) : (
    <Link href="/login" className="text-sm hover:text-accent">Sign in</Link>
  );
}
```

- [ ] **Step 6: Header (server component)**

`storefront/src/components/layout/Header.tsx`:

```tsx
import Image from "next/image";
import Link from "next/link";
import { cookies } from "next/headers";
import { getMarkets, COUNTRY_COOKIE, DEFAULT_COUNTRY, normalizeCountry } from "@/lib/country";
import { apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import { CartButton } from "@/components/layout/CartButton";
import { AccountMenu } from "@/components/layout/AccountMenu";
import { MobileNav } from "@/components/layout/MobileNav";

interface Category { name: string; slug: string; children: Category[] }

export async function Header() {
  const jar = await cookies();
  const markets = await getMarkets().catch(() => []);
  const country = normalizeCountry(
    jar.get(COUNTRY_COOKIE)?.value, markets.map((m) => m.code),
  ) || DEFAULT_COUNTRY;
  const categories = await apiFetch<Category[]>("/categories/", {
    country, next: { revalidate: 3600 },
  }).catch(() => []);
  const signedIn = Boolean(await getAccessToken());

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-cream/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-3">
          <MobileNav categories={categories} />
          <Link href="/" className="flex items-center gap-2">
            <Image src="/logos/toke-logo.png" alt="Toke Cosmetics" width={96} height={56} priority />
          </Link>
        </div>
        <nav className="hidden items-center gap-6 md:flex">
          {categories.slice(0, 6).map((c) => (
            <Link key={c.slug} href={`/category/${c.slug}`} className="text-sm hover:text-accent">
              {c.name}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-5">
          <CountrySwitcher markets={markets} current={country} />
          <AccountMenu signedIn={signedIn} />
          <CartButton />
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 7: Build + eyeball against the running backend**

```bash
npm run build && npm run dev
```
With the backend running, open `http://localhost:3000`: the header shows the logo, up to 6 category links (or none if catalog is unseeded — acceptable), a country/currency `select`, a Sign in link, and a Bag button. Change the switcher NG→GB and confirm the page refreshes (network tab shows `POST /api/country` then a document refresh). (`Header`/`MobileNav` render once Task 11 + 12 mount them; if verifying before then, temporarily import `Header` into `page.tsx`.)

- [ ] **Step 8: Commit**

```bash
git add storefront/src/components/layout/Header.tsx storefront/src/components/layout/CountrySwitcher.tsx storefront/src/components/layout/CartButton.tsx storefront/src/components/layout/AccountMenu.tsx storefront/src/app/api/country
git commit -m "feat(storefront): header with logo, category nav, country switcher, cart button

Server component fetches categories + markets + session; client islands for the
switcher (writes country cookie + router.refresh), account menu and cart button.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Footer — policy links, newsletter capture (wired to the real endpoint), payment logos

**Why:** the footer captures newsletter sign-ups into the real backend from day one (the list must grow before Plan-30 sends anything). The form posts to a same-origin `/api/newsletter` Route Handler that proxies Django's throttled public endpoint and forwards the caller's IP (D5). Policy links point at the CMS `/page/[slug]` skeleton routes (real CMS is Plan-19).

**Files:**
- Create: `storefront/src/app/api/newsletter/route.ts`
- Create: `storefront/src/components/layout/NewsletterForm.tsx` (client)
- Create: `storefront/src/components/layout/Footer.tsx` (server)
- Create: `storefront/public/logos/payments/` (placeholder SVGs: visa, mastercard, verve, paystack, bank-transfer)
- Test: `storefront/src/app/api/newsletter/__tests__/route.test.ts`

- [ ] **Step 1: Failing test — newsletter route**

`storefront/src/app/api/newsletter/__tests__/route.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { POST } from "@/app/api/newsletter/route";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}
function req(body: unknown, ip = "1.2.3.4") {
  return new Request("http://localhost:3000/api/newsletter", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: JSON.stringify(body),
  });
}

describe("newsletter BFF", () => {
  it("proxies a subscribe to Django and forwards the client IP", async () => {
    const f = upstream(201, { detail: "Subscribed." });
    const res = await POST(req({ email: "a@b.com", source: "footer" }));
    expect(res.status).toBe(201);
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/newsletter/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Forwarded-For")).toBe("1.2.3.4");
  });

  it("passes through a 429 throttle response", async () => {
    upstream(429, { detail: "Request was throttled." });
    const res = await POST(req({ email: "a@b.com" }));
    expect(res.status).toBe(429);
  });

  it("rejects a missing email locally with 400 (no upstream call)", async () => {
    const f = upstream(201, {});
    const res = await POST(req({}));
    expect(res.status).toBe(400);
    expect(f).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/app/api/newsletter
```
Expected: FAIL — route not found.

- [ ] **Step 3: Implement the newsletter route**

`storefront/src/app/api/newsletter/route.ts`:

```ts
import { apiFetch, ApiError } from "@/lib/api";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const email = typeof body.email === "string" ? body.email.trim() : "";
  if (!email || !email.includes("@")) return json({ email: ["Enter a valid email."] }, 400);

  // Forward the caller's IP so Django's per-IP throttle counts real users, not our
  // server (see Plan-12 D5; prod must trust X-Forwarded-For — Plan-02 note).
  const ip = req.headers.get("x-forwarded-for") ?? "";
  try {
    const out = await apiFetch("/newsletter/", {
      method: "POST",
      body: { email, source: body.source ?? "footer" },
      headers: ip ? { "X-Forwarded-For": ip } : {},
    });
    return json(out, 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/app/api/newsletter
```
Expected: PASS.

- [ ] **Step 5: NewsletterForm (client)**

`storefront/src/components/layout/NewsletterForm.tsx`:

```tsx
"use client";
import { useState } from "react";

export function NewsletterForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("loading");
    const res = await fetch("/api/newsletter", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, source: "footer" }),
    });
    setState(res.ok ? "done" : "error");
  }

  if (state === "done") return <p className="text-sm text-leaf">Thanks — you are on the list.</p>;

  return (
    <form onSubmit={submit} className="flex gap-2">
      <label className="sr-only" htmlFor="nl-email">Email address</label>
      <input
        id="nl-email" type="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} placeholder="Your email"
        className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm"
      />
      <button
        type="submit" disabled={state === "loading"}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface hover:bg-accent-strong transition-colors disabled:opacity-60"
      >
        {state === "loading" ? "…" : "Subscribe"}
      </button>
      {state === "error" && <span className="text-sm text-red-600">Try again.</span>}
    </form>
  );
}
```

- [ ] **Step 6: Footer (server component)**

`storefront/src/components/layout/Footer.tsx`:

```tsx
import Link from "next/link";
import { NewsletterForm } from "@/components/layout/NewsletterForm";

const POLICIES = [
  ["Contact us", "/page/contact"],
  ["Shipping & delivery", "/page/shipping"],
  ["Returns & refunds", "/page/returns"],
  ["Privacy policy", "/page/privacy"],
  ["Terms & conditions", "/page/terms"],
] as const;

const PAYMENTS = ["visa", "mastercard", "verve", "paystack", "bank-transfer"];

export function Footer() {
  return (
    <footer className="mt-16 border-t border-line bg-surface">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 md:grid-cols-3">
        <div>
          <h3 className="font-display text-lg">Toke Cosmetics</h3>
          <p className="mt-2 text-sm text-muted">Premium beauty, shipped worldwide.</p>
        </div>
        <nav aria-label="Footer" className="grid gap-2">
          {POLICIES.map(([label, href]) => (
            <Link key={href} href={href} className="text-sm text-muted hover:text-accent">{label}</Link>
          ))}
        </nav>
        <div>
          <h4 className="text-sm font-medium">Join our list</h4>
          <p className="mt-1 text-sm text-muted">Offers, launches and beauty tips.</p>
          <div className="mt-3"><NewsletterForm /></div>
        </div>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-5 text-xs text-muted md:flex-row">
          <span>© {new Date().getFullYear()} Toke Cosmetics. All rights reserved.</span>
          <ul className="flex items-center gap-3">
            {PAYMENTS.map((p) => (
              <li key={p} className="rounded border border-line px-2 py-1 capitalize">{p.replace("-", " ")}</li>
            ))}
          </ul>
        </div>
      </div>
    </footer>
  );
}
```

(Payment logos: text chips are the acceptable placeholder for the foundation; drop real SVGs into `public/logos/payments/` and swap the `<li>` for `<Image>` when Hammed provides brand-approved marks. Do not scrape third-party logo files.)

- [ ] **Step 7: Build + integration check**

```bash
npm run build
```
Then with the backend running, `npm run dev`, submit the footer form with a test email, and confirm in the backend shell that the row landed:
```bash
cd tokecosmetics-platform/backend
uv run python manage.py shell -c "from apps.newsletter.models import NewsletterSubscriber; print(NewsletterSubscriber.objects.values_list('email','source'))"
```
Expected: your test email appears with source `footer`.

- [ ] **Step 8: Mutation-verify**

In the newsletter route, change the guard to `if (false)`. Confirm the "rejects a missing email" test goes RED. Revert.

- [ ] **Step 9: Commit**

```bash
git add storefront/src/app/api/newsletter storefront/src/components/layout/NewsletterForm.tsx storefront/src/components/layout/Footer.tsx
git commit -m "feat(storefront): footer with policy links + live newsletter capture

Newsletter posts through a same-origin BFF route that forwards the client IP so
Django's per-IP throttle stays meaningful; policy links point at /page/[slug].

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Mobile nav + search bar stub

**Why:** the header references `MobileNav`; mobile-first means the nav must collapse into a drawer under `md`. The search bar is a visible stub here (real search is Plan-13) so the layout is complete and the input routes to `/search`.

**Files:**
- Create: `storefront/src/components/layout/MobileNav.tsx` (client)
- Create: `storefront/src/components/layout/SearchBar.tsx` (client)
- Modify: `storefront/src/components/layout/Header.tsx` (mount `SearchBar`)

- [ ] **Step 1: MobileNav**

`storefront/src/components/layout/MobileNav.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useState } from "react";

interface Category { name: string; slug: string }

export function MobileNav({ categories }: { categories: Category[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="md:hidden">
      <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-xl">☰</button>
      {open && (
        <div className="fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <nav className="absolute left-0 top-0 h-full w-72 bg-surface p-6" aria-label="Mobile">
            <button onClick={() => setOpen(false)} aria-label="Close menu" className="mb-6 text-muted">✕</button>
            <ul className="grid gap-3">
              {categories.map((c) => (
                <li key={c.slug}>
                  <Link href={`/category/${c.slug}`} onClick={() => setOpen(false)} className="hover:text-accent">
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: SearchBar stub**

`storefront/src/components/layout/SearchBar.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (q.trim()) router.push(`/search?q=${encodeURIComponent(q)}`); }}
      role="search"
      className="hidden flex-1 md:block"
    >
      <label className="sr-only" htmlFor="site-search">Search products</label>
      <input
        id="site-search" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="Search products…"
        className="w-full rounded-full border border-line bg-surface px-4 py-2 text-sm"
      />
    </form>
  );
}
```

- [ ] **Step 3: Mount SearchBar in the Header**

In `Header.tsx`, import `SearchBar` and place it between the nav and the right-side controls:

```tsx
        <SearchBar />
```

- [ ] **Step 4: Build + eyeball**

```bash
npm run build && npm run dev
```
Resize below `md`: the category links collapse into the ☰ drawer; the search bar hides on mobile and shows on desktop. Typing a query + Enter navigates to `/search?q=…` (a 404 until Task 12 adds the route — expected).

- [ ] **Step 5: Commit**

```bash
git add storefront/src/components/layout/MobileNav.tsx storefront/src/components/layout/SearchBar.tsx storefront/src/components/layout/Header.tsx
git commit -m "feat(storefront): mobile nav drawer + search bar stub (routes to /search)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Skeleton routes + shop layout wiring the shell

**Why:** the nav links must all resolve. Add a `(shop)` route group whose layout renders `<Header/>` + `<Footer/>` around every page, plus placeholder pages for every path in the spec so navigation works end-to-end. Auth pages live in an `(auth)` group without the shop chrome distractions (still same shell fonts/tokens).

**Files:**
- Create: `storefront/src/app/(shop)/layout.tsx`
- Create shop pages: `storefront/src/app/(shop)/page.tsx` (home — move from root), `products/page.tsx`, `product/[slug]/page.tsx`, `category/[slug]/page.tsx`, `search/page.tsx`, `cart/page.tsx`, `checkout/page.tsx`, `account/page.tsx`, `page/[slug]/page.tsx`
- Create auth pages: `storefront/src/app/(auth)/login/page.tsx`, `(auth)/register/page.tsx`
- Delete: `storefront/src/app/page.tsx` (the temporary demo — now `(shop)/page.tsx`)

- [ ] **Step 1: Shop layout**

`storefront/src/app/(shop)/layout.tsx`:

```tsx
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";

export default function ShopLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </>
  );
}
```

- [ ] **Step 2: A reusable placeholder + the pages**

Create each page below. Home (`(shop)/page.tsx`):

```tsx
export default function HomePage() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-16">
      <h1 className="font-display text-5xl">Beauty, elevated.</h1>
      <p className="mt-4 max-w-prose text-muted">
        Full storefront lands in Plan-13. This is the foundation shell.
      </p>
    </section>
  );
}
```

For the remaining routes use this shape (change the heading + the `[slug]`/`q` readout per route). **Write each file out in full — do not leave any as "same as above."**

`products/page.tsx`:
```tsx
export default function ProductsPage() {
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">All products</h1><p className="mt-4 text-muted">Listing arrives in Plan-13.</p></section>;
}
```
`product/[slug]/page.tsx` (Next 16: `params` is a Promise — verify in bundled docs):
```tsx
export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Product: {slug}</h1><p className="mt-4 text-muted">Detail page arrives in Plan-13.</p></section>;
}
```
`category/[slug]/page.tsx`:
```tsx
export default async function CategoryPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Category: {slug}</h1><p className="mt-4 text-muted">Listing arrives in Plan-13.</p></section>;
}
```
`search/page.tsx` (Next 16: `searchParams` is a Promise):
```tsx
export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q } = await searchParams;
  return <section className="mx-auto max-w-7xl px-4 py-16"><h1 className="font-display text-4xl">Search{q ? `: ${q}` : ""}</h1><p className="mt-4 text-muted">Search results arrive in Plan-13.</p></section>;
}
```
`cart/page.tsx`:
```tsx
export default function CartPage() {
  return <section className="mx-auto max-w-3xl px-4 py-16"><h1 className="font-display text-4xl">Your bag</h1><p className="mt-4 text-muted">Full cart page arrives with checkout (Plan-14).</p></section>;
}
```
`checkout/page.tsx` (placeholder ONLY — no money logic; Plan-14 owns checkout):
```tsx
export default function CheckoutPage() {
  return <section className="mx-auto max-w-3xl px-4 py-16"><h1 className="font-display text-4xl">Checkout</h1><p className="mt-4 text-muted">Checkout is built in Plan-14.</p></section>;
}
```
`account/page.tsx`:
```tsx
export default function AccountPage() {
  return <section className="mx-auto max-w-3xl px-4 py-16"><h1 className="font-display text-4xl">My account</h1><p className="mt-4 text-muted">Account area arrives in a later plan.</p></section>;
}
```
`page/[slug]/page.tsx`:
```tsx
export default async function CmsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <section className="mx-auto max-w-3xl px-4 py-16"><h1 className="font-display text-4xl capitalize">{slug.replace(/-/g, " ")}</h1><p className="mt-4 text-muted">CMS content arrives in Plan-19.</p></section>;
}
```

- [ ] **Step 3: Auth pages**

`(auth)/login/page.tsx`:
```tsx
export default function LoginPage() {
  return <section className="mx-auto max-w-md px-4 py-16"><h1 className="font-display text-4xl">Sign in</h1><p className="mt-4 text-muted">Login form arrives in a later plan; the auth BFF is already wired.</p></section>;
}
```
`(auth)/register/page.tsx`:
```tsx
export default function RegisterPage() {
  return <section className="mx-auto max-w-md px-4 py-16"><h1 className="font-display text-4xl">Create account</h1><p className="mt-4 text-muted">Register form arrives in a later plan; the auth BFF is already wired.</p></section>;
}
```

(Auth pages have no shop `Header`/`Footer` by default. If Hammed wants the header on them too, add an `(auth)/layout.tsx` that renders `<Header/>` — flag as a small preference, not a blocker.)

- [ ] **Step 4: Remove the temporary root page**

```bash
rm storefront/src/app/page.tsx
```
(The home page now lives at `(shop)/page.tsx`; the `(shop)` group has no URL prefix, so `/` still resolves.)

- [ ] **Step 5: Build + click every route**

```bash
npm run build && npm run dev
```
Expected: build clean. Visit `/`, `/products`, `/product/test-slug`, `/category/skincare`, `/search?q=lip`, `/cart`, `/checkout`, `/account`, `/login`, `/register`, `/page/contact` — each renders with the header + footer (auth pages without shop chrome) and no console errors. Every header/footer link resolves (no 404s).

- [ ] **Step 6: Commit**

```bash
git add storefront/src/app
git rm storefront/src/app/page.tsx 2>/dev/null || true
git commit -m "feat(storefront): (shop)/(auth) route groups + skeleton pages for every path

Shop layout wraps pages in Header/Footer; placeholder pages so all nav resolves.
Checkout is a placeholder only — Plan-14 owns real checkout.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Error, not-found, and loading UX

**Why:** an app shell must fail gracefully. Add a root `error.tsx` (client, per Next), a branded `not-found.tsx`, a root `loading.tsx`, and per-section loading skeletons so route transitions never flash a blank screen.

**Files:**
- Create: `storefront/src/app/error.tsx` (client)
- Create: `storefront/src/app/not-found.tsx`
- Create: `storefront/src/app/loading.tsx`
- Create: `storefront/src/app/(shop)/products/loading.tsx`, `(shop)/category/[slug]/loading.tsx`, `(shop)/product/[slug]/loading.tsx`
- Create: `storefront/src/components/ui/Skeleton.tsx`

- [ ] **Step 1: Skeleton primitive**

`storefront/src/components/ui/Skeleton.tsx`:

```tsx
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-line/70 ${className}`} aria-hidden />;
}
```

- [ ] **Step 2: Root error boundary**

`storefront/src/app/error.tsx`:

```tsx
"use client";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-lg px-4 py-24 text-center">
      <h1 className="font-display text-4xl">Something went wrong</h1>
      <p className="mt-4 text-muted">Please try again. If it keeps happening, contact us.</p>
      <button onClick={reset} className="mt-8 rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Try again
      </button>
    </main>
  );
}
```

- [ ] **Step 3: not-found**

`storefront/src/app/not-found.tsx`:

```tsx
import Link from "next/link";
export default function NotFound() {
  return (
    <main className="mx-auto max-w-lg px-4 py-24 text-center">
      <h1 className="font-display text-5xl">404</h1>
      <p className="mt-4 text-muted">We couldn&apos;t find that page.</p>
      <Link href="/" className="mt-8 inline-block rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Back to home
      </Link>
    </main>
  );
}
```

- [ ] **Step 4: Loading skeletons**

`storefront/src/app/loading.tsx`:

```tsx
import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-16">
      <Skeleton className="h-10 w-1/3" />
      <Skeleton className="mt-6 h-64 w-full" />
    </div>
  );
}
```

`(shop)/products/loading.tsx`, `(shop)/category/[slug]/loading.tsx` (a product-grid skeleton — write the same content into both files):

```tsx
import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-4 py-16 md:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i}>
          <Skeleton className="aspect-square w-full" />
          <Skeleton className="mt-3 h-4 w-3/4" />
          <Skeleton className="mt-2 h-4 w-1/2" />
        </div>
      ))}
    </div>
  );
}
```

`(shop)/product/[slug]/loading.tsx`:

```tsx
import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 md:grid-cols-2">
      <Skeleton className="aspect-square w-full" />
      <div>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-4 h-6 w-1/3" />
        <Skeleton className="mt-8 h-12 w-full" />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Build + eyeball**

```bash
npm run build && npm run dev
```
Visit a bad URL (`/definitely-not-real`) → branded 404. Throttle the network in devtools and navigate to `/products` → grid skeleton flashes before content. Force an error (temporarily `throw new Error("x")` in `(shop)/products/page.tsx`, load it) → the error boundary shows with a working "Try again". Revert the thrown error.

- [ ] **Step 6: Commit**

```bash
git add storefront/src/app/error.tsx storefront/src/app/not-found.tsx storefront/src/app/loading.tsx storefront/src/app/\(shop\) storefront/src/components/ui/Skeleton.tsx
git commit -m "feat(storefront): root error/not-found + loading skeletons

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: Middleware — country cookie default + first-visit suggestion (never forced)

**Why:** the country context must exist on the very first request (so Server Components have a market) and a first-time visitor from the UK should be *offered* GBP — but user choice always wins (a hard geo-redirect is explicitly forbidden by requirements). Middleware sets the default `country` cookie if absent and passes a geo *suggestion* header the client banner reads once.

**Files:**
- Create: `storefront/src/middleware.ts`
- Create: `storefront/src/lib/geo.ts` (pure suggestion logic — unit tested)
- Create: `storefront/src/components/layout/CountrySuggestionBanner.tsx` (client)
- Modify: `storefront/src/app/(shop)/layout.tsx` (mount the banner)
- Test: `storefront/src/lib/__tests__/geo.test.ts`

- [ ] **Step 1: Failing test — suggestion logic**

`storefront/src/lib/__tests__/geo.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { suggestionFor } from "@/lib/geo";

const MARKETS = ["NG", "GB", "US", "CA", "ZZ"];

describe("suggestionFor", () => {
  it("suggests nothing when the user already has a country cookie", () => {
    expect(suggestionFor("GB", "NG", MARKETS)).toBeNull();
  });
  it("suggests the geo market when it is a real market and differs from the default", () => {
    expect(suggestionFor(undefined, "GB", MARKETS)).toBe("GB");
  });
  it("suggests nothing when geo equals the NG default", () => {
    expect(suggestionFor(undefined, "NG", MARKETS)).toBeNull();
  });
  it("suggests ZZ for an unknown geo country (international)", () => {
    expect(suggestionFor(undefined, "FR", MARKETS)).toBe("ZZ");
  });
  it("suggests nothing when geo is absent", () => {
    expect(suggestionFor(undefined, undefined, MARKETS)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test -- --run src/lib/__tests__/geo.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `lib/geo.ts`**

`storefront/src/lib/geo.ts`:

```ts
import { DEFAULT_COUNTRY, REST_OF_WORLD } from "@/lib/country";

/**
 * What (if anything) to SUGGEST to a visitor. Never forces — the caller only shows a
 * dismissable banner. Returns null when there is nothing worth suggesting.
 *  - existing cookie present -> null (their choice is set; leave it alone)
 *  - geo absent -> null
 *  - geo is the NG default -> null (already correct)
 *  - geo is another real market -> that market
 *  - geo is an unknown country -> ZZ (international)
 */
export function suggestionFor(
  existingCookie: string | undefined,
  geoCountry: string | undefined,
  validCodes: string[],
): string | null {
  if (existingCookie) return null;
  if (!geoCountry) return null;
  const geo = geoCountry.toUpperCase();
  if (geo === DEFAULT_COUNTRY) return null;
  if (validCodes.includes(geo)) return geo;
  return validCodes.includes(REST_OF_WORLD) ? REST_OF_WORLD : null;
}
```

- [ ] **Step 4: Run tests**

```bash
npm run test -- --run src/lib/__tests__/geo.test.ts
```
Expected: PASS.

- [ ] **Step 5: Middleware**

`storefront/src/middleware.ts` (verify `NextResponse`/matcher API against the bundled Next 16 docs):

```ts
import { NextResponse, type NextRequest } from "next/server";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

// Static list mirroring the active markets (kept in sync with /meta/countries/; the
// authoritative check happens server-side in normalizeCountry — this is only for the
// first-request default + the geo suggestion so we avoid an API call in middleware).
const MARKET_CODES = ["NG", "GB", "US", "CA", "ZZ"];

export function middleware(req: NextRequest) {
  const res = NextResponse.next();
  const existing = req.cookies.get(COUNTRY_COOKIE)?.value;

  // 1. Ensure a country cookie exists from the first request (default NG).
  if (!existing) {
    res.cookies.set(COUNTRY_COOKIE, DEFAULT_COUNTRY, {
      httpOnly: false, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 365,
    });
  }

  // 2. Pass the geo country (Vercel injects x-vercel-ip-country in prod) as a header the
  //    banner reads. NEVER redirect — suggestion only.
  const geo = req.headers.get("x-vercel-ip-country") ?? "";
  res.headers.set("x-geo-country", geo);
  res.headers.set("x-geo-suggest-eligible", existing ? "0" : "1");
  void MARKET_CODES; // used by the banner via /api; kept here as the single source note
  return res;
}

export const config = {
  // Skip static assets + API routes.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|logos|api).*)"],
};
```

- [ ] **Step 6: Suggestion banner (client)**

`storefront/src/components/layout/CountrySuggestionBanner.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { suggestionFor } from "@/lib/geo";

const MARKET_CODES = ["NG", "GB", "US", "CA", "ZZ"];
const DISMISS_KEY = "toke-geo-dismissed";

export function CountrySuggestionBanner({ currentCountry }: { currentCountry: string }) {
  const router = useRouter();
  const [suggest, setSuggest] = useState<string | null>(null);

  useEffect(() => {
    if (localStorage.getItem(DISMISS_KEY)) return;
    // The client can't read the middleware response header directly, so read the geo
    // hint the server passed into the page via a meta tag (set in (shop)/layout.tsx),
    // falling back to no suggestion. currentCountry is the cookie value already in use.
    const geo = document.querySelector<HTMLMetaElement>('meta[name="x-geo-country"]')?.content;
    setSuggest(suggestionFor(undefined, geo, MARKET_CODES) === currentCountry ? null
      : suggestionFor(undefined, geo, MARKET_CODES));
  }, [currentCountry]);

  if (!suggest || suggest === currentCountry) return null;

  async function accept() {
    await fetch("/api/country", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ code: suggest }),
    });
    localStorage.setItem(DISMISS_KEY, "1");
    router.refresh();
  }
  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setSuggest(null);
  }

  return (
    <div className="bg-accent/10 px-4 py-2 text-center text-sm">
      It looks like you&apos;re in {suggest}. Shop in your local currency?{" "}
      <button onClick={accept} className="font-medium text-accent underline">Yes, switch</button>{" "}
      <button onClick={dismiss} className="text-muted underline">No thanks</button>
    </div>
  );
}
```

- [ ] **Step 7: Feed the geo hint + mount the banner**

In `(shop)/layout.tsx`, read the geo header server-side and expose it as a meta tag, then render the banner above the header:

```tsx
import { headers, cookies } from "next/headers";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { CountrySuggestionBanner } from "@/components/layout/CountrySuggestionBanner";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

export default async function ShopLayout({ children }: { children: React.ReactNode }) {
  const geo = (await headers()).get("x-geo-country") ?? "";
  const current = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  return (
    <>
      {geo && <meta name="x-geo-country" content={geo} />}
      <CountrySuggestionBanner currentCountry={current} />
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </>
  );
}
```

- [ ] **Step 8: Build + eyeball**

```bash
npm run build && npm run dev
```
Because `x-vercel-ip-country` is absent locally, the banner stays hidden (correct — nothing to suggest). To exercise it locally, temporarily hard-code `const geo = "GB"` in `(shop)/layout.tsx`, reload with cleared cookies/localStorage → the banner offers GB; "Yes, switch" flips the switcher and refreshes; "No thanks" hides it and stays hidden on reload. Revert the hard-code.

- [ ] **Step 9: Mutation-verify**

In `suggestionFor`, change `if (existingCookie) return null;` to `if (false) …`. Confirm the "suggests nothing when the user already has a country cookie" test goes RED. Revert.

- [ ] **Step 10: Commit**

```bash
git add storefront/src/middleware.ts storefront/src/lib/geo.ts storefront/src/lib/__tests__/geo.test.ts storefront/src/components/layout/CountrySuggestionBanner.tsx storefront/src/app/\(shop\)/layout.tsx
git commit -m "feat(storefront): country middleware + first-visit suggestion banner (never forced)

Middleware sets the NG-default country cookie on first request and passes a geo hint;
a dismissable banner suggests the local market. User choice always wins — no redirect.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 15: Verification checkpoint (build, driven walkthrough, Lighthouse, design sign-off)

**Why:** the master guide gates all of Plan-13 on Hammed approving the design direction *now*. This task proves the shell works end-to-end against the real local backend and produces the artefacts Hammed signs off on. **No new feature code** — verification + docs only.

**Files:**
- Create: `tokecosmetics-platform/docs/architecture.md` § Storefront (append if the file exists)

- [ ] **Step 1: Full test suite + clean build**

```bash
cd tokecosmetics-platform/storefront
npm run test -- --run     # all Vitest suites green
npm run lint              # clean
npm run build             # clean, no type errors, no failed static generation
```
Expected: all green.

- [ ] **Step 2: Driven click-through against the real local backend**

Start the backend (`cd backend && uv run python manage.py runserver 0.0.0.0:8000`) and `npm run dev`, then drive these flows in a browser and record the result of each:

1. **Auth round-trip** — via the BFF (there is no login *form* yet; drive the API directly to prove the plumbing):
   ```bash
   # register + auto-login (sets httpOnly cookies) — save the cookie jar
   curl -i -c jar.txt -X POST http://localhost:3000/api/auth/register \
     -H 'content-type: application/json' \
     -d '{"email":"walkthrough@example.com","password":"Str0ng!pass9","first_name":"Wk"}'
   # me (reads the access cookie server-side)
   curl -s -b jar.txt http://localhost:3000/api/auth/me   # -> {"email":"walkthrough@example.com",...}
   # confirm NO token leaked to the client: the body above has no access/refresh
   # logout (clears cookies)
   curl -i -b jar.txt -X POST http://localhost:3000/api/auth/logout
   ```
   Expected: `me` returns the profile; the JSON bodies never contain a JWT; after logout, `me` returns 401.

2. **Country switch** — open `/`, change the switcher NG→GB, confirm the page refreshes and the switcher shows GBP; devtools → Application → Cookies shows `country=GB` (and `access`/`refresh`/`cart_id` flagged **HttpOnly**, `country` **not**).

3. **Cart add** — pick a real `variant_id` from the backend (`curl -s http://localhost:8000/api/v1/products/ -H 'X-Country: NG'` → a variant), then:
   ```bash
   curl -i -c jar.txt -X POST http://localhost:3000/api/cart/items \
     -H 'content-type: application/json' -d '{"variant_id":<ID>,"quantity":1}'
   curl -s -b jar.txt http://localhost:3000/api/cart   # -> cart with 1 item, cart_id cookie set
   ```
   Then in the browser, open the cart drawer and confirm the count + subtotal render, and removing the line updates optimistically. (If the catalog is unseeded and `/products/` is empty, note it — cart plumbing is still proven by the BFF test suite; seed a variant in the backend shell if a live add is needed.)

4. **Newsletter** — submit the footer form; confirm the subscriber row exists (shell one-liner from Task 10).

- [ ] **Step 3: Lighthouse (mobile) on the shell**

```bash
npx --yes lighthouse http://localhost:3000/ --preset=perf --form-factor=mobile --screenEmulation.mobile --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless" --output=json --output-path=./lighthouse-home.json
```
(Or run Lighthouse from Chrome devtools.) Record the four scores. **Target ≥ 95** on the shell pages. If any is below 95, note the top opportunities (usually: font display, image sizing of the logo, unused JS) and fix the cheap ones before the checkpoint. A shell this light should clear 95 comfortably; the real budget battle is Plan-13's image-heavy pages.

- [ ] **Step 4: Document the storefront architecture**

Append to `tokecosmetics-platform/docs/architecture.md` a `## Storefront foundation (Plan-12)` section covering: the BFF pattern + cookie table (from this plan's Critical Context), why the browser never sees a JWT, the country model (cookie + `X-Country` + `normalizeCountry` mirroring the backend), the single-locale/currency-in-session note, and the `npm run gen:api` regeneration step. Keep it to ~40 lines — link back to this plan for detail.

- [ ] **Step 5: Commit**

```bash
git add tokecosmetics-platform/docs/architecture.md storefront/lighthouse-home.json
git commit -m "docs: storefront foundation architecture + Plan-12 verification artefacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: 🚦 CHECKPOINT — design-direction sign-off (BLOCKS Plan-13)**

Stop. Present to Hammed, in plain language:
- The running shell (screen-share `/` and a couple of skeleton routes, or a short screen recording) showing the header, nav, country switcher, cart drawer, footer, 404, and loading skeletons.
- The **design direction**: cream/near-black + Toke-green accent, Playfair + Inter. **Get explicit approval of the accent green(s) (D1) and the overall look** — Plan-13 builds every page on this foundation, so changing the design after is expensive.
- The Lighthouse scores.
- The four open decisions (D1–D5) with your recommendations, for a yes/no on each — especially **D4 (Vercel account)**: if Hammed connects Vercel now, redeploy this branch as a Vercel preview and send the URL (the master guide's literal checkpoint); otherwise the local walkthrough stands in until he does.

**Do not start Plan-13 until Hammed signs off on the design direction.**

---

## Self-review notes (author checklist — delete on execution)

- **Spec coverage (master lines 907–914):** (1) typed `lib/api.ts` + `openapi-typescript` → Tasks 1/3. (2) auth BFF login/register/logout/refresh/me + silent refresh → Task 6. (3) cart BFF + `CartDrawer` optimistic → Tasks 7/8. (4) Header logo/nav/switcher/account/cart + Footer policies/newsletter/payments → Tasks 9/10/11. (5) skeleton routes for all 11 paths → Task 12. (6) root error/not-found + per-route loading → Task 13. Middleware country cookie + suggestion → Task 14. Tailwind theme → Task 2. Verification + checkpoint → Task 15. ✅ every spec item maps to a task.
- **Guardrails:** no payments/checkout/shipping code touched (checkout is a placeholder page). No JWT ever reaches the browser (Task 6 test asserts it). Money displayed as-is (Task 4 `formatMoney` groups only). ✅
- **Backend gap found:** none blocking. CORS needs NO change because all Django calls are server-side (D2). D5 notes a prod X-Forwarded-For trust config for the newsletter throttle — a Plan-02 note, not a Plan-12 code change.
- **Type consistency:** `Cart`/`CartLine` shapes match the backend serializer (Task 8 vs. Critical Context). `Market` shape matches `CountrySerializer`. Cookie names identical across `lib/auth.ts`, the auth route, the cart route, and middleware. `normalizeCountry`/`REST_OF_WORLD`/`DEFAULT_COUNTRY` used consistently.
