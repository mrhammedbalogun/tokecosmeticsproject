# Plan-15 — Storefront customer account

**Status:** in progress (started 2026-07-27)
**Branch:** `plan-15-storefront-account` (off `main`)
**Depends on:** Plan-12 (storefront foundation), Plan-11 (accounts backend) — both shipped.

Customer dashboard: orders, order detail + tracking, addresses, profile, wishlist, password —
plus the auth pages that make registration and password reset real for the first time.

---

## Design rulings (Fable 5, 2026-07-27)

Fable corrected three claims I had asserted from a first read. All three were verified against
the repo before this plan was written; **correction 3 invalidated my original gating design.**

**C1 — `src/proxy.ts` already exists** (Plan-12/13: seeds the country cookie, sanitizes the geo
header, matcher covers everything except `_next/static`, `_next/image`, favicon, `/logos/`,
`/api/`). Next allows only ONE proxy file. **Extend the existing `proxy()` function; do not
create a file, and do not rewrite the matcher** — it already covers `/account`, and breaking it
breaks country seeding site-wide.

**C2 — `(auth)/login` and `(auth)/register` are 3-line placeholders**, not working pages. This
is not a redirect-back retrofit; both forms are built from scratch here.

**C3 — `fetchWithAuth` CANNOT do its silent refresh from a Server Component.** `session.ts:32`
calls `jar.set(...)`, and the bundled Next 16 doc
(`01-app/03-api-reference/04-functions/cookies.md:80`) states: *"Setting cookies is not supported
during Server Component rendering. To modify cookies, invoke a Server Function from the client
or use a Route Handler."* In an RSC the set throws.

> **This is a latent bug TODAY**, not only a constraint on new work: `lib/checkout.ts:51`
> `getOrder` → `fetchWithAuth`, called from `checkout/confirmation/[number]/page.tsx`, a Server
> Component. It has never bitten because confirmation is visited seconds after checkout, while
> the access token is still valid. ~~Fix it in 15c.~~
>
> **FIXED IN ITEM 4 (2026-07-26), pulled forward from 15c.** The fix is a change of fetch
> mechanism, not of presentation, so it belongs with the mechanism and its tests rather than with
> 15c's extraction refactor. Shipping item 4 while a known-broken caller of the very thing item 4
> exists to fix stayed broken would have been process for its own sake.
>
> **And the hazard is worse than "the cookie write throws".** The refresh POST *succeeds* first,
> and SimpleJWT (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION) blacklists the old refresh
> token server-side the instant it is spent. An RSC that refreshes therefore destroys a live
> 14-day session and only *then* fails to persist the replacement. `product/[slug]/page.tsx`
> — which this plan did not even list — was the worse of the two call sites for exactly this
> reason: its `catch` returned a generic delivery label, so the page rendered perfectly while
> the customer's session died. Both call sites are fixed; the product page now uses `apiFetch`
> with a hand-read token, because a **public** page must neither bounce to login nor refresh.

### Gating architecture

Two layers. The proxy is a cheap hint; **the real gate is each page's own data fetch.**

1. **Proxy (presence theatre, ~5 lines).** Inside the existing `proxy()`: if the pathname starts
   with `/account` and there is no `refresh` cookie, redirect to `/login?next=<pathname>`.
   **Gate on `refresh`, never on `access`** — `access` expires after 30 minutes while `refresh`
   lasts 14 days, so gating on `access` would bounce a perfectly logged-in user to /login every
   half hour. Buys: a logged-out visitor or crawler never renders eight dynamic pages, and a
   direct URL hit gets a correct `?next=`. Nothing more; document it as such.
   The proxy must import only cookie-name constants — **never `lib/session.ts`.**

2. **Real gate: the refresh-redirect dance.** Because only a Route Handler may write cookies:
   - `api/auth/refresh-redirect/route.ts` (GET): validate `next`, refresh the token pair,
     **persist BOTH rotated tokens**, 303 to `next`. On refresh failure: clear both cookies and
     redirect to `/login?next=<next>`. A dedicated file, not a new `[action]` case — that
     handler is POST-and-JSON.
   - `requireAuth(currentPath)` in `lib/session.ts`: no access + no refresh → `/login?next=`;
     no access + refresh → `/api/auth/refresh-redirect?next=`; access present → plain
     `apiFetch` **without** the refresh fallback, and 401 → refresh-redirect.

**Three traps inside this:**

- **`redirect()` throws `NEXT_REDIRECT`.** Any `try/catch` on this path MUST rethrow it
  (`unstable_rethrow`). A generic catch silently turns the entire gate into a no-op. This is
  the subtlest line in Plan-15.
- **Layouts do not re-run on soft navigation.** /account/orders → /account/addresses does not
  re-execute `account/layout.tsx`, so a layout-only gate protects nothing after minute 30.
  Hence: every page's own fetch is the gate. The layout fetches `/auth/me/` once per hard load
  for the nav only. **No page adds a separate gate call on top of its data fetch** — zero extra
  round trips except one redirect per genuine expiry.
- **Rotation race.** Two concurrent RSC requests can both hit refresh-redirect; with
  ROTATE + BLACKLIST the loser 401s to `/login?next=`. Heal it by having the login page check
  server-side whether the user is already authenticated and, if so, redirect straight to `next`.
  Build that in from day one — it turns the race into an invisible extra redirect.

**Open-redirect guard:** accept `next` only when it starts with a single `/` and not `//` or
`/\`; otherwise fall back to `/account`. Applied in login, register, and refresh-redirect.

### Other rulings

- **Invoice = BFF streaming proxy.** `fetchWithAuth` parses JSON so it cannot stream; add
  `fetchWithAuthRaw(): Promise<Response>` sharing the same refresh block (factored, not
  duplicated). **No IDOR to design against** — verified `orders/views.py` is `IsAuthenticated`
  and filters `user=request.user`, so a stranger's order 404s. The invariant to state in the
  route: forward the CUSTOMER's token and never any privileged credential; authorization lives
  in exactly one place, the backend queryset. Validate `number` against `^[A-Za-z0-9-]{1,32}$`.
  `Content-Disposition: attachment`, and **`Cache-Control: private, no-store`**. API 404 → 404;
  **403 → also 404** (never confirm the order exists).
- **Reviews: OUT of scope.** Product-scoped reviews already exist; there is no "my reviews"
  endpoint, and the spec's own file list omits the page. Adding a backend endpoint inside a
  storefront plan is cross-boundary scope creep. Mention it at the checkpoint.
- **`/verify-email` IS in scope** (I had missed it). `accounts/views.py:42` mails
  `${FRONTEND_URL}/verify-email?token=...` on registration, and Plan-15 is what makes
  registration real — without the page every new registrant clicks a 404. Route slugs are pinned
  by the backend: exactly `/reset-password` (`uid` + `token`) and `/verify-email`.
- **Account pages stay under `(shop)`**, not a literal `src/app/account`, so they keep the site
  chrome. Deviation from the spec's literal paths; note at checkpoint.
- **Reuse by extraction, not import.** Pull shared presentation out of the confirmation page into
  `components/orders/` and have both consume it. Do NOT let account order-detail import the
  confirmation page or share its *fetch* path — keep each page owning its own fetch.
  **CORRECTION (2026-07-26): the reason given here was wrong. The confirmation page does NOT
  serve guests.** `permission_classes = [AllowAny]` on `OrderDetailView` is the DRF idiom for
  "this view does its own auth in the body", not "guests welcome": `orders/views.py:69-71` returns
  **403 `authentication_required`** to an anonymous caller, and anonymous access works *only* with
  a signed `?token=` tracking link (which yields the redacted serializer, and which the
  confirmation page never passes). Verified live against the running API: garbage bearer → 401,
  no auth → 403. So confirmation is an authed page like any other and uses
  `fetchWithAuthOrBounce`. The tracking-token guest view is 15c's separate `/track` surface.
- **No caching under /account.** `cookies()` makes these routes dynamic automatically; no
  `revalidate`, no `use cache`.

---

## Tasks

**15a — Auth core. HIGHEST RISK; review hardest.**
Every failure mode here is an auth failure mode: cookie-write rules, the rotation race,
NEXT_REDIRECT swallowing, open redirect.
1. `lib/next-param.ts` — `safeNext()` open-redirect guard (+ tests).
2. Extend `src/proxy.ts` with the `/account` refresh-presence check (+ tests).
3. `api/auth/refresh-redirect/route.ts` (+ tests).
4. ~~`requireAuth` / 401-wrapper / `fetchWithAuthRaw` in `lib/session.ts` (+ tests).~~ **DONE
   2026-07-26.** Shipped surface, and the reasoning that is easy to undo by "simplifying":

   - **`lib/api.ts`: `apiFetchRaw()`** returns the Response untouched; `apiFetch` is rebuilt on
     top of it so URL/header assembly exists once.
   - **RSC-safe (read cookies, never write, never touch the refresh endpoint):** `getAccessToken`,
     `requireAuth(currentPath)`, `fetchWithAuthOrBounce(path, currentPath, opts)`.
   - **Route-Handler-only (write cookies):** `fetchWithAuth`, `fetchWithAuthRaw`. Both share one
     private `refreshAndPersist(jar, refresh)`.
   - **`currentPath` is an explicit required parameter.** Next 16 gives an RSC no pathname API
     (`headers()` exposes incoming request headers only — checked the bundled doc). The rejected
     alternative was a proxy-injected header: it fails *silently* when the matcher misses a route
     or the header name drifts, quietly sending users to `DEFAULT_NEXT`. A wrong literal is caught
     in one walkthrough; a silent infrastructure fallback is not.
   - **`fetchWithAuth` was NOT renamed.** Nine Route Handlers use it correctly; churn buys nothing.
   - **Enforcement is a dev-time probe, not a lint rule.** The bug arrived *indirectly* through
     `lib/checkout.ts`, which Route Handlers may legitimately import, so an import rule on pages
     would have missed it. `assertCookiesWritable` attempts `jar.delete()` and converts the
     failure into a named error. **Verified live, not just against the mock:** a scratch RSC
     calling `fetchWithAuth` produced *"fetchWithAuth() was called during Server Component
     render… Use requireAuth() or fetchWithAuthOrBounce()"*. A second, cheap structural test
     (`session-boundary.test.ts`) asserts the writing fetchers are imported only under
     `app/api/` — when first written it failed and named exactly the two known offenders.
   - **Deleted `getDeliveryOptions`** from `lib/checkout.ts`: zero callers: the BFF route
     `api/checkout/delivery-options/route.ts` re-implements it. Deleting it removed a third RSC
     hazard for free.

   **A Next 16 behaviour to know before writing the login page (found by testing, not documented):**
   the renewal bounce does **not** arrive as an HTTP 307. `redirect()` fires after the RSC shell
   has begun streaming, so Next cannot send a `Location` header and instead embeds the redirect in
   the streamed RSC payload for the client router to act on. Verified end to end in a real browser
   on a *hard* navigation with a stale access cookie: the browser landed on
   `/login?next=%2Fcheckout%2Fconfirmation%2FTC-100038`, **both** dead token cookies were cleared
   (so no gate↔handler loop), and `country=NG` survived the chain. Consequences: `curl` and other
   no-JS clients see the fallback UI and a **200**, not a redirect — do not assert on 307 in any
   test or smoke check; and a stale-session user briefly sees the page shell before bouncing.
   **Still unverified (Fable's open question):** the same bounce during a *soft* client-side
   navigation. Nothing links to a gated page yet, so verify it in the 15b walkthrough.
5. Login page — full build, `?next=`, already-authed short-circuit.
6. Register page — full build, `?next=`; the existing BFF register action auto-logs-in.
7. `forgot-password`, `reset-password`, `verify-email` pages.

**15b — Account shell + identity pages.**
`account/layout.tsx` (side nav desktop / tabs mobile), dashboard index, profile + marketing
consent (PATCH `/auth/me/` — read the serializer's consent field name, don't guess), security
page (password change per `PasswordChangeSerializer`; deletion behind typed confirmation → BFF →
`/auth/account/delete/` → clear cookies → redirect home).

**15c — Orders.** Second-riskiest, because of the extraction refactor.
Orders list with status chips, order detail, tracking, invoice BFF proxy + `<a>` link; extract
shared presentation from the confirmation page and re-verify the confirmation flow; fix the
C3 latent bug in `getOrder`.

**15d — Addresses + wishlist.**
Address CRUD with default badges — the existing `api/addresses` BFF has only GET/POST, so extend
it with PATCH/DELETE and the two set-default routes. Wishlist grid with add-to-cart over the
existing wishlist BFF.

---

## Verification

Full click-through of every page as a real user; password-reset email round trip on preview.

**Verify on the deployed API before the reset round trip — do not assume:**
1. **`FRONTEND_URL`** defaults to `http://localhost:3000` (`config/settings/base.py:191`). If the
   VPS env doesn't set the real storefront origin, every reset email carries a localhost link.
2. **`EMAIL_BACKEND`** defaults to the console backend; Resend engages only if `EMAIL_BACKEND` +
   `RESEND_API_KEY` are set. "Email round trip on preview" is testing infra config, not code.
   Confirm the Resend sender domain is verified or delivery fails silently / lands in spam.
3. Reset tokens are single-use and time-limited (`PASSWORD_RESET_TIMEOUT`, default 3 days) —
   click a used link and confirm the UI shows the 400 message rather than crashing.
4. Forgot-password must show the **same generic success unconditionally** — `PasswordResetView`
   always returns 200 specifically to prevent email enumeration; the UI must not leak it back.
5. A completed reset also auto-verifies email and claims legacy orders — expect that side effect.

**CHECKPOINT:** screen walkthrough for Hammed.

## Next 16 gotchas (bundled docs are authoritative — `storefront/AGENTS.md`)

- Cookie writes are Route-Handler/Server-Function only (C3).
- `redirect()` inside `try/catch` needs `unstable_rethrow`.
- Layouts don't re-run on soft navigation.
- `searchParams` is a Promise — `await` it, as the codebase already does for `params`.
- After logout, call `router.refresh()` before navigating: the client router cache can otherwise
  serve stale /account HTML on Back.
- Proxy is Node-runtime only and must stay dependency-free.
