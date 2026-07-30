# Plan-17a — admin catalog: products list, editor, create, stock adjust, categories

Design spec: `docs/superpowers/specs/2026-07-30-plan-17a-admin-catalog-design.md`
(approved by Hammed 2026-07-30). Master spec: `master-tokerebuild.md` §
Plan-17-admin-catalog-inventory, sliced into 17a/17b/17c by the design spec.

Branch `plan-17a-admin-catalog` off `main` (`2db0b21`).

---

## Grounding facts, verified 2026-07-30 against production and the tree (do not re-derive)

**Production catalogue** (measured, and two of these changed the design):

| | |
|---|---|
| products | 69, all with images |
| variants | 122, across 18 multi-variant products (**26% of the range**) |
| variants with a usable weight | 114 (8 have none) |
| prices | 121, **all NGN**; 0 country-level overrides |
| stock items | 122 (117 with qty > 0) · warehouses 2 |
| categories | 40 · **brands 0** · collections 0 |
| currencies configured | NGN, GBP, USD, CAD |

**Backend as it stands**

- `apps/catalog/admin_views.py` — `AdminBaseViewSet` gives every catalogue viewset
  `AdminJWTAuthentication` + `HasAdminScope("products.manage")` + `AdminAuditMixin`, all
  three fail-closed by inheritance. Viewsets: Product (`lookup_field="slug"`), Category,
  Brand, Tag, Collection, ProductVariant, ProductVideo, Price, plus CSV import/export.
- `apps/inventory/admin_views.py` — `StockItemAdminViewSet` with
  `http_method_names = ["get","post","head","options"]` (no PUT/PATCH by design) and an
  `adjust` action; `StockMovementListView`; stock CSV import/export.
- `StockAdjustSerializer` requires `quantity` (min 0), `reason`, `note`. Reason choices are
  `StockMovement.REASONS` **minus `migration`** — that sentinel is machine-only and
  deliberately unreachable from this endpoint.
- Routes mount at `api/v1/admin/` (`config/urls.py:41-47`). `SimpleRouter`, not
  `DefaultRouter` — the surface guard refuses an `APIRootView` here.
- **FOUR** completeness guards force declarations for anything new. Corrected during
  Task 1 — the plan originally said three, and the fourth failed the full suite after the
  first three were green:
  1. `test_admin_surface_guard.ADMIN_SURFACE` — view class → required scope.
  2. `test_admin_role_matrix.MATRIX` — a row per endpoint, per role.
  3. `test_audit_guard.py` — DECLARATIVE: does the view carry the mixin, is its allowlist
     free of write-only fields, does it resolve a model label.
  4. `test_audit.py::WRITE_CASES` — BEHAVIOURAL: one real HTTP request per write endpoint
     proving one real row lands, plus a completeness test that fails on any admin write
     endpoint with neither a case nor a `READ_ONLY_VIEWS` declaration.

  3 and 4 are deliberately a pair, and the module docstring explains why at length: a
  declaration test is satisfiable by a class that ignores the thing it declares, which is
  exactly how the Plan-16 Task 3b preauth-token bug passed a green guard. **Adding an
  admin endpoint means touching all four.**
- Global default pagination is `PageNumberPagination`, `PAGE_SIZE = 24`.

**Admin app as it stands** (`admin/src`, 65 TS files)

- Precedents to follow, not reinvent: `staff/page.tsx` (Server Component, `requireAdmin`,
  `fetchWithAuthOrBounce`, `allSettled` + rethrow non-`ApiError`, 403 → a sentence not a
  crash), `staff/actions.ts` (Server Functions using `fetchWithAuth`),
  `settings/audit/page.tsx` (URL-driven filters), `components/Pagination.tsx`.
- `lib/nav.ts` already has `{ label: "Products", href: "/products", scopes:
  ["products.manage"] }` as a placeholder href. This plan makes it real.
- `lib/session.ts` exports `requireAdmin`, `fetchWithAuth`, `fetchWithAuthRaw`,
  `fetchWithAuthOrBounce`. **Server Components use `…OrBounce`; Server Functions use
  `fetchWithAuth`.** Never the latter in a page — it would blacklist a refresh token with
  nowhere to persist the replacement, silently ending the session.

**Standing instruction.** `admin/AGENTS.md`: this is Next 16.2.10 and it has breaking
changes against training data. Read the relevant guide under
`admin/node_modules/next/dist/docs/` **before writing any code** in that app. `params` and
`searchParams` are Promises.

---

## Amendment 1 — the backend gap is FOUR changes, not one

The design spec says "**One real gap** … `ProductImageAdminViewSet` … That is the only
backend work in this slice." That is wrong, and it would be discovered mid-Task-2 rather
than now.

**Verified 2026-07-30:** `grep -n "filter_backends\|filterset\|search_fields" backend/apps/catalog/admin_views.py`
returns **nothing**. Not one catalogue admin viewset has any filtering. The global default
is `DjangoFilterBackend`, but a backend with no `filterset_fields` on the view filters
nothing, and `SearchFilter` is not in the global list at all.

So four backend changes, not one:

1. **`ProductImageAdminViewSet` (PATCH + DELETE)** — the spec's known gap. `ProductImage`
   is uploadable via `POST /admin/products/{slug}/images/` but is not routed as a resource,
   so alt text, `position` and deletion are all unreachable. Task 3 (Images tab) is
   impossible without it.
2. **Search + status filter on `ProductAdminViewSet`** — the `/products` list is specified
   as "search, status filter, pagination" and the backend supports none of it today.
   The indexes are already there and were built for exactly this: `product_name_upper_trgm`
   on `UPPER(name)` (Plan-16 Task 6 proved a bare-column index is never consulted for
   `icontains`), and `variant_sku_trgm` on `UPPER(sku)`, commented "SKU lookup from the
   admin search box". The indexes anticipated a consumer that was never written.
3. **`?product=` on `ProductVariantAdminViewSet`** — the editor's Variants tab needs one
   product's variants. Today the endpoint returns all 122.
4. **Filtering on `PriceAdminViewSet`** — the Prices grid needs one product's prices.
   Today the endpoint returns all 121.

Without 3 and 4 the editor must fetch the whole catalogue and narrow it in the browser.
That works at 69 products and rots silently, and it repeats the Task 8 RSC-payload finding
from Plan-16: props handed to a Client Component are serialised into the flight data in
full, so "fetch everything, render one" ships everything to the browser.

**Consequence:** Task 1 grows. It is still the smallest task and still first, but it is four
declarations against three guards, not one.

**Not in scope, still:** Warehouse CRUD and the unpriced-per-market endpoint remain 17c, as
the spec says.

## Amendment 2 — the global search endpoint is not the list filter

`/admin/search/` exists (`apps/core/admin_search.py`, Plan-16 Task 6) and backs the topbar
`GlobalSearch`. It is a cross-model, mixed-shape, permission-filtered result set for "find
me that thing". The products list needs a single-model paginated list with a status facet.

They are different endpoints for different jobs and both should exist. Task 2 must not try
to render the list from `/admin/search/`, and must not widen `/admin/search/` to serve it.

---

## Tasks

Sequential. Two-stage review each, as Plan-16. The checkpoint fires at Task 9, as early as
the spec could place it; Task 10 sits after it so it can slip without blocking Hammed.

### Task 1 — backend: routing and filtering (the four gaps)

`apps/catalog/admin_views.py`, `admin_serializers.py`, `admin_urls.py`.

- `ProductImageAdminViewSet(AdminBaseViewSet)` — reuse `ProductImageAdminSerializer`
  (already has `audit_allowlist = ("product","alt","position","variant")` and
  `read_only_fields = ["product"]`, so a PATCH cannot reparent an image to another
  product). `http_method_names` limited to PATCH/DELETE + safe verbs: creation stays on the
  existing multipart action, and two create paths for one model is how they drift.
  Register as `images` on the router.
- `ProductAdminViewSet`: add `SearchFilter` alongside `DjangoFilterBackend` with
  `search_fields = ["name", "variants__sku"]` and `filterset_fields = ["status"]`.
  Confirm by `EXPLAIN` that the trigram indexes are consulted; if `SearchFilter`'s
  `icontains` does not reach them, say so in the plan rather than leaving a slow path
  undocumented. Watch for row multiplication from the `variants__sku` join — `.distinct()`
  where needed, and a test with a multi-variant product that asserts it appears once.
- `ProductVariantAdminViewSet`: `filterset_fields = ["product", "is_active"]`.
- `PriceAdminViewSet`: `filterset_fields = ["variant", "currency", "country"]`.

TDD this task — the four guards make the tests the specification.

**Verify:** new pytest cases green; `ADMIN_SURFACE`, the role matrix and `WRITE_CASES` all
updated (a missing row fails a guard, which is the point); a Manager can reach the image
routes and a Support user gets 403; searching a multi-variant product by SKU returns one
row.

**DONE 2026-07-30.** 20 new tests in `apps/catalog/tests/test_admin_filtering.py` and
`test_admin_image_resource.py`, written failing first. Declarations added to all four
guards. `ProductImageAdminViewSet` audits as `partial_update` — the mixin prefers the DRF
action name over the HTTP verb, so `update` was wrong and the behavioural guard caught it.

### Task 2 — `/products` list

Server Component. Search box, status filter, pagination via the existing `Pagination`
component. Filters in the URL (this is a list, not a form — the audit page is the
precedent, and Design Decision 3's local-state argument applies only to the editor).

Columns: image thumbnail, name, status, variant count, price presence per currency, updated.
No bulk actions — dropped in the spec at 69 products.

**Verify:** `/products` lists all 69 against production-shaped data; search by name and by
SKU; status filter; page 2 works; a scopeless user sees the 403 sentence, not a crash.

### Task 3 — editor shell + Details and Availability tabs

One client component owning form state for every tab, per Design Decision 3. Tabs
show/hide; **switching a tab must never be a navigation**. Panels are presentational
children taking values + `onChange` — do not give each tab its own form state.

- Details: name, slug, status, short/long description, categories, tags, is_featured
- Availability: `available_countries` checkboxes incl. International (Rest of World).
  Surface what empty means — `available_countries` empty = **everywhere**
  (`catalog/models.py:132-134`, Plan-05b `sellable_in`). A checkbox grid that renders
  "none ticked" and "sold everywhere" identically is a trap.

Saves via `PATCH /admin/products/{slug}/` as one Server Function. 400 field errors map onto
inputs; non-field errors to a banner on the active tab.

**Verify:** edit a name and a country set, save, re-read; a validation error lands on the
right input; the unsaved-vs-saved distinction from Decision 1 is visible in the UI.

### Task 4 — Content and SEO tabs

Content: ingredients, directions, warnings, plus `specs` and `faqs`, which are
`JSONField(default=list)` holding `[{"label","value"}]` and `[{"q","a"}]`. They need
repeatable row editors, not a raw JSON textarea.

SEO: `seo_title`, `seo_description` with a Google-style preview.

Note for the implementer: **all 69 products have empty ingredients/directions/warnings**
(`docs/migration/description-review.csv`) — this tab is the tool Hammed's team will use to
fix that, so empty states should invite input rather than look broken.

**Verify:** add two spec rows and one FAQ, save, re-read; the JSON shape matches what the
storefront PDP already renders.

### Task 5 — Images tab

Upload (existing multipart action), reorder, alt text, delete — the last three via Task 1's
new viewset. Per Decision 1 these take effect immediately, and the UI must say so.

Per the spec: an upload failure shows on the row and offers retry, and **must not discard
the rest of the form** — that is unsaved text the user cannot recover.

**Verify:** upload, reorder, rename alt, delete; force a failed upload and confirm the
Details tab's unsaved text survives.

### Task 6 — Variants and Prices tabs

Variants: flat list of existing variants — SKU, name, weight, stock per warehouse
(read-only, with Adjust), variant image. **No option-matrix, no generate-combinations —
that is 17b.** The 18 multi-variant products make editing existing variants non-optional.

Prices: grid of **variant × currency** (`Price` hangs off `ProductVariant`, so it is not
"a row per currency" — that would be right for 51 products and wrong for 18). Missing cells
flagged. Writes currency-level rows only (`country = NULL`).

**Country-override handling is mandatory even though production has zero.** Where a
non-NULL `Price.country` row exists, the cell renders read-only, names the country, and
refuses the edit with a pointer to 17c. A silently-hidden override means an edit that
appears to succeed and changes nothing — the worst class of bug. Test against a fixture.

**Verify:** set a GBP price on a multi-variant product, re-read; the override fixture
renders read-only and cannot be edited.

### Task 7 — stock adjust modal

Quantity read-only text + **Adjust** button. Modal takes new quantity, reason (from the
serializer's choices — `migration` is absent and must stay absent), and a mandatory note.
Posts to the `adjust` action. A plain editable number would be a lie about what the API
permits.

**Verify:** adjust a quantity, confirm the new figure and a `StockMovement` row with actor,
reason and note; confirm `migration` is not offered.

### Task 8 — `/products/new`

Create flow. Minimum viable product record, then land on the editor for the rest — do not
ask for seven tabs before the first save.

Slug collisions surface the backend's message; **no client-side uniqueness check**, which
could disagree with the database.

**Verify:** create a product end to end; force a slug collision and read a useful message.

### Task 9 — live walkthrough, then CHECKPOINT

A real browser pass against a real login, as Plan-16 Task 8. That pass found the RSC payload
leak every unit test had passed over, and a real login found `last_login` never being
written. Both were invisible to unit tests by construction.

**CHECKPOINT: Hammed creates one product end to end, himself.**

### Task 10 — `/categories`

Indented read-only tree, edit form with parent select and sort order. 40 categories.

**Drag-to-reparent is dropped**, not deferred — a parent select is the same capability
without a drag dependency, a keyboard fallback and cycle prevention. Cycle prevention is
still needed on the parent select itself (a category cannot be its own ancestor); confirm
whether the backend enforces it and add it if not.

**Verify:** reparent a category, reorder siblings, confirm the storefront nav still builds.

---

## Testing discipline

Per the spec, unchanged from Plan-16:

- **Backend:** TDD. The surface guard forces an `ADMIN_SURFACE` entry with a scope, the role
  matrix forces a row, the audit guard forces an `AdminAuditMixin` decision.
- **Admin app:** vitest for every lib function and presentational component. Server
  Functions tested by mocking `global.fetch` and asserting the request
  (`staff/__tests__/actions.test.ts` is the pattern).
- **Not unit-tested:** Server Component pages, matching existing precedent. They are covered
  by the Task 9 walkthrough.

## Non-goals

Carried from the spec so their absence stays a decision: option-matrix builder (17b);
warehouse CRUD, inventory grid, movement drawer, low-stock filter, CSV import wizard,
cross-catalogue unpriced checklist, country-level price overrides (17c); drag-to-reparent,
brands/collections CRUD, bulk actions (dropped).

## Risks

- **Task 6 is the fiddliest** and carries the override rule. It sits before the checkpoint
  because the editor is unusable on 26% of the catalogue without it.
- ~~**Task 1's search performance** is unproven.~~ **RESOLVED 2026-07-30, Task 1.** Django
  compiles both `icontains` lookups to exactly the expression the Plan-16 indexes are
  built on:

  ```sql
  WHERE UPPER("catalog_product"."name"::text)        LIKE UPPER(%shea%)
  WHERE UPPER("catalog_productvariant"."sku"::text)  LIKE UPPER(%4123%)
  ```

  `product_name_upper_trgm` is `GinIndex(OpClass(Upper("name"), "gin_trgm_ops"))` and
  `variant_sku_trgm` the same on `sku`, so the index expression and the query expression
  match and the index is usable. Whether the planner *chooses* it is a size question — at
  69 products it will seq-scan, correctly, and no `EXPLAIN` here can prove otherwise. The
  thing that could have been wrong was the expression, and it is right. Do not "tidy"
  these `search_fields` with `^` or `=` prefixes: both compile to a different lookup and
  strand the indexes.
- **The 8 weightless variants** are not this plan's job to fix, but the Variants tab is
  where they become visible. Showing weight as an empty cell rather than `0` matters —
  `0 g` is a claim, blank is an absence.
