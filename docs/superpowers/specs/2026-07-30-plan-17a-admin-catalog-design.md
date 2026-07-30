# Plan-17a — admin catalog: products list, editor, create, stock adjust

**Status:** design approved by Hammed 2026-07-30. Implementation plan to follow.

## Why this is 17a and not 17

`master-tokerebuild.md`'s Plan-17 entry describes eight separable subsystems: a products
table with bulk actions, a seven-tab product editor, a Shopify-style option-matrix variant
builder, a draggable categories tree, brands/collections CRUD, a warehouse manager, an
inventory screen with a CSV import wizard, and an unpriced-per-market checklist. Any of the
editor, the matrix builder, the inventory screen or the CSV wizard is plan-sized alone.

Built in one pass, nothing is usable until nearly all of it exists — and the checkpoint
("Hammed creates one product end-to-end") cannot fire until the very end. Plan-16 was eight
tasks and this is larger.

So it is sliced by **what gets used daily**, each slice ending in something usable:

| slice | contents |
|---|---|
| **17a** (this spec) | products list, product editor, create flow, stock adjust, categories |
| 17b | the variant option-matrix builder |
| 17c | warehouse CRUD, inventory grid, CSV import wizard, unpriced-per-market checklist |

## What the catalogue actually looks like (production, 2026-07-30)

Measured, not assumed — and two of these numbers changed the design:

| | |
|---|---|
| products | 69 (all have images) |
| variants | 122, across **18 multi-variant products** |
| prices | 121, **all NGN** — zero GBP/USD/CAD |
| stock items | 122 (117 with qty > 0) |
| warehouses | 2 |
| categories | 40 |
| brands | **0** |

**26% of the catalogue is multi-variant**, so an editor that only handles single-variant
products would be unusable on a quarter of the range. The editor must edit *existing*
variants from day one even though *generating* new ones waits for 17b.

**The catalogue is NGN-only**, so every product is invisible in the UK, US and Canada for
want of a price. That is not urgent: only Paystack is certified, so NG is the sole sellable
market by design, and pricing the others is blocked behind gateway work regardless.

**Zero brands**, so brand CRUD is dropped rather than deferred. Collections likewise.

## What already exists on the backend

Almost everything. Plan-05c and Plan-06 shipped admin viewsets for products, categories,
brands, tags, collections, variants, videos and prices; stock has a viewset with an
`adjust` action, a movements list, and CSV import/export.

**One real gap.** `POST /admin/products/{slug}/images/` uploads an image, but `ProductImage`
is not routed as a resource — there is **no way to delete an image, change its alt text, or
reorder it**. 17a adds a small `ProductImageAdminViewSet` (PATCH + DELETE). That is the only
backend work in this slice.

Two further gaps — Warehouse CRUD and an unpriced-per-market endpoint — belong to 17c and
are out of scope here.

## Screens

| route | purpose |
|---|---|
| `/products` | list: search, status filter, pagination |
| `/products/new` | create flow |
| `/products/[slug]` | tabbed editor |
| `/categories` | indented read-only tree + edit form (parent select, sort order) |

All behind `products.manage`, which Owner and Manager hold. As everywhere in this app, the
nav item is ergonomics and `HasAdminScope` on each endpoint is the fence.

**Editor tabs:** Details · Availability · Variants · Prices · Images · Content · SEO.

- **Details** — name, slug, status, short/long description, categories, tags, is_featured
- **Availability** — `available_countries` checkboxes including International (Rest of World)
- **Variants** — flat list of existing variants: SKU, stock per warehouse (read-only +
  Adjust), variant image. **No option-matrix, no generate-combinations** — that is 17b.
  Prices are NOT here; see below for why.
- **Prices** — a grid of **variant × currency**, editable, missing cells flagged
- **Images** — upload, reorder, alt text, delete
- **Content** — ingredients, directions, warnings, specs, FAQs
- **SEO** — `seo_title`, `seo_description`, with a Google-style preview

## Three ratified design decisions

Each was put to Hammed explicitly and approved on 2026-07-30.

### 1. Saving is per-resource, not one atomic action

The product's own fields (Details, Availability, Content, SEO) save together as a single
`PATCH /admin/products/{slug}/`. Variants, prices, images and stock are **separate API
resources** and save on their own, immediately.

The visible consequence, which the UI must make obvious rather than hide: uploading an
image or adjusting stock takes effect at once, while text edits need a **Save** click.

The alternative — one atomic save across all of it — needs a transactional endpoint that
does not exist. Building one would mean a bespoke write path around six models for a
convenience, and it would sit outside the per-resource audit trail that
`AdminAuditMixin` gives us for free.

### 2. Stock is adjusted, never overwritten

`StockItemAdminViewSet` sets `http_method_names = ["get", "post", "head", "options"]` — it
refuses PUT and PATCH outright. The only path to a quantity is the `adjust` action, which
requires a **reason** and a **note** and writes a `StockMovement`.

So the UI shows quantity as read-only text with an **Adjust** button opening a modal
(new quantity, reason from the model's choices, note — all mandatory). A plain editable
number field would be a lie about what the API permits.

This is a backend constraint and a good one: every quantity change has an author, a reason
and a ledger entry.

### 3. Tab state is LOCAL, not in the URL

This deliberately contradicts `/settings/audit`, where filters live in the URL and the
argument was that the URL should be the truth about what is on screen.

A form is different. URL-driven tabs make switching a **navigation**, and navigation
destroys unsaved edits — losing a half-written description because you clicked "SEO" is a
data-loss bug, not a UX wrinkle. Tab state therefore lives in client state and the panels
show/hide.

**Cost, accepted:** you cannot link somebody to a specific tab. Worth it.

**Consequence for implementers:** the editor is one client component owning the form state
for every tab. If it grows unwieldy, split by extracting each tab's *panel* as a
presentational child that receives values and an onChange — do not split by giving each tab
its own form state, which reintroduces the problem.

## The Prices grid, precisely

`Price` hangs off **`ProductVariant`**, not `Product`
(`pricing.Price.variant → catalog.ProductVariant`), so the grid is **variant × currency** —
one row per variant, one column per currency. A single-variant product renders as one row
of four; the largest multi-variant product renders as several. Describing it as "a row per
currency" would be right for 51 products and wrong for 18.

Configured currencies, verified in production: **NGN, GBP, USD, CAD**. Countries: NG→NGN,
GB→GBP, US→USD, CA→CAD, and **ZZ (Rest of World) → USD**, so a USD price serves both the
US and RoW.

**Country-level overrides are out of scope.** `Price.country` is nullable and NULL means
"every country using this currency"; a non-NULL row overrides one country. 17a writes and
edits **currency-level rows only** (`country = NULL`). Verified in production: 0 overrides
exist today, 121 currency-level rows.

**But the grid must not pretend they cannot exist.** If a variant ever has a country
override, a UI that silently showed only the currency-level row would let somebody edit a
price and see no effect on the storefront for that country — the worst class of bug,
because the edit appears to succeed. So: where an override exists, the cell shows it
read-only with a note naming the country, and editing is refused with a pointer to 17c.
A test covers this against a fixture even though production has none.

## Error handling

- **403** — render "Your role does not include managing products", not a crash. Same shape
  as `/staff` and `/settings/audit`.
- **400 with field errors** — map DRF's `{field: [msg]}` onto the corresponding inputs;
  show non-field errors in a banner at the top of the active tab.
- **409 / slug collision on create** — surface the backend's own message; do not invent a
  client-side uniqueness check that can disagree with the database.
- **Image upload failure** — the row shows the failure and offers retry; it must not
  discard the rest of the form, which is unsaved text the user cannot recover.
- **Server Component fetches** use `fetchWithAuthOrBounce`; **Server Functions** use
  `fetchWithAuth`. Never the latter in a page — it would blacklist a refresh token with
  nowhere to persist the replacement, silently ending the session.

## Testing

Same discipline as Plan-16.

- **Backend:** TDD the `ProductImageAdminViewSet`. The surface guard will force an
  `ADMIN_SURFACE` entry with a scope, the role matrix will force a row, and the audit guard
  will force a decision about `AdminAuditMixin` — all three are completeness checks that
  fail on an undeclared admin route, so they are the specification.
- **Admin app:** vitest for every lib function and presentational component; Server
  Functions tested by mocking `global.fetch` and asserting the request, per
  `staff/__tests__/actions.test.ts`.
- **Not unit-tested:** Server Component pages, matching existing precedent. They are
  covered by the live walkthrough.
- **Live walkthrough before the checkpoint**, as in Task 8 — that pass found the RSC
  payload leak that every unit test had passed over, and a real login found `last_login`
  never being written. Both were invisible to unit tests by construction.

## Task order

The checkpoint fires as early as possible, and the fiddliest screen sits after it so it can
slip without blocking.

1. `ProductImageAdminViewSet` — PATCH + DELETE, with guard declarations (backend)
2. `/products` list — search, status filter, pagination
3. Editor shell + Details and Availability tabs
4. Content and SEO tabs
5. Images tab — upload, reorder, alt, delete
6. Variants and Prices tabs
7. Stock adjust modal
8. `/products/new` create flow
9. Live walkthrough, then **CHECKPOINT: Hammed creates one product end to end**
10. `/categories` — tree + parent select + sort order

## Non-goals

Named so their absence is a decision rather than an oversight.

| not in 17a | where it goes |
|---|---|
| Variant option-matrix builder | 17b |
| Warehouse CRUD (needs a backend endpoint) | 17c |
| Inventory grid, movement history drawer, low-stock filter | 17c |
| CSV import wizard (upload → map → dry-run → apply) | 17c |
| Cross-catalogue unpriced-per-market checklist | 17c — the per-product flag in the Prices tab covers the immediate need |
| Drag-to-reparent categories | dropped — a parent select is the same capability for 40 categories that are rarely reorganised, without a drag dependency, a keyboard fallback, or cycle prevention |
| Brands and collections CRUD | dropped — 0 brands exist; revisit if that changes |
| Bulk actions on the products list | dropped — 69 products; revisit past a few hundred |
| Multi-currency price entry as a workflow | the grid accepts it, but there is no market that can sell in those currencies yet |
| Country-level price overrides (`Price.country` non-NULL) | 17c — 17a writes currency-level rows only, and shows any existing override read-only rather than hiding it |
