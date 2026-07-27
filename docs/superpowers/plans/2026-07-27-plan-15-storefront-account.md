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
   **Gate on `refresh`, never on `access`** — the access cookie expires in **14 minutes**
   (under its 15-minute token; it was wrongly 30 minutes until item 5 fixed it) while the
   refresh **cookie** lasts 14 days, so gating on `access` would bounce a perfectly logged-in
   user to /login every quarter hour. Note the distinction, because it matters in the other
   direction too: the refresh **token** is valid 30 days (`base.py:176`) and the cookie is
   deliberately shorter at 14 (`lib/auth.ts:18`, pinned by `auth.test.ts`). Cookies must
   always expire *before* the tokens they carry — do not "tidy" the cookie up to 30 days, or
   you recreate the access-cookie bug in reverse. Buys: a logged-out visitor or crawler never renders eight dynamic pages, and a
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
5. ~~Login page — full build, `?next=`, already-authed short-circuit.~~ **DONE 2026-07-26.**

   **Built as a Server Function, not a client fetch to the auth BFF.** The deciding reason
   is navigation, not progressive enhancement: `redirect()` in a Server Action serves a 303
   and streams the destination's payload in the *same* response (`redirect.md:11`,
   `server-actions.md:48`), so the landing page renders *after* the cookies are staged. The
   client-fetch alternative has no correct sequence — `router.refresh()` returns void with
   no completion signal, so a `push` cannot be ordered after it. Two things came free:
   Next's `Origin`/`Host` CSRF check on every action (`server-actions.md:82`), which the
   JSON BFF route does **not** have; and a form that works with JS off.
   `api/auth/[action]` keeps its contract unchanged — checkout's `SignInStep` still uses it.

   **`lib/auth-session.ts` is new and shared** (`setTokens`/`clearTokens`/`mergeGuestCart`/
   `establishSession`). A Server Action cannot reuse the BFF route by fetching it —
   `Set-Cookie` on a fetch response never reaches the outer response, so the user would
   authenticate and stay logged out. Sharing the module is what keeps the guest-cart merge
   to one implementation. Its country-cookie forwarding is now pinned by a test; it was
   unpinned, which is exactly how an extraction loses it.

   **`decideLoginEntry` is a SEPARATE function from `decideAuth`, deliberately.** Fable's
   ruling suggested reusing `decideAuth` here; that would have shipped an infinite redirect,
   and its own table contradicted it. `decideAuth` returns `authenticated` whenever an
   access token is present, but `proxy.ts:40` gates `/account*` on the **refresh** cookie —
   so honouring an access-only cookie sends the visitor to `/account`, the proxy sends them
   back to `/login`, and round it goes, with no API call anywhere to break it. The rule is
   **both cookies, or a form**; refresh-only renews via the bounce.

   **Two defects fixed here because item 5 depends on them:**
   - `ACCESS_MAX_AGE` was **30 min against a 15-min `ACCESS_TOKEN_LIFETIME`** — for half of
     every session the browser held a token Django rejects, which would have made the
     login short-circuit's happy path a guaranteed 401. Now 14 min, with a test asserting
     the cookie always expires before the token it carries.
   - `refresh-redirect`'s `catch` was bare, so a 502/timeout was treated as "token dead" and
     destroyed a valid 14-day session for every user whose access token happened to be
     stale during the blip. Now only SimpleJWT's own 400/401 clears cookies. Termination is
     unaffected: a transient error retries, a real verdict clears.

   **Verified live, not only in tests:** a genuine no-JS submit (parse the server-rendered
   HTML, POST React's `$ACTION_*` fields as multipart, zero client JS) returned **303 +
   `Set-Cookie: access, refresh`** and honoured `next` — so progressive enhancement is real,
   which Fable had flagged as unverified. `https://evil.example/pwn` came back as `/account`.
   With JS, submit soft-navigated to `/account/orders`; `document.cookie` showed no tokens
   (httpOnly intact). All three entry states confirmed by cookie: access-only renders the
   form, refresh-only emits the renewal bounce, neither renders the form.

   **Also:** `(auth)` had no layout, so auth pages rendered with no header/footer and no way
   back to the store. Added a minimal `(auth)/layout.tsx` — logo linked home, nothing else.
   No "Forgot password?" link until item 7 builds that page; a visible 404 is worse.

   **Deliberately NOT done: forwarding `X-Forwarded-For` from the auth BFF or the action.**
   It looks like a rate-limit fix and is not one. See the security section below.
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

## LAUNCH-BLOCKING SECURITY GAP — its own slice, do before 15b (found 2026-07-26)

Not caused by item 5 and not worsened by it; the exposure is live right now through
checkout's `SignInStep` and through plain `curl`. It is separated out because the fix is
Django throttle classes plus a Cloudflare rule, and bundling it into a storefront page
would make that page's review about DRF internals.

**`/auth/token/` has no effective rate limit at all.** Verified against the local API:

| probe (80–70 attempts, junk credentials) | result |
| --- | --- |
| no `X-Forwarded-For` | first `429` at attempt **61** |
| fixed spoofed `X-Forwarded-For` | first `429` at attempt **61** |
| **rotating spoofed `X-Forwarded-For` prefix** | **0 × 429 in 80 — every guess allowed** |

Why: `NUM_PROXIES` is unset, so DRF's `BaseThrottle.get_ident`
(`rest_framework/throttling.py:29-40`) falls through to `''.join(xff.split())` — it keys on
the **entire XFF chain as one string**. Rotate a junk prefix and every request gets a fresh
bucket. `/auth/token/` is stock `TokenObtainPairView` (`accounts/urls.py:17`) with only the
global `anon: 60/min`, and no scoped throttle.

Three consequences, all confirmed:
1. **Brute force / credential stuffing is unmetered** for anyone who posts straight to
   `api.tokecosmetics.com` instead of going through the storefront.
2. **Customers share one bucket.** Because the BFF proxies every login, Django sees the
   Vercel egress IP, so legitimate shoppers contend for a single 60/min allowance — a
   capacity risk independent of security.
3. **The `password_reset: 5/min` throttle added in the previous slice is globalised**: five
   forgotten passwords a minute for the whole store, *and* still bypassable by skipping the
   storefront. Worse than it looked when it was added.

**Forwarding XFF from the BFF is NOT the fix and must not be attempted.** `NUM_PROXIES` is
one global number, but the two paths need different ones — direct-to-API puts the real
client at `addrs[-2]`, via-BFF at `addrs[-3]`. At 2, BFF-forwarded XFF is ignored; at 3, a
direct attacker forges any client IP, which is worse than today. Corollary worth knowing:
the existing forwarding in `api/newsletter/route.ts:13-19` and `api/search/suggest/route.ts:15-20`
only works by accident of whole-chain keying and breaks the moment anyone sets `NUM_PROXIES`.
Its "prod must trust X-Forwarded-For" comment describes a fix that does not exist.

**`RegisterView` is in scope too** (`accounts/views.py:32-47`) — verified: no `throttle_classes`,
so global anon only and the same XFF bypass. Worse than login, because `perform_create` fires
`send_email_task.delay` to the **submitted** address: rotating XFF gives an attacker unlimited
registrations, each mailing an arbitrary stranger from our domain. That is a spam cannon whose
cost is `mg.tokecosmetics.com` getting blacklisted — which would silently break every order
confirmation the store sends.

**When this must be done — named triggers, not a vibe.** As of 2026-07-26 the production DB has
**0 users, 0 orders** (69 products), so there is nothing to brute-force into *yet*. That is a
snapshot, not an invariant: registration is already publicly reachable in production through
checkout's `SignInStep`, so the count can change without any deploy. (A) must be complete
before the FIRST of these:
1. **Plan-22's legacy customer import** — the moment a known list of real addresses exists in
   that DB, credential stuffing goes from theoretical to routine;
2. **the first staff/superuser account** (Plan-17 admin work);
3. **swapping `sk_test` for live Paystack keys** — real money behind the accounts.

**The fix, three pieces:**
1. **Scoped throttle keyed on the submitted email, not the IP** — `SimpleRateThrottle`
   subclass, `scope="login"`, `get_cache_key` → `throttle_login_<lower(email)>`, ~5/min plus
   a slow window (20/hour). Immune to IP spoofing *and* to the BFF hop, because the key comes
   from the request body. Same treatment for `password_reset`, where keying on the target
   email is also the only key that actually protects the victim's inbox, and for `register`.
2. **Custom `get_ident` preferring `CF-Connecting-IP`** for the residual IP-keyed throttles —
   trustworthy *here specifically* because `infra/proxy/zz-api.conf:61-95` locks the origin to
   Cloudflare. Verify empirically; `mod_remoteip` is not loaded, so Django must read it.
3. **A Cloudflare rate-limiting rule on `/api/v1/auth/*`** — blocks the direct path before it
   reaches Django. **Needs Hammed** (dashboard access), and while there, confirm whether any
   rule exists today: `docs/runbooks/vps-stack.md:169-171` leans on Cloudflare rate limiting
   as part of the security story and it is unverified.

**Bundle with it:** the auth BFF route has **no `Origin` check**, so a cross-site form POST to
`/api/auth/login` with attacker credentials is session fixation — the victim is logged into
the attacker's account and `mergeGuestCart` then folds the victim's bag into it. `SameSite=Lax`
does not help: the attack needs no existing cookie, and it is the *response's* `Set-Cookie`
that does the damage. The new `/login` Server Action is already protected (Next checks
`Origin` against `Host`); this is only the older JSON route, still used by checkout.

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
