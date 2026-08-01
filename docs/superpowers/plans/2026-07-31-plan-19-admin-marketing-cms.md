# Plan-19 — marketing and CMS

Master spec: `master-tokerebuild.md` §Plan-19-admin-marketing-cms. Branch off `main`
(`4ad46c6`).

**This stage is far larger than any before it** — the master spec asks for a whole new
backend app (four models, public endpoints, admin CRUD), seven admin surfaces, and a
storefront rewiring, in one line each. Plans 17 and 18 were both sliced after proving too
big; this one is bigger than either and is sliced here before a line is written.

> **REVISED after a Fable review**, which found an orphaned model with higher stakes than
> anything I had ranked first, and named one of my two headline arguments as a
> rationalisation. The original draft and what changed are recorded at the bottom rather
> than quietly overwritten.

---

## Grounding (measured in production 2026-07-31 — do not re-derive)

| | |
|---|---|
| `apps/cms/` | **does not exist**, in any form |
| Coupons | model exists (`checkout/models.py:8`) + redemption ledger · **0 coupons, 0 redemptions** |
| Coupon admin API | **none** — `checkout` has no `admin_urls.py` |
| `BankAccount` | exists (`payments/models.py:118`) · **no admin API, no admin UI, anywhere** |
| `CountryPaymentGateway` | 15 rows, 6 active · **no admin API** |
| Delivery options | 6, all active · **0 `DeliveryOptionRate` rows** (no weight tiers in use) |
| Regions | **811** — 37 `state`, 774 `area` |
| Delivery/region admin API | **none** |
| `SiteSetting` | 0 rows · `Redirect` 0 rows |
| Storefront homepage | 11 hardcoded components, fed by `lib/home-content.ts` (89 lines) |
| Storefront `/page/{slug}` | a 3-line stub |
| Storefront revalidation | **already built** — `app/api/revalidate/route.ts`, secret + tags + tests |
| Backend revalidation caller | **none** |
| WP page migration | **no owner** — `migration_wp/management/commands/` has no `migrate_pages` |

**Five facts shape the slicing, and they are not opinions:**

1. **`BankAccount` is orphaned, and it is the row customers wire money to.** Its own
   docstring says it plainly: *"Bank transfer is the only live payment method at launch, so
   this row IS the payment page for that country."* Plan-09b deferred its CRUD screen on
   the grounds that "Django admin covers launch" — but **`/django-admin/` is denied
   outright at the Apache vhost**, which `config/urls.py:3-9` documents as verified from
   the public internet on 2026-07-28. So the fallback named in the deferral does not exist,
   Plan-18a shipped without the screen, and changing the account number today is a raw SQL
   UPDATE against a live production table. This outranks everything else in the stage.

2. **The live storefront's footer has ELEVEN links into a stub.**
   `components/layout/Footer.tsx:24-45` links `/page/` for about, affiliates, blog,
   community, contact, faqs, privacy, returns, shipping, terms and wholesale. Every one
   renders `app/(shop)/page/[slug]/page.tsx`, whose entire body is the sentence **"CMS
   content arrives in Plan-19."** It is also a soft 200 for *any* slug, so `/page/asdf`
   is indexable.

3. **A role exists whose whole job is this stage.** `cms.manage` is declared in
   `accounts/rbac.py:94` and held by `Owner` and `Content`; **no endpoint anywhere declares
   it**. `admin/src/lib/nav.ts:42` shows that person a "Content" link that 404s.

4. **The homepage seam already exists.** `home-content.ts:1-4` says in its own docstring
   that it "IS the CMS until Plan-19 ships real content models — keep it typed and boring
   so Plan-19 can swap each export for an API call without touching the section
   components." Replacing fixtures with API calls is cheap. **Building the builder UI that
   edits them is not**, and the two must not be conflated.

5. **The homepage is a DYNAMIC route.** `app/(shop)/page.tsx:26` calls `cookies()` for the
   country, so the master spec's "ISR `revalidate: 300`" does not apply to the route — all
   caching lives in the fetch data cache. Any CMS fetch written `cache: "no-store"` (the
   lazy default once cookies are in scope) sends every homepage view to the Django VPS.

---

## Design rulings

### 1. Rich text: NO TipTap in 19a. Revisit it in 19c, where it earns its place

The master spec says "rich text — use TipTap". Declined for the pages editor:

- **The corpus is eleven pages of policy prose**, written once and edited rarely. A block
  editor is a large client dependency and a second content format to store and render.
- **The product editor already made this decision** and this surface should not disagree
  with it: `DetailsPanel.tsx:119` ships a plain HTML textarea labelled "HTML is allowed and
  is rendered as-is".
- **The editor is not the XSS decision** (see ruling 2) — TipTap's output is also stored
  HTML.

**But the counterargument is recorded rather than dismissed:** the `Content` role exists
for non-technical staff, and "write the Returns policy in raw HTML" is a poor answer for
them. So TipTap is not refused outright — it arrives in **19c**, where editorial homepage
blocks want it anyway, and the pages editor swaps onto it then. 19a ships the textarea.

### 2. Sanitise on write, in THIS plan, not in Plan-25

Plan-25 lists CMS bodies among its hardening tasks, flagging "this is stored HTML rendered
by the storefront!". Deferring is wrong here for a specific reason: **Plan-19 invalidates
the assumption the current code is written on.** The storefront renders stored HTML through
`dangerouslySetInnerHTML` at `components/product/PdpAccordions.tsx:23`, and the comment four
lines above states the premise out loud: *"`description` is backend-authored rich HTML
(trusted admin content)."*

That is true today, when the only author is Hammed. This stage adds page bodies authored by
a `Content` role deliberately **not** trusted with orders or products — so the sentence
stops being true in the same release that adds the field. A lower-privileged editor would
gain script execution on the storefront's origin, which is where customers type card
details.

So the sanitiser lands with the model, applied on write, and existing product descriptions
are backfilled through it. **Deviation from the spec, recorded:** it names `bleach`, which
has been unmaintained since 2023; `nh3` (maintained Rust `ammonia` bindings) is used
instead.

### 3. A page is CONTENT, not a route — and an empty page is worse than none

`Page.slug` addresses `/page/{slug}`, and eleven footer links are already written. So:

- Unknown slugs must `notFound()`. **Corrected during 19a after measuring:** that renders
  the not-found UI but still answers **HTTP 200**, because `app/loading.tsx` is a root
  Suspense boundary and Next commits the status before the body streams. It injects
  `<meta name="robots" content="noindex">` instead, which its own guide says prevents
  indexation. A nonexistent PRODUCT does the same, so this is app-wide and predates this
  plan. A truthful status needs a pre-stream existence check and belongs with Plan-25.
- Page SEO fields must emit real metadata, and the pages list must join `app/sitemap.ts`
  (specced at master line 934, currently absent).
- **Deletion is not offered in 19a**; publishing state is a field.
- **An empty "Privacy policy" is legally worse than a missing one.** 19a therefore carries
  an explicit content task — the eleven slugs reconciled against the footer one by one,
  each either authored with Hammed or removed from the footer. Seeding eleven blank drafts
  and calling the stub fixed is not a completion.
- **`/page/blog` is a lie waiting to happen.** The blog is post-launch (`apps/blog`, master
  line 1350). 19a decides explicitly: drop the footer link, or ship a real placeholder.

This slice is also the de facto owner of a decision nobody holds: **Plan-24's redirect map
branches on which legacy WP pages are migrated or dropped** (master line 1267), and no
migration command exists for pages. With eleven pages, an Elementor-soup importer is not
worth writing — re-authoring is cheaper — but the *decision and its list* must be recorded
here for Plan-24 to point at.

### 4. Bank accounts and gateways are money config, not content

Both are CRUD over existing payments models with no storefront work. They are **not**
behind `cms.manage` — they are `orders.manage`, because changing the account number
customers pay into, or turning a payment method on, is a money decision.

The honest argument for pulling them in is **not** "it needs a developer" — Hammed is the
developer, and Paystack activation is a one-time event he will be present for. It is that
`/django-admin/` is denied at the vhost, so **no UI path exists for any of this config**,
and these are one-ViewSet riders on a stage that is already touching admin CRUD.

### 5. Revalidation: the storefront half exists; do not rebuild it

`app/api/revalidate/route.ts` already validates a secret header, takes a tag array and
calls Next 16's two-arg `revalidateTag`, with tests. **What is missing is a Django-side
caller** — there are none.

The honest minimum for the checkpoint's "live within a minute" is **tagged CMS fetches with
`next: { revalidate: 60 }`** and no backend→Vercel coupling at all. If the webhook is built
anyway, it is a Celery task, fire-and-forget with a small retry, per-environment secret and
URL — **never inline in the save path**, or a Vercel wobble degrades admin saves.

---

## Sequencing

**19a — CMS pages, end to end.** The `cms` app with `Page` only; write-time sanitisation
(nh3, product descriptions backfilled); public `GET /cms/pages/{slug}/`; admin CRUD behind
`cms.manage`; storefront route with `notFound()` and real SEO metadata; sitemap wiring; the
eleven-slug reconciliation and the blog decision; the Plan-24 dropped/migrated list
recorded. Tagged, cached fetches per ruling 5.

**19b — Commerce config.** One coherent slice of admin CRUD over models that already exist,
with zero storefront work and zero new apps: **`BankAccount`** (the orphan, and the reason
this slice is not last), `CountryPaymentGateway`, coupons + usage stats, and **plain
`DeliveryOption` field CRUD** — price, `free_over`, `min_days`/`max_days`, `is_active`,
`sort`. Weight tiers are **out of v1**: zero `DeliveryOptionRate` rows exist and a tier
editor for an unpopulated table is speculative.

**19c — Homepage, banners, menus — and the CHECKPOINT.** `Banner`, `HomepageSection`,
`MenuItem`, public endpoints, the builder UI, TipTap, the `home-content.ts` swap and the
revalidation story. **Plan-19's own checkpoint lives here** — the master spec verifies this
stage by "Hammed's team changes the hero banner and sees it live" (line 1071), so the stage
is NOT substantially done after 19b, however much of its value has shipped by then.

**19d — Regions browser and coverage.** The 811-region tree, mixed-granularity coverage
picker and the "test an address" widget. Last because the six options work today, and this
is the largest single UI in the stage.

**Deadline note:** UAT (master line 1310) exercises "CMS edit" and "delivery-option setup",
so 19c and 19d may trail launch prep but cannot slip past Plan-26.

---

## Risks

- **811 regions in one tree control** is the hardest UI here and it is last. If 19d is cut
  for time, NG delivery still works — that is why it sits there.
- **`Content` is a role nobody has held.** Its first real use is 19a, and the role-matrix
  test asserts a nav shape that will change.
- **Eleven pages of policy text is Hammed's writing time, not build time**, and 19a cannot
  close without it. It is the same shape of dependency as Plan-17c Task 0's weights.
- **The webhook is optional and looks mandatory.** The spec asks for it; ruling 5 says a
  60-second TTL meets the stated bar. Building it is a choice, not a requirement.

---

## What the Fable review changed, and what it did not

Recorded rather than folded in, per the standing second-opinion practice.

**It found a model I had missed entirely.** `BankAccount` has no admin path, Plan-09b
deferred it to a Django admin that is denied at the vhost, and it holds the account number
every Nigerian customer wires money to. I had ranked `CountryPaymentGateway` first among
the payments riders; the review was right that this one has strictly higher stakes and
belongs in the same slice.

**It named one of my two headline arguments as a rationalisation, correctly.** I wrote that
the gateway switch mattered because "turning card payments on requires a developer with DB
access". Hammed *is* the developer. The argument that survives is the vhost denial — there
is no UI path for *any* of this config — and ruling 4 now says that instead.

**It corrected the justification for prioritising pages, while agreeing with the priority.**
"The stub is embarrassing" argues for an afternoon of static MDX, not a Django app. What
justifies building `cms.Page` now is the dependency chain: Plan-24's redirect map and the
sitemap both need the model and its slugs.

**It caught work I would have duplicated.** The storefront's revalidation endpoint is
already built and tested; I had it down as unbuilt. Only the Django-side caller is missing.

**It improved the delivery slicing.** I had bundled trivial flat-field edits (which a Lagos
store may want monthly as fuel and logistics costs move) behind the homepage builder,
because I treated "delivery manager" as one thing. Split: field CRUD to 19b, the region
tree to 19d.

**It caught four smaller drops:** the sitemap wiring, `notFound()` for unknown slugs, the
`/page/blog` landmine, and that the stage's own checkpoint lives in 19c rather than
anywhere earlier.

**Where I did not follow it:** it proposed 19a be CMS-only with the payments riders moving
to 19b — which I adopted — but suggested TipTap might simply move to 19c. I have kept that
as an explicit swap-later ruling rather than a vague deferral, because "19c will add
TipTap" is exactly the kind of promise Plan-17c had to retract three of.

---

## Completion record (2026-08-01)

All four slices built and each walked in a browser as it was built.

**19a — CMS pages.** `cms.Page`, write-time sanitisation, public endpoints, admin CRUD,
storefront route, sitemap. Live: a body containing `<script>`, `<iframe>` and `onclick`
reached the shop as allow-listed HTML with `rel="noopener noreferrer"` added.

**19b — Commerce config.** `BankAccount` (the orphan), `CountryPaymentGateway`, coupons and
flat `DeliveryOption` fields. Live: the `payments.W002` gap surfaced as "CA, US offer bank
transfer with no active account"; the account-number confirmation showed
`0123456789 → 2233445566` and Cancel left it untouched; `launch15` normalised to
`LAUNCH15`; the Lagos price saved at 1800.

**19c — Banners, sections, menus.** Live: an empty CMS fell back to the Plan-13 fixtures,
then a strip banner and a hero created in the admin both appeared within the 60-second
TTL — headline and eyebrow from the banner, sub-headline still the fixture because the
banner left it blank. **The stage's own checkpoint behaviour therefore passes**; the
CHECKPOINT itself is Hammed's to perform.

**19d — Coverage.** The 811-region tree, mixed granularity and the address tester. Live:
37 states collapsed with area counts; unticking Lagos and ticking Ikeja + Apapa produced
the "part" tri-state; the tester answered *offered* for Ikeja and *not offered* for Agege
in the same state; the save persisted exactly those two areas, and the original coverage
was restored afterwards.

backend 1679 passed / 3 skipped · admin 710 · storefront 734 · tsc, eslint, ruff clean.

### Two rulings changed while building

- **Ruling 4 was wrong about scope.** I had put bank accounts and gateways behind
  `orders.manage`. `rbac.py` had already filed the payout account under `settings.manage`
  (Owner-only), naming it "the single highest-value target in the system". The code's
  existing reasoning won.
- **Ruling 1's TipTap promise is RETRACTED, not carried.** 19a said the pages editor would
  swap onto TipTap in 19c. It has not, and the promise is withdrawn rather than deferred
  again: a large client dependency and a second stored content format, for eleven policy
  pages authored by one person. The textarea and the sanitiser stay. Adding TipTap later
  is a contained change and should be a decision, not a debt — which is exactly what
  Plan-17c had to retract three of.

### Still open, and not mine to close

- **Ten of the eleven pages have no content.** The machinery is done; an empty "Privacy
  policy" is legally worse than a missing one, so the text is Hammed's.
- **`/page/blog`** still needs the decision ruling 3 named: placeholder, or drop the link.
- **Plan-24's migrated/dropped page list** has an owner now (this plan) but no entries.
- **CA and US offer bank transfer with no account** — visible on `/settings/payments`.
