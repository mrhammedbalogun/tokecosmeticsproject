# Plan-16 — Admin foundation (staff auth, RBAC, shell, audit)

Master spec: `master-tokerebuild.md` § Plan-16-admin-foundation. Branch
`plan-16-admin-foundation` off `main` (`1f97396`). Execution: subagent-driven, one
implementer per task, two-stage review per task, final whole-branch review.

## Grounding facts, verified 2026-07-28 (do not re-derive)

- `admin/` is a BARE Next 16.2.10 scaffold from Plan-01: `package.json` +
  configs only, no `src/`, deps are next/react/tailwind only. Everything is
  greenfield there. Same Next version and conventions as `storefront/` — the
  storefront is the style/architecture reference throughout.
- 18 `IsAdminUser` sites across 5 backend files (`catalog/admin_views.py`,
  `inventory/admin_views.py`, `orders/views.py`, `payments/views.py`,
  `shipping/views.py`) — the Plan-05–11 admin endpoints the spec says to tighten.
- Auth stack: SimpleJWT (ROTATE + BLACKLIST, 15-min access / 30-day refresh
  tokens; cookies 14 min / 14 days in the storefront BFF), `LoginView` with
  email+IP throttles and optional Turnstile. `User` is email-keyed
  (`apps/accounts`), has `is_staff` from AbstractUser. Django permission
  machinery (Group, Permission) is present and unused so far.
- The storefront's session architecture (httpOnly cookie pair via BFF, RSC-safe
  vs cookie-writing fetchers, renewal bounce, `decideAuth`) is proven — the
  admin app MIRRORS it rather than inventing a second scheme. Every lesson in
  `docs/superpowers/plans/2026-07-27-plan-15-storefront-account.md` applies
  (never `await body.cancel()`; tokenless requests decide the bounce up front;
  layouts never gate; `params`/`searchParams` are Promises).
- Email: `apps/core` mail infra + Resend in prod (`send_email_task`), templates
  under `apps/notifications/templates/email/`.
- Deploy target: admin will be a THIRD deployable (Vercel project) — but
  deployment is NOT this plan (Hammed's checkpoint uses a preview URL).

## Design rulings (Fable, 2026-07-28)

1. **Roles are Django Groups** seeded by migration (`Owner`, `Manager`,
   `Support`, `Content`) — no custom Role model. The spec's `Role(name)` is
   satisfied by Group; a parallel model would be a second source of truth.
2. **Scopes, not raw permissions, at the API boundary.** A scope string
   (`"orders.manage"`, `"orders.view"`, `"products.manage"`, `"customers.view"`,
   `"cms.manage"`, `"reports.view"`, `"staff.manage"`, `"settings.manage"`) maps
   to the groups that hold it in ONE table in `apps/accounts/rbac.py`.
   `HasAdminScope("x")` = `is_staff` AND (superuser or group grants x). Views
   never name groups.
3. **Staff sessions reuse SimpleJWT** with a dedicated admin BFF (same cookie
   dance as the storefront, separate app = separate cookie jar on a separate
   origin). Admin login REQUIRES `is_staff` at a dedicated `/auth/admin-token/`
   endpoint (staff check inside the serializer, same throttles as LoginView) —
   the storefront token endpoint stays customer-only-shaped.
4. **AuditLog writes happen in a DRF mixin** (`AdminAuditMixin`) applied to the
   retrofitted views; mutations only (POST/PUT/PATCH/DELETE), storing request
   diff-ish `changes` JSON (validated_data keys, never secrets), actor, model
   label, object id, `client_ip()` (the existing throttling helper), timestamp.
   Reads are not audited (volume, no value).
5. **Idle logout is cookie-lifetime driven** (admin refresh cookie 12h, not
   14d; access 14 min as storefront) + a visible-activity extender client-side.
   No server session table.

## Tasks (sequential; two-stage review each)

1. **RBAC core (backend).** `apps/accounts/rbac.py`: scope table + seed
   migration creating the four Groups; `HasAdminScope` permission class;
   `admin-token/` staff login endpoint (staff-check serializer on LoginView's
   base) + `admin-me/` returning name/email/groups/scopes. Tests: scope map
   per role, non-staff rejected at admin-token even with valid credentials,
   throttles still apply.

   **AMENDED 2026-07-28 (see Amendment 1 below): `admin-token/` IS
   Turnstile-gated, and gets its own stricter throttle scopes
   (`admin_login_ip` 5/min, `admin_login_email` 10/hour) rather than reusing
   LoginView's customer-sized rates.** Admin login failures must reach the
   existing `apps.security` logger at ERROR so Sentry raises them as events.
2. **Retrofit the 18 `IsAdminUser` sites** to `HasAdminScope` with the right
   scope per endpoint (orders endpoints → orders.manage/view split per spec:
   Support gets read+transition; products/inventory → products.manage;
   payments/shipping admin ops → orders.manage). Guard test that walks the
   URLconf and fails on any admin view still using bare `IsAdminUser`. Role
   matrix test: each seeded role against each endpoint class.
3. **StaffInvite (backend).** Model (email, role/group, token hash, expiry,
   invited_by, accepted_at); Owner-scoped create endpoint (sends email via
   `send_email_task`, link `${ADMIN_URL}/accept-invite?token=`); public accept
   endpoint (token + password → creates is_staff user in group, single-use,
   expiring); tests incl. token misuse. `ADMIN_URL` env (default
   http://localhost:3001).
4. **AuditLog (backend).** Model in `apps/core` + `AdminAuditMixin` wired into
   every retrofitted admin view + list endpoint (settings.manage scope,
   filters: actor/model/date). Tests: a product edit writes a row; secrets
   never land in `changes`.
5. **Admin app foundation.** `admin/src`: Tailwind setup copied from
   storefront's tokens (visually distinct accent), `lib/` session architecture
   ported from storefront (`api.ts`, `auth.ts` cookie names `admin_access`/
   `admin_refresh`, `session.ts` with drainBody + tokenless-upfront-decide
   lessons baked in, proxy gate on refresh cookie for everything but /login),
   login page (Server Function like storefront's), shell: sidebar nav
   (Dashboard, Orders, Products, Inventory, Customers, Reviews, Coupons,
   Content, Reports, Settings, Staff — items render only when `admin-me`
   scopes allow), topbar with env indicator (red STAGING badge when
   `NEXT_PUBLIC_API_URL` isn't the prod API), sign-out. Port `.claude/launch.json`
   entry (port 3001). Tests mirroring storefront's session/auth-guard suites.
6. **Global search.** Backend `admin/search/?q=` (staff, any scope): orders by
   number/email, products by name/SKU, customers by toke_id/email/name, capped
   ≤10 per type; topbar search box with grouped results (links may 404 until
   Plans 17/18 build the target pages — link to placeholder routes). Tests.
7. **Settings surface: audit viewer + staff page.** `/settings/audit` table
   (filters, pagination) and `/staff` page (list staff+roles, invite form —
   Owner-scoped). These are the first two real admin pages and prove the shell.
8. **Verification (controller).** Both suites, builds; live: seed roles, create
   a staff user per role in dev, walk the role matrix in the browser (nav
   hiding + 403s), invite flow end-to-end (email via console backend), audit
   rows from a product edit via API, idle/renewal behaviour. CHECKPOINT
   (Hammed): logs into a preview URL with an Owner account — deferred until a
   preview deploy exists.

## Global constraints

- Backend: same test discipline as always (TDD in every task, pytest, no
  migrations edited after review). Storefront untouched. `admin/` may take new
  deps only where storefront already uses the equivalent (@tanstack/react-query,
  vitest, testing-library); anything else needs a controller ruling.
- Admin BFF forwards NO X-Forwarded-For; staff endpoints keep LoginView-grade
  throttling. Secrets never in `changes` JSON, tokens never logged.
- Commit style `feat(admin)`/`feat(rbac)` etc. + Fable co-author trailer.

## AMENDMENTS 2026-07-28 (Fable rulings, after the Turnstile/Sentry prod cutover)

Context: Turnstile went live in production on 2026-07-28 (customer login, register,
password-reset), and Sentry is now live with `SENTRY_ENVIRONMENT=production`. That
changes what this plan must do.

### Amendment 1 — `/auth/admin-token/` IS Turnstile-gated, plus mandatory TOTP

The original "Turnstile-exempt — staff URLs are not public forms" rationale is
**rejected**: the endpoint is publicly reachable and one grep of the deployed bundle
away from discovery. Obscurity is not a control. Exempting it would leave the
*higher*-value login with only the protection customer login had before today.

But be clear-eyed about sizing: Turnstile stops dumb bots; a targeted attacker buys
solver tokens for ~$1/1k, and the admin is exactly the target worth paying for.
**The catastrophic scenario is: admin compromise → attacker edits the payout bank
account → every bank-transfer order pays the attacker.** Turnstile does not prevent
that. So:

1. `require_turnstile(request)` on `admin-token/`.
2. **Mandatory TOTP for all staff accounts, IN THIS PLAN — not deferred.** This is
   the control actually sized to the threat: it makes credential guessing worthless
   regardless of solver farms. With a staff population of ~1 it is trivial to
   operate. Add as a new Task 3b (see below).
3. Dedicated strict throttle scopes for admin-token. Legitimate staff login volume
   is near zero and staff lockout is recoverable via root server access, so brutal
   limits cost nothing.
4. Admin login failures → `apps.security` at ERROR so Sentry alerts on them.

**Break-glass during a Cloudflare/siteverify outage** (this is the operational
answer to "don't lock staff out"): during such an outage customer login, register
and checkout sign-in are already down — the revenue path is dark regardless. Recovery
is the rehearsed one-liner, ~60s, root required:
```
ssh tokecosmetics 'sed -i "/^TURNSTILE_SECRET=/d" /opt/tokecosmetics/.env.prod && cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml up -d'
```
Put that in the Plan-16 runbook. Optional refinement (not required): give the admin
gate its own `TURNSTILE_ADMIN_SECRET` so staff break-glass does not drop the customer
gate.

**TRAP that will otherwise burn Task 1 at rollout: Turnstile widgets are
domain-scoped.** The admin app is a NEW hostname, and the existing widget's allowlist
is `next.tokecosmetics.com` — the widget will error client-side before a token is ever
minted. Decide BEFORE building Task 1 whether to add the admin hostname to the existing
widget or mint a separate admin widget (the latter pairs naturally with
`TURNSTILE_ADMIN_SECRET`). This determines whether admin gets its own site key/secret.

### Amendment 2 — new Task 3b: staff TOTP

Model + enrolment flow (QR provisioning URI), verification step at admin login after
password+Turnstile, recovery codes (hashed, single-use), and an enforcement rule that
a staff account without TOTP enrolled can only reach the enrolment screen. Library:
`pyotp` or `django-otp` — controller ruling required before adding the dep, per the
global constraints. Tests: enrolment, replay rejection of a used code, clock skew
window, recovery-code single-use, non-enrolled staff blocked from all other routes.

### Amendment 3 — the preview deploy comes INTO Plan-16 (Task 8 rewritten)

The original Task 8 deferred Hammed's checkpoint "until a preview deploy exists",
which means the plan as written **cannot be signed off at completion**. There is direct
precedent in this project for what that produces: Plan-09's deferred sandbox checkpoint
became "DEFERRED, not met, all gateways deactivated" and took Plan-09b plus Plan-02 to
unwind. A plan whose sign-off gate cannot fire is a plan with a hope, not a checkpoint.

Create the admin Vercel project and ship a preview deploy inside this plan (~1h, full
CLI access exists). It also front-loads the failures that only appear deployed: env
wiring, CORS, cookie domains, and the Turnstile domain scoping above. Checkpoint
becomes: **Hammed signs off by logging into the preview deploy with an Owner account.**

### Amendment 4 — admin origin hardening, minimally, in scope

The load-bearing boundary is the API's RBAC plus admin auth; the admin origin is a
shell that should hold nothing secret. Cheap and in scope:
- `noindex` headers site-wide; no sitemap; never reference the admin hostname from
  the storefront.
- Vercel Deployment Protection on **previews** at minimum (prevents the classic
  preview-URL leak of an unreleased admin); production too if the plan tier allows.
- Auth wall served first — no route renders data pre-auth; all data via the RBAC'd API.
- No secrets in the admin bundle beyond `NEXT_PUBLIC_*` site key.

Explicitly OUT of scope: IP-allowlisting the origin, mTLS, hiding the hostname. That
is obscurity again; TOTP + RBAC is the real fence.

### Amendment 5 — fix the fictional-control comment

`backend/apps/accounts/throttling.py` (`_IPKeyedThrottle` docstring, ~lines 130-132)
claims "the Cloudflare edge rule on the storefront's own `/api/auth/*` is the control
that sees real client addresses". **That control cannot exist**: verified 2026-07-28,
`next.tokecosmetics.com` is a bare CNAME to `vercel-dns-017.com` and is NOT
Cloudflare-proxied, so no CF rule there can ever fire. Correct the comment when this
module is next touched. See memory `project_tokecosmetics_real_client_ip_gap`.

### Amendment 6 — admin audience claim (found DURING Task 1, confirmed empirically)

**The hole:** SimpleJWT tokens minted at `/auth/token/` and `/auth/admin-token/` were
indistinguishable, and `AdminMeView` gated only on `IsAdminUser`. A staff member's
*customer* login token therefore opened the admin. Everything Amendment 1 added — the
5/min gate, the separate admin widget, ERROR-level Sentry alerting — was decoration
while the cheaper door existed, and TOTP would have inherited the same bypass.

**Ruled design (Fable):**
- **Mint** `aud: "toke-admin"` on the **refresh** token in the admin serializer's
  `get_token()`. `RefreshToken.access_token` copies all claims except `no_copy_claims`,
  so refreshed access tokens inherit it and the shared `/auth/token/refresh/` endpoint
  needs no change — while a customer refresh token can never grow the claim.
- **Enforce primarily in an AUTHENTICATION class**, `AdminJWTAuthentication`, which
  raises `AuthenticationFailed` when the claim is absent. Admin views set
  `authentication_classes = [AdminJWTAuthentication]` and must NOT also list stock
  `JWTAuthentication`. Rationale: forget a *permission* class and a customer token walks
  in; forget it with a dedicated *authentication* class and the request is simply
  unauthenticated — it fails closed at 401.
- **Secondary:** keep the `is_staff` DB check in the permission layer. Claims outlive
  staff revocation; the fresh DB read is what makes revocation immediate.
- **The actual guarantee is the guard test**, which walks the URLconf and asserts
  `authentication_classes == [AdminJWTAuthentication]` **exactly** for every admin view.
  Equality, not membership — a list that *also* contains stock `JWTAuthentication` is
  the bypass reborn and a "contains" assertion would pass it.

**Residual until Task 3b lands, stated plainly:** the claim stops a customer-door token
from *working* on admin endpoints, but an attacker can still brute-force the staff
*password* through the cheap customer door (30/min, customer widget). The audience claim
and TOTP are two halves of one fix. **Task 3b is load-bearing, not polish — sequence it
immediately after Task 2 and before the checkpoint.**

**This changes Task 3b's design, for the better:** the claim means "the full admin
ceremony completed" — password + Turnstile + TOTP — and is minted only after all three
verify. TOTP enforcement then lives in exactly one place, and no endpoint can forget it
because no other code path can produce the claim. A two-step flow (password → TOTP
challenge) must give the intermediate token a DIFFERENT claim (`toke-admin-preauth`),
accepted only by the TOTP-verify endpoint, never by admin endpoints.

### Amendment 7 — order scopes renamed: nothing named `view` may write

Task 1 initially made `orders.view` mean "read + drive status transitions". The split is
right; the name was a landmine — a scope called `view` that mutates state will eventually
be granted by someone who believes the name. Three scopes, renamed while the table has no
dependents: `orders.view` (genuinely read-only), `orders.operate` (status transitions),
`orders.manage` (money: refunds, bank-transfer confirmation, line edits, cancel). Support
gets `view` + `operate`.

### Amendment 8 — `marketing.manage` added; Manager loses `cms.manage`

Task 1 gave Manager `cms.manage` because coupons ship alongside pages in Plan-19 — a
delivery-schedule fact standing in for an authorization decision. Coupons are a money
lever (discount abuse is a classic insider vector); page content is content integrity.
Conflating them means neither can ever be granted without the other. `marketing.manage`
(coupons, promotions) goes to Manager; `cms.manage` (pages, homepage) stays Owner+Content.
Plan-19 binds coupons to `marketing.manage`.

### Amendment 9 — failure-counting on `admin_login_email`, in this plan

`admin_login_email` at 10/hour is request-counting against a staff population of one
whose address is public: ten anonymous junk POSTs lock the owner out of his own store for
an hour, recoverable only by root SSH into Redis. Zero attacker cost, operational
disaster. Fixed here rather than deferred, because the population-of-one property that
makes it dangerous also makes it cheap: increment only on the failed-credential path
(same event as the existing `user_login_failed` ERROR line — wire them together, do not
invent a second detection path), reset on success. Tokenless junk then dies at Turnstile
without touching the bucket, and each countable failure costs a solved token.
`admin_login_ip` stays request-counting — correct for a volume cap. Document the
break-glass `redis-cli DEL` one-liner in the runbook regardless. **Customer-side
failure-counting stays in the pre-Plan-22 gate work, not here.**

### Resolved 2026-07-28 — the Vercel account is **Pro** (confirmed by Hammed)

This settles all three dependent decisions:
1. **Vercel Firewall rate-limit rules ARE available** for the storefront `/api/auth/*`.
   That is the correct — and only — home for a control that sees real client IPs on the
   storefront path (see Amendment 5 / memory `project_tokecosmetics_real_client_ip_gap`).
   Not Plan-16 work, but it is now unblocked and should be scheduled.
2. **Production Deployment Protection is available**, so Amendment 4 applies it to
   production as well as previews, not previews only.
3. **BFF-real-IP does NOT promote** off the hardening backlog — the Vercel rule covers
   the gap it existed to cover. Revisit only if tighter IP rates or `remoteip` on
   siteverify is wanted.
