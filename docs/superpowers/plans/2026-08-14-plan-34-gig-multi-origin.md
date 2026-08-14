# Plan-34 — GIG multi-origin: pickup from the closest Toke location

Toke now has TWO fulfilment points — Ogudu Mall (Lagos, the current sender) and a shop
in Abuja — and both carry the full catalog (Hammed, 2026-08-14). Today every GIG
shipment originates from six `GIG_SENDER_*` env vars, so an Abuja customer's parcel is
priced and dispatched Lagos→Abuja interstate. Routing Abuja-area orders to the Abuja
origin turns them into intra-city jobs: cheaper (sender pin moved Ogudu→Ikorodu
repriced +85% — the pin drives the price), faster, and the rider collects locally.

**Confirmed before planning (2026-08-14, Hammed):**
- Ogudu Mall is correct and stays (`Shop No 1, Ogudu Mall, Kosofe, Ogudu, Lagos`,
  6.5765217/3.3893872).
- Abuja carries the FULL catalog — routing can stay pure geography, no stock check.
- GIG confirms account `ECO078703` can originate pickups in Abuja.

## STATUS (2026-08-14)

**RENAMED pre-commit (2026-08-14, later the same day):** `GigSenderLocation` →
`SenderLocation` everywhere (model, admin classes, migrations regenerated as
`0013_senderlocation_gigshipment_origin` + reseeded 0014, guard/matrix/audit rows,
tests, this doc). A pickup address is carrier-neutral — AAJ (Plan-35's non-goal,
its own future plan) will route from the SAME table. API route (`/admin/
sender-locations/`) and admin UI were already neutral, so nothing user-facing moved.
Dev DB rolled back to 0012 and re-migrated; Ogudu (seed) + Kubwa (dev data entry)
both present. Delivery + all three guard suites re-run green (755 tests) after the
rename. See [[2026-08-14-plan-35-deliveries-menu]] for the surface that grows out
of this.

**SHIPPED 2026-08-14**: 9659c22 → backend-v0.25.0 (one release with Plan-35, which
also moved the pickup-locations page to /deliveries and added display-only state/lga
fields). Prod migrations 0013–0015 applied, Ogudu seeded, healthz ok, Vercel admin
Ready. Slice 4 steps 2–4 remain: Abuja prod data entry (eyeball the pin below at
entry time), smoke quotes, Abuja staff E2E order.

**Slices 1–3 BUILT in dev, uncommitted.** Model + migrations 0013/0014 (Ogudu seeded),
`gig/origins.py` selection, v2 origin-scoped cache keys, origin in cached payload →
`GigShipment.origin` → capture SenderDetails (all-or-nothing coordinate rule),
`SenderLocationAdminViewSet` (`products.manage`, guard row added, delete refused
once referenced), Pickup-origins card on /settings/delivery, GigPanel "Collecting
from" + capture confirm names the shop. Tests: delivery+checkout green incl. 15 new
(origins selection, quote body/cache isolation, placement lift, capture snapshot +
partial-snapshot rule, admin CRUD/validation); admin 835 vitest + lint + build green;
verified live in dev by TOTP Playwright walkthrough (Ogudu listed, Abuja row added
through the real form).

**Abuja data for prod entry (slice 4 step 2)** — geocoded via Places API (New),
exact-name hit "F01 Building Materials Market kubwa":
- Name: `Kubwa (Abuja)` · Locality: `Kubwa`
- Address: `Shop 7, Lane 3, Gate 1, Phase 2, F01 Building Materials Market, Kubwa, FCT`
- Pin: **9.161219, 7.355617** — Hammed should eyeball this on the map at entry time
  (the pin is the rider's destination; slice-4 step 2 discipline).
- Phone: `+2347074800702` — **the SAME number as the Ogudu sender** (Hammed supplied
  it 2026-08-14). Works, but GIG's Abuja rider will call a Lagos-answered line; if the
  Abuja shop has its own number, prefer it.

## Grounding (measured in 32a/32b or settled)

| Fact | Source |
|---|---|
| Sender is pure per-request data: `/price/v3` takes `SenderLocation` coords, `/capture/preshipment` takes the full `SenderDetails` block; no station id binds the account to one origin | quotes.py:97, capture.py:195 |
| The rider drives to the sender PIN; price follows the pin (Ogudu vs Ikorodu = ₦3,533 vs ₦6,526) | go-live 2026-08-13 |
| Quote cache is keyed `(region|centre, ceil-kg)` — origin is NOT in the key today | quotes.py `_cache_key` |
| Placement snapshots the cached quote payload verbatim via `carrier_quote_key`; capture trusts the snapshot | shipments.py, capture.py |
| `haversine_km` already exists and powers `nearest_centre` | gig/centres.py, carriers.py |
| `inventory.Warehouse` exists (priority-based stock reservation, per-country) but has no address/coords/phone — different job | inventory/models.py |
| One GIG wallet funds all shipments regardless of origin | account model |
| 3pm cutoff for same-day dispatch (assumed per station — asked nowhere; cosmetic) | GIG dev 2026-08-11 |

## Design rulings

1. **Origins become data: `SenderLocation`** (delivery app) — `name`, `phone`,
   `address`, `locality`, `latitude`, `longitude`, `is_active`. Deliberately NOT an FK
   to `inventory.Warehouse`: Warehouse models *stock reservation* (priority,
   serves_countries) and has no physical address; coupling them would entangle "where
   stock is debited from" with "where the rider collects", which are allowed to differ.
   Aligning the two is a future slice if it ever matters (see non-goals).
2. **Selection = nearest active origin to the quote's receiver point**, by
   `haversine_km`. For home delivery the receiver point is the door pin (else LGA
   centroid); for centre pickup it is the CENTRE's coordinates — the parcel travels
   origin→centre, so origin follows the centre, not the customer's home. Deterministic,
   explainable to a customer ("shipped from our Abuja store"), one selection per quote,
   zero extra HTTP. *Not* cheapest-of-N: that doubles GIG calls per render, and GIG's
   zone pricing makes nearest ≈ cheapest in every case we can construct; revisit only
   with evidence.
3. **The chosen origin rides INSIDE the cached quote payload** and is snapshotted onto
   the shipment at placement — a new `GigShipment.origin` JSONField (`{id, name, phone,
   address, locality, latitude, longitude}`), sibling of `centre`. This is the same
   discipline as centres and door pins: capture ships from EXACTLY the origin the
   customer was quoted from, even if rows are edited or deactivated in between.
   Quote→capture consistency is structural, not hoped for.
4. **Cache keys gain the origin id and bump the version**: `gig:quote:v2:{origin_id}:
   {region_id}:{kg}` and `gig:quote:pickup:v2:{origin_id}:{centre_id}:{kg}`. Without
   this, two origins would poison each other's 6-hour cache and customers would be
   charged one origin's price while capture debits another's. The v1→v2 bump also
   orphans (not corrupts) all pre-deploy cache entries.
5. **Env vars stay as the structural fallback.** Zero active `SenderLocation` rows →
   behave byte-for-byte as today from `GIG_SENDER_*` settings (selection returns a
   settings-backed pseudo-origin, id `0`). The deploy is safe before any data entry,
   and an admin who deactivates every row gets Ogudu-from-env, never a 500 or a
   quote-less checkout. Same fallback at capture for shipments whose snapshot predates
   this plan (empty `origin` dict = the env origin, which is what they were quoted from).
6. **Admin CRUD lives on /settings/delivery** — a "Pickup origins" card: list, add,
   edit, deactivate (two-step, like payment-gateway remove); delete only for
   never-used mistakes. Backend `SenderLocationAdminViewSet` under
   `products.manage` (the scope that already owns every delivery surface —
   `DeliveryOptionAdminViewSet` precedent; `test_admin_surface_guard` gets the row).
   Coordinates are pasted as numbers (Google Maps right-click → copy), validated to
   Nigeria's bounding box (lat 4–14, lng 2.5–15) — a map picker is a nice-to-have the
   admin app has no component for yet; do not build one for two rows.
7. **Phone per origin is load-bearing, not decorative**: GIG calls the sender number to
   coordinate the pickup. Validate E.164 (the Plan phone-registration validator is
   already in the codebase); the Abuja row must carry the Abuja shop's phone, or GIG
   phones Lagos about an Abuja pickup.
8. **The admin sees the routing before the money moves.** `AdminGigShipmentView` gains
   an `origin` block; the GigPanel shipment card shows "Collecting from: <origin name>"
   and the capture confirm copy names it — the packing desk in Ogudu must never press
   capture on a shipment routed to Abuja, and vice versa. This is the human fence for
   the ops gap software can't close (who packs what).

## Slices

### Slice 1 — model, selection, seed (backend)

- `SenderLocation` model + migration; seed migration creates the Ogudu Mall row from
  the live values (name/phone/address/locality/6.5765217/3.3893872) so prod selection
  is identical before and after deploy. Abuja is DATA ENTRY, not a migration — Hammed
  supplies address/phone/pin via the admin (runbook below).
- `gig/origins.py`: `select_origin(receiver_lat, receiver_lng) -> Origin` — nearest
  active row by `haversine_km`, else the settings fallback (ruling 5). `Origin` is a
  small frozen dataclass; `as_snapshot()` emits the JSON dict.
- Unit tests: nearest wins, ties stable, inactive skipped, empty table falls back,
  bounding-box validation.

### Slice 2 — quotes + placement + capture carry the origin (backend)

- `quote_home_delivery` / `quote_centre_pickup` select the origin (receiver point per
  ruling 2), send its coords as `SenderLocation`, key the cache per ruling 4, and store
  `origin: as_snapshot()` inside the cached payload.
- `create_quoted_shipment` lifts `origin` out of the cached payload into
  `GigShipment.origin` (migration adds the field, default `{}`). Cache-miss-at-placement
  keeps today's behaviour (empty quote, log line) — and empty origin = env fallback.
- `capture.py` builds `SenderDetails` from the snapshot (fallback: settings), keeping
  `InputtedSenderAddress` = the snapshot address. No other capture logic moves.
- Tests: quote body carries the selected origin's coords; Lagos-pin and Abuja-pin
  customers get different cache keys and different sender coords; placement snapshot
  round-trips; capture body uses the snapshot even after the row is edited; legacy
  empty-origin shipment captures with env values.

### Slice 3 — admin surface (backend + admin app)

- `SenderLocationAdminViewSet` (CRUD, audit-mixin, `products.manage`, no
  pagination — operator-scale rows), wired into the admin router; serializer validates
  E.164 phone + NG bounding box; `destroy` refused once any `GigShipment.origin.id`
  references the row (deactivate instead — the snapshot answers history, but the
  refusal keeps the id-space honest).
- /settings/delivery "Pickup origins" card: table + add/edit form + two-step
  deactivate. Server actions follow the payments-settings patterns (try/catch, honest
  errors).
- `AdminGigShipmentView` + GigPanel: origin row + capture confirm copy (ruling 8).
- Tests: viewset CRUD + guard row in `test_admin_surface_guard`, admin component tests
  per house pattern.

### Slice 4 — go-live (runbook, prod)

1. Deploy backend tag + Vercel admin. Prod behaviour unchanged (seeded Ogudu row ==
   env values; keys bumped to v2 so no stale-cache ambiguity).
2. Hammed enters the Abuja origin in /settings/delivery: exact shop address, locality,
   Abuja shop phone, pin from Google Maps. **The pin is the price and the rider's
   destination — same care as the Ogudu confirmation.**
3. Smoke quotes from a shell: an FCT-pin receiver must select the Abuja origin and
   price intra-city (expect roughly the Lagos-intra ballpark, NOT the current
   Lagos→Abuja interstate figure); a Lagos receiver must still price exactly today's
   ₦3,532.97-class numbers. Record both in this doc.
4. Staff E2E order with an Abuja address: pay → capture → rider arrives at the ABUJA
   shop → scans → wallet debit reconciles vs `GigShipment.cost`. This is the Abuja
   twin of the still-open step 7 for Ogudu — one visit can close both.
5. WhatsApp GIG (cosmetic, non-blocking): confirm the 3pm cutoff applies per station.

## Risks / open items

- **Ops routing is the real risk, software's fence is ruling 8**: an Abuja-routed
  order must be packed in Abuja. Until there's a per-origin order view (non-goal), the
  GigPanel origin line + capture copy is the guard; Hammed decides how Abuja staff get
  told (likely: they check the orders list; a filter can come later if volume asks).
- Interstate orders from far-north states will now route to Abuja where they used to
  route Lagos — prices CHANGE for existing coverage the moment the Abuja row goes
  active. That is the point, but note it: quotes are cached 6h per origin, so the
  switch is clean-keyed, and any customer mid-checkout re-prices at placement (same
  request, same key — consistent).
- GIG's insufficient-balance error shape is still unknown (open since go-live);
  unchanged by this plan — one wallet serves both origins.
- Weight/vehicle logic untouched; `VehicleType` stays the global default (Bike).

## Non-goals (deliberate)

- Stock-aware routing / `Warehouse` coupling: Abuja carries the full catalog, so
  geography suffices. If assortments ever diverge, selection gains a stock predicate —
  that is a different plan with reservation-lane consequences.
- Cheapest-of-N quoting (ruling 2), per-origin cutoff copy, per-origin admin order
  queues, DHL (Plan-32c), map-based pin picker in the admin.
