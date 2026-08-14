# Plan-35 — the Deliveries menu: carrier shipment tables + shared pickup locations

## STATUS (2026-08-14)

**Slices 1–3 BUILT in dev, uncommitted** (session resumed after a machine crash — the
crash landed between writing this plan and starting the code; nothing was half-done).

- **Slice 1**: `AdminGigShipmentListView` at `GET /admin/gig-shipments/` — `orders.view`,
  read-audited, paginated (global PAGE_SIZE), `select_related("order")`, newest first.
  Filters hand-rolled like `AdminOrderListView` (the codebase precedent; django-filter
  can't express the JSON `Q` logic): `status`, `origin` (0 matches BOTH id-0 snapshots
  and the empty pre-Plan-34 dict), `service` (centre-snapshot presence), `placed_after`/
  `placed_before` (parsed eagerly — garbage dates match nothing instead of 500ing, an
  improvement over the order-list wart). `GigShipmentRowSerializer` composes rows purely
  from snapshots (empty origin renders as `{id: 0, name: "Ogudu (built-in)"}` — never
  resolved against today's settings). Guard rows added in all three files (surface,
  role matrix `_DESK`, audit READ_ONLY + READ_AUDITED). Tests:
  `test_gig_shipments_admin.py`, 5 cases incl. the origin-0 special case and
  pagination/ordering.
- **Slice 2**: nav `Deliveries` entry between Orders and Products (any-of
  `orders.view`/`products.manage`; nav tests updated — Support now sees it), `/deliveries`
  door page (Settings pattern), `/deliveries/gig` server page + `CarrierShipmentTable`
  (carrier-neutral columns+rows props, ruling 5) + `GigShipmentFilterForm` (plain GET
  form; origin choices from `/admin/sender-locations/` + built-in id 0, control degrades
  away for Support whose role 403s that list) + shared `Pagination`. `lib/deliveries.ts`
  mirrors `lib/orders.ts` (parse/query-string/lastScanStatus — prefers webhook
  `ScanStatusComment` over the poll's bare `Status` code); 8 vitest cases.
- **Slice 3**: migration `0015_senderlocation_lga_senderlocation_state` (blank
  CharFields, DISPLAY ONLY — model comment + serializer help text + form copy all say
  the pin routes). Serializer + audit allowlist rows. Component moved to
  `/deliveries/pickup-locations` (actions moved to that route's `actions.ts`;
  `/settings/delivery` card removed, old actions file points at the new home). Test:
  round-trip + a routing assertion (a wrong label never moves `select_origin`).
- **Slice 4 verification**: admin 849 vitest green, lint fully clean (also fixed 2
  pre-existing warnings in `DeleteProductButton.test.tsx`), build green with all three
  routes; TOTP Playwright walkthrough 12/12 (door cards, table rows incl. built-in
  labelling, origin filter → only Kubwa-routed, row→order link, pickup CRUD with
  state/lga round-trip at the new home, /settings/delivery card gone). Dev artifact
  order `TC-PLAN35T1` (Kubwa-routed shipment) kept for future walkthroughs. Backend
  full suite: run at session end (see conversation record).

**SHIPPED 2026-08-14** (Hammed's go-ahead the same day): 9659c22 → backend-v0.25.0 on
the VPS (one release with Plan-34; deploy clean first try, migrations 0013–0015
applied, healthz ok) + Vercel admin Ready. Live-verified: `/admin/gig-shipments/` and
`/admin/sender-locations/` 401 unauthenticated (exist, gated), all three /deliveries
routes 307→login, Ogudu seeded in the prod table, prod shipment count 0 (no GIG orders
yet — honest). Backend full suite 2437 passed pre-ship.

**Remaining**: the Plan-34 slice-4 prod steps — Abuja data entry (Hammed eyeballs the
pin at entry time), smoke quotes, Abuja staff E2E order.

Hammed's ask (2026-08-14): a "Deliveries" area in the admin with a GIG-deliveries
table (every shipment with pickup origin, destination, customer name/phone, what was
charged, "all necessary details"), a Pickup-locations page Managers and Owners
maintain, and room for AAJ (aajexpress.org) when that integration happens — which is
explicitly AFTER GIG is fully done. The routing "algorithm that looks at that table"
already exists (Plan-34: nearest active `SenderLocation` by haversine, snapshotted
per shipment); this plan is the operational SURFACE over it, plus one new backend
list endpoint.

Why it matters operationally: with two pickup locations, "what must MY shop pack
today?" has no answer in the admin — shipments are visible only one at a time inside
each order's GigPanel. The origin-filtered deliveries table is that answer.

## Grounding

| Fact | Source |
|---|---|
| `GigShipment` already holds everything the table needs: status, waybill, quote/cost/charged, `origin` snapshot, `centre` snapshot, last_scan, and the order FK carries customer name/phone/address snapshot | Plan-32a/34, delivery/models.py |
| `SenderLocation` is carrier-neutral (renamed from GigSenderLocation 2026-08-14, pre-commit, for exactly this plan and AAJ); CRUD lives at `/admin/sender-locations/` under `products.manage` | Plan-34 |
| The sidebar is FLAT (`admin/src/lib/nav.ts`); multi-section areas use a door page with section cards, gated any-of (the Settings pattern) | nav.ts docstring |
| A list naming every customer + phone is bulk PII; the order list precedent is `orders.view` + read-audit, with bulk EXPORT gated higher (`orders.manage` on the CSV) | test_admin_surface_guard.py reasoning |
| The three discovery guards (surface, role matrix, audit write-cases) each demand a row per new endpoint | learned twice in Plan-34 |
| AAJ has no API research yet — nothing here may depend on AAJ shapes | this plan |

## Design rulings

1. **Nav: one "Deliveries" item, door page, two sections** (three when AAJ lands).
   `{ label: "Deliveries", href: "/deliveries", scopes: ["orders.view", "products.manage"] }`
   — any-of, the Settings precedent: the desk (orders.view) comes for the shipment
   table, a Manager (products.manage) also gets Pickup locations; the door page shows
   only the sections the visitor's scopes cover. Sits between Orders and Products in
   the list. `activeHref` longest-prefix already handles the nesting.
2. **GIG deliveries = a read-only table over `GigShipment`,** new endpoint
   `GET /api/v1/admin/gig-shipments/` (`orders.view`, read-audited — same PII posture
   as the order list). Paginated (this table grows forever — never `pagination_class
   = None`), `select_related("order")`, newest first. Filters: `status`, `origin`
   (snapshot id, 0 = env sender), `service` (door/pickup), placed date range.
   Columns/fields: order number (link to the order page — capture stays THERE, ruling
   4), placed date, status, waybill, **origin name**, destination (centre name for
   pickups, else "area, state" from the order's address snapshot), customer name,
   customer phone, charged (customer paid), cost (wallet debited), last-scan
   status/time. Origin filter choices come from `/admin/sender-locations/` plus a
   built-in "Ogudu (built-in)" for id-0/empty snapshots — pre-Plan-34 shipments must
   not vanish from a filtered view.
3. **Pickup locations MOVES to `/deliveries/pickup-locations` and the
   /settings/delivery card is removed** — one home, or the two drift. The component
   (`SenderLocations.tsx`) and endpoint move unchanged; scope stays
   `products.manage`, which is exactly "Managers and Owners edit". `SenderLocation`
   gains optional display-only `state` and `lga` CharFields (Hammed's ask — human
   filing for a table that will grow) — **the PIN stays the only routing input.**
   Typing "Lagos" in a display field must never move a quote; the serializer help
   text and the form say so.
4. **The table reads; the order page acts.** No capture/label buttons in the table —
   capture is a money-moving act with its own confirm ritual on the order page
   (GigPanel), and duplicating it in a bulk surface invites a mis-click that
   dispatches a rider. The table's rows LINK; they do not fire.
5. **Carrier bones are shared, carrier pages are separate.** The table component
   takes columns+rows props (no GIG imports in the shared piece); `/deliveries/gig`
   composes it. When AAJ lands it gets `/deliveries/aaj` + its own endpoint over its
   own shipment model, reusing the component and the SAME `SenderLocation` table for
   origin routing. Nothing speculative is built for AAJ now — the door page simply
   doesn't show a section that doesn't exist.

## Slices

### Slice 1 — backend: the shipment list endpoint

- `AdminGigShipmentListView` (or viewset, list-only) at `/admin/gig-shipments/`:
  `orders.view`, `audit_reads = True`, pagination, django-filter on status/origin/
  service/date. Serializer composes the row from shipment + order snapshot fields
  (no N+1: select_related order; destination resolved from snapshots, zero HTTP).
- Guard rows: surface guard, role matrix (`_DESK`, like AdminOrderListView), audit
  read-case.
- Tests: filter correctness (origin id 0 ≡ empty snapshot), pagination, PII fields
  present, RBAC.

### Slice 2 — admin: nav + door page + GIG table

- nav.ts entry + Shell tests; `/deliveries` door page (Settings-style cards, scope-
  filtered); `/deliveries/gig` server page fetching page 1 + filter dropdowns
  (status chips, origin select, service), client table component with pagination
  controls. Empty state says what the table is for.
- The packing-desk flow is the acceptance test: filter origin=Kubwa → only
  Abuja-routed shipments, each linking to its order.

### Slice 3 — pickup locations move + state/lga fields

- Migration: `state`/`lga` CharFields (blank), serializer + audit allowlist rows,
  form fields with the "display only — the pin routes" copy, columns in the card
  list. Card relocates to `/deliveries/pickup-locations`; /settings/delivery loses
  it; /settings landing keeps pointing at Delivery (options) only.
- Tests: backend serializer round-trip; existing admin tests updated for the move.

### Slice 4 — verify + ship

- Full suites both apps; TOTP Playwright walkthrough: door page, GIG table with the
  dev shipments, origin filter, pickup-locations CRUD at its new home. Deploy =
  backend tag + Vercel admin (one release with Plan-34 or after it — Plan-34 must
  not wait on this).

## Risks / notes

- **Bulk PII**: the list is read-audited and paginated; a CSV export is deliberately
  NOT included (the order-list precedent gates bulk egress at `orders.manage` —
  if Hammed wants an export later it's its own endpoint at that scope).
- Legacy shipments (pre-Plan-34) have empty origin snapshots — every view treats
  empty as "Ogudu (built-in)" (ruling 2) so history stays legible.
- The GigPanel stays the acting surface; if the table ever grows actions, each one
  must re-run the order-page confirm ritual, not shortcut it.

## Non-goals (deliberate)

- The AAJ integration itself (API research, quoting, capture, tracking — its own
  plan series, only after GIG step 7 + Plan-34 go-live are done: Hammed's rule).
- Per-origin notifications (emailing the Abuja shop on new orders) — a follow-up
  once the table proves the workflow.
- CSV export, bulk actions, editing shipments from the table.
