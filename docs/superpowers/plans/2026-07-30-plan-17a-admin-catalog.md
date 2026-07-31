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

**DONE 2026-07-30, with three findings that were not in the plan.**

1. **The column list was unbuildable as written.** `ProductAdminSerializer` exposed no
   image, no variant count, no pricing signal and not even `updated_at`, so the specified
   columns had no data behind them. Added as read-only `SerializerMethodField`s —
   `thumbnail`, `variant_count`, `priced_currencies`, plus `updated_at`. Method fields
   over prefetched relations rather than queryset annotations **on purpose**: an
   annotation renders on a list and then raises `AttributeError` on the POST/PATCH
   response, whose instance carries no annotation. A test pins that.

   `priced_currencies` counts **currency-level rows only**. A country override prices one
   country, and treating it as pricing the whole currency would report a product as
   available in a market it is still hidden in — the exact thing the column exists to
   surface.

2. **A pre-existing N+1, found by the new query-budget test.** The serializer renders four
   M2M fields (`categories`, `tags`, `related`, `available_countries`), none prefetched —
   a 12-product page measured **55 queries** and is now **11**. The JSON was identical
   either way, which is why it survived since Plan-05c. Not caused by this task; exposed
   by it.

3. **The admin CSP would have blocked every thumbnail.** `img-src 'self' data: blob:`
   admits no CDN host, so production images would render broken with nothing but a console
   violation to say why. The media host now joins `img-src` — one directive, one host we
   control, `script-src` and `connect-src` untouched.

   **Amended after review: the hostname is COMMITTED as the default**
   (`dk4ivng9pnc2t.cloudfront.net`), not left to a Vercel dashboard entry. Same name
   (`NEXT_PUBLIC_MEDIA_HOST`), same value and same reasoning as
   `storefront/next.config.ts` — commit `1f97396` hard-coded it there precisely because
   gating on a dashboard variable had already broken every production product image once.
   The first version of this task recreated that trap in the admin. The env var still
   overrides, for pointing a preview at another distribution. **No Vercel action is
   required.**

`components/Pagination.tsx` was generalised to take a `buildQuery` callback instead of
importing `AuditFilters`, and the pagination arithmetic moved to `lib/pagination.ts`
(re-exported from `lib/audit.ts`). The audit page's behaviour is unchanged and its tests
still assert it.

Verified: admin vitest **219 passed** (22 files), `tsc --noEmit` clean, `eslint` clean,
`next build` succeeds with `/products` in the route table.

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

**DONE 2026-07-30.** No backend change was needed. Four things worth carrying forward:

1. **The Availability panel states the empty case in words.** `available_countries` empty
   means **everywhere**, and a bare checkbox grid renders "none ticked" and "sold in every
   market" identically — so somebody clearing the last box to *withdraw* a product would
   have published it to all of them. The panel says which of the two is true, in a
   highlighted box, and a test pins both wordings.

2. **The PATCH body is built from an explicit `EDITABLE_FIELDS` list**, not by spreading
   form state. The serializer also writes `brand`, `related`, `published_at` and the legacy
   columns; a spread payload would send `undefined` for whichever a built tab does not own
   and clobber a value nobody on screen could see. Task 4 extends the list; that is the
   whole change.

3. **Saving uses the ORIGINAL slug in the URL and the new one in the body.** PATCHing to
   the edited slug would address a product that does not exist yet. On success the client
   `replace()`s to whatever slug came back — read from the response, not assumed, since the
   backend may normalise it — because the old URL now 404s and `push` would hand the back
   button a broken page.

4. **Reference pickers walk every page.** `/admin/categories/` and `/admin/tags/` paginate
   at 24 against 40 categories and ~84 tags, so a one-page fetch would silently omit the
   rest — presenting as "that category does not exist". `fetchAllPages` requests by page
   NUMBER rather than following the API's absolute `next`, which points at the Django
   origin and would bypass this app's API base.

`isDirty` is order-insensitive for multi-selects: a checkbox grid produces whatever order
the user clicked in, and treating `NG,GB` vs `GB,NG` as an edit would leave the
unsaved-changes bar up forever.

Verified: admin vitest **259 passed** (25 files, 40 new), `tsc --noEmit` clean, `eslint`
clean, `next build` succeeds with `/products/[slug]` in the route table.

Note: `@testing-library/user-event` is NOT a dependency of this app. Interaction tests use
`fireEvent` from `@testing-library/react`, matching `TotpPanel.test.tsx`.

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

**DONE 2026-07-30.** No backend change. Four decisions worth carrying:

1. **The SEO preview mirrors the storefront rather than approximating it**, with the source
   lines cited in `lib/seo-preview.ts`: `seo_title || name`
   (`product/[slug]/page.tsx:39`), `seo_description || short_description` (`:40`), and the
   `%s | Toke Cosmetics` template from `layout.tsx:21`. **Omitting that suffix would
   under-report the rendered title by 17 characters** — which is wrong exactly when
   somebody is trimming a title to fit. The URL uses `/product/<slug>`, singular; `/products`
   is the listing.

2. **A malformed spec/FAQ row is repaired, not discarded.** These are `JSONField(default=list)`
   holding whatever the WordPress importer produced across 69 products. A row missing a key
   gets `""` and survives; only non-objects are dropped. Silently deleting a partial row on
   the next save of an unrelated tab is the quietest kind of data loss.

3. **Blank rows are dropped on save but do not arm Save.** A row added and abandoned would
   otherwise promise a change that cannot happen, and the unsaved bar would never clear. A
   HALF-filled row is kept — a question typed but not yet answered is work in progress.

4. **`isDirty` now distinguishes sets from ordered rows.** `categories`/`tags`/
   `available_countries` are order-insensitive; `specs`/`faqs` are not, because reordering
   a spec table is a real edit. The old implementation would have compared object rows via
   `String(row)`, collapsing every row to `[object Object]`.

The PATCH body now comes from `toPatchPayload` in one place rather than being spelled out
in the action, so adding a tab is one edit to `EDITABLE_FIELDS`.

Verified: admin vitest **290 passed** (26 files, 31 new), `tsc --noEmit` clean, `eslint`
clean, `next build` succeeds.

### Task 5 — Images tab

Upload (existing multipart action), reorder, alt text, delete — the last three via Task 1's
new viewset. Per Decision 1 these take effect immediately, and the UI must say so.

Per the spec: an upload failure shows on the row and offers retry, and **must not discard
the rest of the form** — that is unsaved text the user cannot recover.

**Verify:** upload, reorder, rename alt, delete; force a failed upload and confirm the
Details tab's unsaved text survives.

**DONE 2026-07-30.** First consumer of Task 1's `ProductImageAdminViewSet`. Five decisions:

1. **`apiFetchRaw` gained a multipart branch.** It JSON-stringified every body and forced
   `Content-Type: application/json`, so the upload endpoint was unreachable. FormData now
   passes through with **no Content-Type set** — only fetch knows the boundary token, and a
   hand-written `multipart/form-data` header carries none, making Django parse an empty
   payload and answer "No file was submitted" for a request that plainly contains one. Its
   own test file exists because that failure is invisible from the client.

2. **No image action revalidates the editor page.** `revalidatePath` here would re-render
   the Server Component, remount the editor, and discard unsaved text in Details or
   Content — the spec names that as what a failed upload must not do, and a SUCCESS must
   not do it either. `/products` is revalidated because its thumbnail column is now stale
   and nothing there can be lost.

3. **Reordering renumbers the whole list rather than swapping two positions.**
   `ProductImage.position` has no uniqueness constraint and the migrated rows came from an
   importer, so duplicates are possible — and swapping two equal numbers changes nothing,
   with the row springing back on reload and no error anywhere. `positionWrites` then
   narrows the renumber to the rows that actually moved, so a one-step move costs two
   PATCHes.

4. **Image state lives in `ProductEditor`, not `ImagesPanel`.** The panel unmounts on every
   tab switch; state inside it would make an upload appear to vanish on the way to Details
   and back.

5. **Images get their own `useTransition`.** Sharing the save's would put the Save button
   into "Saving…" and disable it during an upload — announcing a write that is not
   happening, on the one tab whose whole point is that it does not save with the form.

Alt text writes on blur, not per keystroke; deleting asks twice, because it is immediate
and there is no undo; a failed reorder puts the order back.

Verified: admin vitest **318 passed** (28 files, 28 new), `tsc --noEmit` clean, `eslint`
clean, `next build` succeeds.

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

**DONE 2026-07-30.** The locked-cell rule turned out to be wider than the spec described.

**The spec named country overrides; `Price` has a second scoping axis too.** Its unique
constraint is `(variant, currency, country, starts_at)`, so a variant+currency legitimately
admits several rows: a country override, a **scheduled** future price, or both. The spec's
argument — an edit that appears to succeed while a narrower row governs what customers pay
is the worst failure this screen can have — applies identically to a scheduled row, so both
lock the cell. A cell is editable only when the plain row (`country` NULL, `starts_at`
NULL) is the *only* row for that variant+currency.

Measured in production 2026-07-30 before designing this: **0 country overrides, 0 scheduled
rows, 0 variant+currency pairs with more than one row**, so every locked path exists only
under test — which is why it is tested rather than deferred.

Two small backend additions, both additive and needing no guard changes:
`variant__product` on `PriceAdminViewSet` and on `StockItemAdminViewSet`. `variant` is an
exact-match filter, so without them the editor would issue one request per variant —
**ten** on the largest production product.

Other decisions:
- **Weight renders blank, never `0 g`.** Eight production variants have no weight, and a
  zero is a claim about a parcel rather than an absence — it is also the number a courier
  quote would be built from.
- **Warehouse columns are derived from the stock rows**, because no warehouse endpoint
  exists until 17c. A warehouse holding none of this product contributes no column; with
  one stock row per variant in production, a product routinely shows one column, not two.
- **A comma in a price is refused, not parsed.** "1,500" is 1500 to a Nigerian reader and
  1.5 to a German one, and guessing wrong writes a price off by a thousand.
- **The saved row's id is adopted** after a create, so a second edit of a cell that was
  empty a moment ago PATCHes instead of POSTing a duplicate the unique constraint rejects.
- Prices commit on blur and **do not arm the product Save button** — they are their own
  resource.

Verified: backend suite green, admin vitest **362 passed** (30 files, 44 new), `tsc` clean,
`eslint` clean, `next build` succeeds.

### Task 7 — stock adjust modal

Quantity read-only text + **Adjust** button. Modal takes new quantity, reason (from the
serializer's choices — `migration` is absent and must stay absent), and a mandatory note.
Posts to the `adjust` action. A plain editable number would be a lie about what the API
permits.

**Verify:** adjust a quantity, confirm the new figure and a `StockMovement` row with actor,
reason and note; confirm `migration` is not offered.

**DONE 2026-07-30.** No backend change — the endpoint was already the right shape.

- **The field is an ABSOLUTE count, not a change.** `inventory.services.adjust` SETS
  on-hand and stores the difference as the movement, so the modal says "This replaces the
  count, it is not added to it" and shows the delta live. Somebody reading it the other way
  would set a shelf of 300 to 47 and not notice.
- **Zero is valid and meaningful** (`IntegerField(min_value=0)`) — it is how a sold-out
  line is recorded, so it is tested rather than treated as an empty field.
- **`migration` is absent from the dropdown**, and the test asserts its absence rather than
  the presence of the others. It is the sentinel `apps/migration_wp/importers/stock.py`
  reads to find stock nobody has touched; a human writing it would strip that item's
  clobber guard.
- **All seven allowed reasons ARE offered**, in two labelled groups. A dropdown offering
  fewer choices than the endpoint accepts is a UI that disagrees with it — but `sale`,
  `reservation` and `release` are written automatically when an order moves, and a human
  picking one puts a row in the ledger that reads as though an order caused it. Grouping
  them under "Normally automatic" costs nothing and says so.
- **The saved row is adopted, not the typed number.** `adjust` returns the item as the
  database now holds it, and a concurrent reservation may have moved `reserved` since the
  modal opened.
- Errors are cleared on OPEN rather than on close, so a previous failure does not greet
  the next person to open the modal as though their own attempt had failed.

**GAP FOUND, not in scope, needs a decision.** Production keeps **one stock row per
variant** across two warehouses, and the Variants tab renders "—" where a variant has no
row in a warehouse. There is no Adjust button on those cells, because `adjust` operates on
an existing `StockItem` — so **there is currently no admin path to start stocking a variant
in a second warehouse.** `StockItemAdminViewSet` does accept POST, so the capability exists;
nothing calls it. It belongs with 17c's inventory screen, but it should be a conscious
deferral rather than a discovery: if the UK warehouse is ever to hold stock, this is the
missing step.

Verified: admin vitest **388 passed** (31 files, 26 new), `tsc --noEmit` clean, `eslint`
clean, `next build` succeeds.

### Task 8 — `/products/new`

Create flow. Minimum viable product record, then land on the editor for the rest — do not
ask for seven tabs before the first save.

Slug collisions surface the backend's message; **no client-side uniqueness check**, which
could disagree with the database.

**Verify:** create a product end to end; force a slug collision and read a useful message.

**DONE 2026-07-30.** No backend change.

- **Two fields, and nothing else.** Name and slug. Everything else is editable a second
  later on a page built for exactly that, and a create form asking for seven tabs' worth of
  detail is one nobody can put down half-finished.
- **Created as a DRAFT by omission**, not by sending `status`. The model defaults to
  `draft`, and a product created straight to `active` would be one with no price, no image
  and no copy. A test asserts the payload carries no `status` at all.
- **No client-side uniqueness check, per the spec.** Only the database knows whether a slug
  is free; a browser-side check that disagreed would refuse available slugs and admit taken
  ones. The backend's own sentence — "product with this slug already exists." — is rendered
  verbatim against the field.
- **The redirect follows the slug the backend RETURNED**, not the one submitted, since it
  may normalise it and the record has to be where we send the person.
- **The slug auto-fills from the name until it is edited by hand, then stops for good.**
  Silently rewriting a deliberate slug is noticed only after the product is live and the
  URL is wrong. Clearing the field resumes the link — an empty slug means "you choose".
- An empty slug is filled from the name rather than refused; a name of only punctuation
  slugifies to `""`, which is reachable and asks for a slug instead of failing obscurely.

`/products/new` resolves ahead of `/products/[slug]` — Next matches static segments before
dynamic ones — so no product may ever occupy the slug `new`. Left as-is: the collision is
harmless (that product would be unreachable, not misrendered) and guarding it would add a
rule the backend does not have.

Verified: admin vitest **422 passed** (34 files, 34 new), `tsc --noEmit` clean, `eslint`
clean, `next build` succeeds with all three product routes present.

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

**DONE 2026-07-30. The cycle question the task told me to check had a bad answer.**

**Nothing prevented a cycle, and the damage lands on the storefront, not here.**
`Category.parent` is a plain self-FK with no `clean()` and no database constraint, so one
PATCH could make a category its own ancestor. Two things then hang, both public:

- `Category.get_ancestors()` walked `node = node.parent` with no exit but `None` — it backs
  the PDP breadcrumb;
- `api_serializers.CategorySerializer.get_children` recurses into itself, so the category
  tree endpoint blows the stack.

A hung worker is worse than any tree shape, and this page — a parent select on all 40
categories — is exactly what would have made it reachable. So the guard ships with it:
`CategoryAdminSerializer.validate_parent` refuses a parent inside the category's own
subtree (self, child, or any deeper descendant), and `get_ancestors` now terminates on a
cycle already in the data rather than spinning. **This is a backend change and needs a
deploy** — `backend-v0.5.0` is live without it.

Other decisions:
- **The select hides the category and its whole subtree**, which is a courtesy; the
  endpoint is the fence. A check hiding only direct children would still offer a
  grandchild, and choosing it makes a cycle.
- **The form is keyed by the selected category**, so switching remounts it. That reloads
  the uncontrolled inputs (otherwise the previous category's name sits in a form pointed
  at a different record) *and* resets `useActionState`, so "Saved Skincare." does not hover
  above the Haircare form. The first attempt used `setState` in an effect; eslint's
  `react-hooks/set-state-in-effect` was right to refuse it.
- **Product counts are derived from the products list**, since no endpoint reports them.
  Affordable at 69 products, not at 6,900 — the answer then is an annotated count on the
  serializer, not a bigger fetch. They answer "can I safely hide this?".
- **Categories is its own nav item**, not a link inside Products: `activeHref` does
  longest-prefix matching, so nesting it under `/products/…` would highlight Products while
  the categories page was on screen.

Verified: backend **1423 passed**, admin vitest **445 passed** (36 files, 33 new), `tsc`
clean, `eslint` clean, `next build` succeeds with `/categories`.

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

---

## Task 9 — live walkthrough record (2026-07-31)

Real Django + Postgres + admin `next dev`, nothing mocked. Cloudflare **test** keys per
`turnstile-admin-setup.md` §6 (the real pair that was sitting in local `.env` files is
backed up as `.env*.bak-walkthrough-17ab`; the test pair is the documented dev posture).
A fresh `owner-walk@tokecosmetics.local` Owner account was taken through the full
ceremony — password → TOTP enrol (setup key read off the screen) → TOTP confirm — and
landed on the dashboard with the Owner nav.

**What passed, against real DRF responses:**

- `/products`: 28 real products, search (`?search=curl` → 1), status filter, page 2.
- The editor, all seven tabs, on `radiance-glow-serum` — Details, Availability (market
  tick-list with the "sold in every market" explainer), Variants (options + stock with
  "Adjust"), Prices (per-currency grid, country-override lockouts pointing at 17c),
  Content (ingredients/directions/warnings/specs/FAQs), Images (ordered, alt text),
  SEO (SERP preview with the "| Toke Cosmetics" suffix counted).
- A real PATCH: Details edit → "Saved." → survives reload → **DB verified** → audit row
  `partial_update Product #radiance-glow-serum` with actor, IP, timestamp.
- `/categories`: tree renders 11 with product counts; reparent Men → Body saved and
  **DB verified**, then reverted the same way. Cycle guard holds at the UI: Face's
  parent select excludes Face and all its descendants.
- Create flow: name-only form → draft created → redirected straight into the editor
  (`walkthrough-whip-butter`, left in place as a fixture for the checkpoint walk).
- Backend log: **zero 5xx across the whole session.**

**Findings, none blocking the checkpoint:**

1. **Category edit panel goes stale right after save.** Save "Men → parent Body"
   succeeds (DB confirms), but the panel then shows *No parent (top level)* while the
   tree shows the truth. A trusting second Save would silently move the category back
   to top level. Re-selecting the category shows the correct parent, so the bug is
   only the post-save form state — but this surface writes catalogue structure, so it
   should be fixed before heavy use.
2. **Audit `changes` never records the copy fields.** `ProductAdminSerializer.
   audit_allowlist` omits `short_description`, `description` and every Content-tab
   field, so an edit that changes *only* the description writes an audit row whose
   FIELDS list names nine *other* (unchanged, merely submitted) keys. The allowlist
   design is right; these keys just need adding (MAX_CHANGES_BYTES already caps size)
   — or the omission needs writing down where an auditor will read it.
3. **Sidebar links to unbuilt sections are bare 404s.** `/inventory`, `/customers`,
   `/reviews`, `/coupons`, `/content`, `/reports` all render the naked Next 404 with
   no shell. The dashboard tiles say "Coming in a later plan"; the nav should degrade
   the same way (placeholder page, or don't link).
4. **Product images cannot render anywhere in local dev.** The list requests relative
   `/media/...` against the *admin* origin (404); the Images tab requests
   `http://localhost:8000/media/...` and the admin CSP blocks it (`img-src 'self'
   data: blob: https://dk4ivng9pnc2t.cloudfront.net`). Production is presumably fine
   via CloudFront URLs; dev needs either an env-aware `img-src` or a media rewrite.
5. **Stale empty-state copy:** a zero-variant product's Variants tab still says
   creating variants "arrives in a later slice (17b)" — directly beneath the shipped
   17b builder.

**CHECKPOINT — still Hammed's to perform:** create one product end to end, himself.
The path is verified working; the account, servers and a worked example are in place.
