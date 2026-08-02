# Plan-25 — QA and hardening

Follows Plan-18b, which was pulled forward specifically so this stage's IDOR/PII pass would
have the customer surface to test.

> This is **not** a generic hardening checklist. Every item below is either something this
> project explicitly deferred to Plan-25 in code or in a plan, or something measured on
> 2026-08-02. Nothing here is "we should probably also…".

---

## Grounding (measured 2026-08-02)

### What is already done, and is not this stage's work

Worth stating because a hardening plan that re-litigates settled work wastes the pass:

- **Prod security headers are set**: `SECURE_SSL_REDIRECT`, HSTS 1 year with preload and
  subdomains, secure session/CSRF cookies, `nosniff`, `X_FRAME_OPTIONS=DENY`,
  `strict-origin-when-cross-origin`.
- **Throttling is thorough** — 19 declared scopes, including the login design that caps by
  IP *and* by email in two windows so password spraying is metered.
- **The admin surface is guarded four ways** — 49 endpoints, each declared in
  `ADMIN_SURFACE`, the role matrix, the audit write/read-only sets and (where PII-bearing)
  `READ_AUDITED_VIEWS`. Adding an endpoint without declaring it fails the suite.
- **CMS HTML is sanitised on write** (nh3), which Plan-19 deliberately pulled out of this
  stage.
- **2,047 backend tests, 743 admin, 745 storefront.**

### THE FINDING: both apps run a Next.js with nine high-severity CVEs

`next@16.2.10` in **both** `storefront/` and `admin/`. Latest patch is **16.2.12**.
`npm audit` reports 6 high advisories on the storefront and 4 on the admin, all with fixes
available. The Next ones that matter for a live store:

| Advisory | Why it matters here |
|---|---|
| **Unauthenticated disclosure of internal Server Function endpoints** | The admin is entirely Server Components + Server Actions behind a BFF |
| **Middleware / proxy bypass in App Router** | The admin's whole auth model is a BFF proxy at `app/api/[...path]` |
| **Cache confusion of response bodies for requests with bodies** | A storefront serving per-country cached content |
| **SSRF in rewrites via attacker-controlled destination hostname** | |
| **SSRF in Server Actions on custom servers** | |
| **DoS in App Router using Server Actions**; unbounded Edge payload; image-optimisation SVG DoS | |

Plus **`sharp`** inheriting four libvips CVEs (CVE-2026-33327/33328/35590/35591) — that one
processes uploaded and migrated product imagery.

This is a two-patch bump. It is the highest value-per-risk action available in this stage
and it goes first.

### There is no Content-Security-Policy anywhere

Not in Django, not in the storefront, not in the admin. Searched all three. The CMS
sanitiser is the current XSS control and it is a good one, but it is a single layer, it is
applied on write, and Plan-24 just loaded 50 WordPress/Elementor bodies through it. CSP is
the second layer that turns "the sanitiser had a gap" into "the sanitiser had a gap and
nothing executed".

### Three controls this project already knows are weaker than they look

Each is written down in the code, honestly, by whoever built it:

1. **A 404 is served as HTTP 200.** `app/loading.tsx` is a root Suspense boundary, so Next
   commits the status before the body streams; `notFound()` renders the not-found UI and
   injects `noindex`, but the status line says 200. App-wide, not Plan-19's or Plan-24's.
   Cited in `storefront/src/app/(shop)/page/[slug]/page.tsx:27` as belonging here.
2. **`AuditLog`'s append-only REVOKE is inert.** `core/migrations/0006` says so in as many
   words: Django connects as a Postgres **superuser** (the `postgres:16-alpine` image
   creates `POSTGRES_USER` that way, and `docker-compose.prod.yml` uses it unchanged), and
   a superuser bypasses privilege checks. The table is protected by its **trigger** alone.
   The migration deliberately records this rather than letting the grant read as protection.
3. **The VPS has months of unapplied security updates** (Plan-02 §311, which named this
   stage). Live production, one prior malware incident.

### Known-inert or deferred, confirmed still open

- S3 **object** sweep for pruned orphan images — deliberately deferred to 25/26 *after*
  bucket versioning is enabled, because deleting unversioned objects is unrecoverable.
- Marketing/analytics tags (GTM, Meta, TikTok) — `audit.md:295` assigns them here.

---

## Design rulings

### 1. Patch the CVEs first, and verify by running the apps, not by reading the changelog

A dependency bump that typechecks and passes unit tests can still break a running app —
this project's own `CLAUDE.md` says to run the thing. Both suites plus a real browser walk
of one storefront page and one admin page.

### 2. CSP is `report-only` first, on the storefront, before it is enforced anywhere

A CSP written blind against a Next app with inline styles, Turbopack's runtime and a CMS
that emits arbitrary published HTML **will** block something real. Shipping it enforcing
means finding that out from a customer. Report-only, read the reports, then enforce — and
the admin gets the stricter policy first because its content is entirely ours.

### 3. The IDOR pass is written as tests, not as a document

A hardening pass whose output is a PDF is a hardening pass nobody can re-run. Every finding
becomes a test in the suite that fails against the unfixed code. The four existing guard
declarations already make "an undeclared endpoint" impossible; this adds the per-object
question they do not ask — *can role X reach object Y that belongs to customer Z*.

### 4. The Postgres superuser is fixed in infra, not worked around in code

Adding application-level checks to compensate would be a third layer describing a control
that still is not there. Either the app connects as a least-privilege role or the migration's
comment stays true. This stage does the former and deletes the caveat.

---

## Tasks

1. **Dependency CVEs** — `next` 16.2.10 → 16.2.12 and `sharp` in both apps; re-audit to
   zero high; run both suites and drive both apps in a browser.
2. **CSP** — report-only on the storefront, enforced on the admin, with the CMS body case
   explicitly considered.
3. **IDOR / per-object authorisation pass** across the 49 admin endpoints and the customer
   account surface, output as tests.
4. **404 truthfulness** — a pre-stream existence check, or a documented decision that
   `noindex` is the accepted answer and the comment is updated to say so permanently.
5. **Least-privilege Postgres role**, retiring the inert REVOKE caveat.
6. **VPS patching** — with a snapshot first, given one prior malware incident.
7. **S3 versioning, then the orphan-object sweep** (in that order, irreversibly).
8. **Analytics tags** — deferred here from the audit; scope to be confirmed, since consent
   handling is a legal question, not a technical one.

Tasks 1–3 are this stage's substance. 6 and 7 touch live infrastructure and are gated on
Hammed the same way the migration credential is.


---

## Progress (2026-08-02)

### Task 1 — dependency CVEs ✅

`next` 16.2.10 → **16.2.12** in both apps; `sharp` and `postcss` pinned via npm
`overrides` because both are bundled inside next. **Both apps audit clean** (was 6 high /
4 high).

> ⚠️ **Never run `npm audit fix --force` in these repos.** npm's proposed remediation is
> `next@9.3.3` — a six-year downgrade — because it cannot see that the advisories are in
> next's own bundled dependencies.

**Verifying by running the apps found a far worse bug than the CVEs.** See the commit, and
the note added to the catch-all route: the root `src/app/loading.tsx` made Next commit the
HTTP status before the body streamed, so **Plan-24's entire redirect layer answered 200
with no `Location` header** and every 404 in the app answered 200. Browsers followed the
streamed client-side navigation, so it looked perfect to a human. Removing that one file
fixed both, and cost nothing — the three routes heavy enough to want a skeleton already
have their own. A structural test now fails if it comes back.

### Task 2 — CSP ✅

Storefront **report-only**, admin **enforced**. The asymmetry is the ruling: the storefront
renders CMS bodies authored as Elementor markup and loads three payment SDKs that inject
scripts and iframes, so it reports first; the admin has four dependencies, no third-party
content, and is the higher-value target.

Origins were found by reading the code rather than copying a starter policy —
`@paystack/inline-js` and `@paypal/react-paypal-js` both inject scripts and render frames,
while Flutterwave and Stripe hand off by top-level redirect and need no allowance at all.
Verified live: both headers ship, and the admin renders under the enforced policy.

`unsafe-eval` is dev-only and asserted absent from production in both apps.

**Still open on CSP:** somebody has to read real reports before `REPORT_ONLY` flips on the
storefront, and per-request nonces would remove `'unsafe-inline'` from `script-src` — the
natural next step once the policy has proven itself.

### Task 3 — IDOR / per-object authorisation ✅

**The pass found no holes.** All 14 object-addressed routes outside `/api/v1/admin/` are
either scoped to the requesting user or public by design, checked one at a time. The two
that were not already covered by tests — `orders/<number>/pay/` and
`payments/<reference>/verify/` — both filter on the user, verified in
`retry_payment` and `PaymentStatusView`.

Since "we looked and it was fine" protects nothing, the deliverable is
`apps/core/tests/test_object_ownership.py`: a guard in the same shape as `ADMIN_SURFACE`
that **fails when a new route takes an object id without declaring how it is scoped**,
plus cross-account tests for the address action routes and the payment-verify endpoint.

### Noted, not fixed

- **`src/lib/__tests__/session-boundary.test.ts` is flaky on `/mnt/c`** — it walks the
  source tree under a 5-second timeout and times out when a dev server is competing for
  I/O. It passes alone in ~2.4s. It will fail intermittently in CI on a slow filesystem;
  the fix is a longer timeout on that test, not a change to the walk.
- **`/product/[slug]` and `/category/[slug]` still soft-404**, because they keep their own
  `loading.tsx`. A discontinued product therefore answers 200. That is a real trade-off —
  a skeleton on the heaviest pages versus a truthful status — and it is Hammed's call, not
  one to make silently while fixing something else.

### Remaining

4 (404 truthfulness — now only the two routes above), 5 (least-privilege Postgres role),
6 (VPS patching), 7 (S3 versioning then the orphan sweep), 8 (analytics tags). 6 and 7
touch live infrastructure and are gated the same way the migration credential is.
