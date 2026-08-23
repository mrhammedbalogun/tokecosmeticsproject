# Plan-43 — AAJ Express door delivery (Nigeria, every state)

**Status: BUILT 2026-08-23, ships DARK.** Option seeded inactive (`Door Delivery (AAJ
Express)`, carrier_code `aaj`, sort 6). Backend + admin + storefront complete, 1,286
backend tests green, live-verified against AAJ's sandbox for quoting and the free
create-booking step. **The money call (`process-booking`) could NOT be rehearsed** —
see §6. Go-live is the runbook in §7.

The brief: "just the same way we implemented GIG delivery option". This mirrors Plan-32a
(GIG) in structure — `apps/delivery/aaj/{client,states,origins,quotes,shipments,capture,
tracking}.py`, an `AajShipment` row born at placement, an order-page panel, a deliveries
table — with the differences AAJ's API forces, each one measured first.

## 1. Inputs

- `AAJ/API Documentation.postman_collection.json` + `AAJ/CurL command Examples.docx`
  (test key + base URLs) — Hammed's folder.
- https://docs.aajexpress.org (33 pages, read in full 2026-08-23). Where the docs and the
  sandbox disagree, the sandbox wins; the disagreements are listed in §2.
- Sandbox: `https://dev.aajexpress.org/api/v2`, production `https://booking.aajexpress.org/api/v2`.
  Bearer API key (`Authorization: Bearer aaj-…`). The KEY picks the partner account:
  the docx's first key books as "Ayomide Enterprises" (acct 657357), the second as
  "Favs Inc" (558162).

## 2. Measured facts (sandbox, 2026-08-23) — the design follows from these

**Quoting.** `POST /quote` prices DOMESTIC without creating a real booking (the
`booking` id it returns 404s on get-booking). ~1.2–2.2 s. `data.quotes[0].total` is the
price and INCLUDES 7.5 % VAT. Inputs that move the price, in order of surprise:

| input | effect |
|---|---|
| receiver `stateOrProvinceCode` | **the zone.** State NAME and city string are ignored. An UNKNOWN code silently prices as Lagos (`XX/XYZZY/Ikeja` → ₦2,779). Hence `aaj/states.py`: our 37-row table, `None` → omit the option. |
| sender `stateOrProvinceCode` | also the zone: Abuja→Lagos ₦4,701, Abuja→Abuja ₦3,861, Kano→Lagos ₦9,099. Hence the origin's state is resolved per row, never a setting. |
| `actualWeight` | 1 kg tiers: ≤1 kg ₦2,779 intra-Lagos, 1.2–2 kg ₦3,564, 3 kg ₦5,535, 10 kg ₦17,568. Cache key is ceil-kg. create-booking refuses < 0.1 kg. |
| `packageDimension` | does not price (1×1×1 = 30×30×30), but is REQUIRED. Nominal 20×15×10 box sent. |
| postal code, city | do not price. City must be ≥ 2 chars; `"Town"` is some keyword that prices as Lagos — never send it. |

Zone table at ≤1 kg from Lagos: Lagos ₦2,779 (2 d) · Ogun/Oyo ₦3,861 (4 d) ·
FCT/Delta/Rivers/Nasarawa/Akwa Ibom/Cross River ₦4,701 (5 d) · Kano ₦9,099 (8 d).

**Three price tiers for the same route.** `/quote` retail ₦2,585 + VAT = ₦2,779;
`/quote` with the undocumented `partner:true` ₦2,360; **create-booking under our key
₦2,225 + VAT = ₦2,392** (the account's negotiated rate). Ruling (§4a): the customer is
priced from the documented retail quote; cost is recorded at booking; the ~14 % gap is
margin the deliveries table shows as `charged` vs `AAJ cost`.

**Coverage.** `GET /partner/booking/delivery-locations/aaj` lists all 36 states + FCT
with area names — door delivery everywhere. No LGA sync, no centroid precondition. (The
docs spell FCT `FC`; the endpoint says `FCT`; both price identically. They spell
`Nassarawa`; our table aliases it.)

**Booking is two calls.** `POST /partner/booking/create-booking` is FREE (docs + measured
`paid:false`), prices at the account rate, needs: contact `name` LETTERS AND SPACES ONLY
2–50 (`O'Brien-Smith` → 400), E.164 phone, `email` REQUIRED; address `addressLine1, city,
state, country, stateOrProvinceCode, countryCode` (+ `postalCode` for the sender);
`payments {accountNumber, transaction {generateTransaction, method CREDIT_FACILITY|WALLET}}`;
`category` (env-specific id; "Non Electronics" resolved by name from
`get-categories`); `customBookingId` (our order number — NOT searchable by
track-shipment). `POST /partner/booking/process-booking/{id}` is THE MONEY CALL → `data.
payload.shipment {tracking_id, labelDocuments[{carrier,url}]}`.

**The half-state.** With `method: WALLET` the sandbox answered HTTP 500 "Credit facility
cannot be charged" AND created a shipment record (tracking id, label PDF, status 0) while
the booking stayed `paid:false`. So a refusal is not proof of no side-effect.
`get-booking/{id}` exposes `paid` and `shipmentId`; `get-single-shipment/{id or tracking}`
gives `_id`, `trackingId`, `labelDocuments`. Capture reconciles after EVERY non-success.

**Void.** `DELETE /partner/shipment/void-shipment/{trackingId or _id}` body
`{"unrestricted": false}` → status 7, idempotent, "reverses pending charges", allowed until
the first hub scan (status 1 Received IS one). `delete-booking/{id}` removes an unprocessed
booking; refused once processed ("void shipment instead").

**Tracking.** `GET /partner/shipment/track-shipment/{trackingId}?extraDetails=false`, one
per call, no batch; partner rate limit 300/min. Numeric `status` across 107 sandbox
shipments: 0 Pending/label · 1 Received · 2 In transit · 3 Out for delivery ·
4 Delivered · 5 Exception · 6 Available for pickup · 7 Voided · 8 Returned ·
9 Clearance · 12 Reweighed. Events carry `scanType` (LABEL_CREATED, ORIGIN_SCAN,
ARRIVAL_SCAN, DEPARTURE_SCAN, OUTBOUND_SCAN, DELIVERY_SCAN, EXCEPTION_SCAN, RETURN_SCAN,
REWEIGH_SCAN, PICKUP_SCAN, DROPOFF_SCAN), `description`, `dateTime`, `meta.location`.
Track-by-BOOKING-id works pre-process but uses a DIFFERENT numbering (1 = "awaiting
payment") — never mix the two.

**Absent.** Webhooks (docs say "consider webhooks" five times and document none).
Wallet/credit balance endpoint. Any trace id (GIG's `apiId` has no analogue). A hub list
for `deliveryMode: PICKUP` (so: door delivery only). Sandbox test credit — both docx keys
now answer "Credit facility cannot be charged" on process-booking.

**Security note for AAJ.** `GET https://booking.aajexpress.org/api/v2/quote` returns other
customers' quotes (149k, paginated) with NO Authorization header. Key names only were
inspected. Worth an email to techteam@aajexpress.org.

## 3. What was built

Backend (`apps/delivery/aaj/`):
- `client.py` — Bearer key, envelope judged by `success` (a 500 can carry a business
  refusal), list-shaped validation messages flattened, connection errors retried, read
  timeouts never.
- `states.py` — the money-bearing 37-row state→code table; `state_code()` returns None
  rather than guess. Pinned against the fixture AND AAJ's live list by tests.
- `origins.py` — reuses `SenderLocation`; resolves each row's STATE (state_region → state
  label → nearest LGA centroid to the pin); selection = same state as receiver, else
  nearest by haversine, else lowest pk. Unresolvable rows are skipped, never Lagos.
- `quotes.py` — cached 6 h per (origin, state, ceil-kg); 4 s budget, 0 retries; `eta_days`
  rides along and `carriers.py` widens the row's `max_days` to it (min never rises).
- `shipments.py` — `AajShipment` born at placement; abandon releases `quoted` AND
  `booked` and queues `delete_aaj_booking` (HTTP via Celery, never in the on_commit lane).
- `capture.py` — create (free) → `booked` with `cost` → process (money, gated by
  `AAJ_PROCESS_ENABLED`) → `created`; every non-success of process re-reads get-booking and
  classifies (paid+shipment → created; unpaid no shipment → stay booked, retryable; unpaid
  with shipment or unreadable → `create_unconfirmed`). `check_unconfirmed` (read-only
  reconcile), `void_shipment` (+ clears order tracking fields), `fetch_label`. Names
  NFKD-folded, punctuation→space, 2–50, fallback to the email local part.
- `tracking.py` — 2-hourly poll; 4 → delivered (+ order hops), movement → in_transit
  (+ order shipped), 7 → voided / 8 → returned (terminal for the poll, staff emailed,
  order untouched), 5/12 → staff emailed once; stops at the first unreachable call;
  reconciles `create_unconfirmed` rows first.
- `tasks.py` — `poll_aaj_tracking`, `delete_aaj_booking`, `check_aaj_states` (nightly
  drift check of the code table against AAJ's list → staff email).
- Notification event `delivery.aaj_attention` (+ templates, preview).
- `carriers.py` dispatches by carrier_code; omits AAJ when any line has no weight (AAJ
  prices by weight and reweighs; GIG is unaffected). `KNOWN_CARRIERS` gains `aaj`;
  `known_delivery_services` lists it so Plan-41 blocks/masks work on `aaj`.
- `OrderSerializer.carrier_tracking` — one carrier-neutral scan shape for GIG and AAJ.
- Admin API: `aaj-shipments/` list, `orders/{n}/aaj/` panel, `/capture/` (manage),
  `/check/` (operate), `/void/` (manage), `/label/` (operate). Role matrix, surface guard
  and audit seatbelts extended.
- Settings: `AAJ_BASE_URL`, `AAJ_API_KEY`, `AAJ_ACCOUNT_NUMBER`, `AAJ_PAYMENT_METHOD`,
  `AAJ_CATEGORY_ID` (optional), `AAJ_SENDER_EMAIL`, `AAJ_SENDER_POSTAL_CODE`,
  `AAJ_PROCESS_ENABLED` (default False).

Admin: `AajPanel` on the order page (two-step confirm, booked/voided re-capture,
check, void, label, kill-switch notice, retail-vs-cost line), `/deliveries/aaj` table +
filter form, Deliveries card. `fail()` now also reads slug codes from `error` (the
delivery endpoints' shape) so `process_disabled`/`capture_unconfirmed` reach the panel.

Storefront: `TrackingBlock` renders `carrier_tracking`; `api-types.ts` regenerated
(it had been stale since Plan-39).

## 4. Rulings (with the second-opinion review folded in)

A Fable consult on the first design changed it in these ways — recorded plainly:
1. **No `price_changed` refusal.** It would never fire (booked cost is BELOW retail); the
   real post-hoc risk is REWEIGH, which now emails staff. Cost is recorded, the margin is
   written into the timeline event, and a cost above what the customer paid is logged.
2. **`booked` is reachable by abandon and re-capture**, and abandon deletes the unpaid
   booking at AAJ (customer PII under an unsearchable id otherwise sits there forever).
3. **No settings fallback for the sender's state** — resolved per row, unresolvable rows
   skipped. (`AAJ_SENDER_STATE` was removed before it existed.)
4. **Reconcile on every non-success**, not just timeouts — the measured half-state came
   with an HTTP 500 and a message.
5. **`AAJ_PROCESS_ENABLED` kill-switch**, default off, because the money call can't be
   rehearsed.
6. **`carrier_tracking`** instead of a second GIG-shaped field.
7. **ETA override widens `max_days` only.**
8. **Returned/voided never move the order**; staff are told; void clears the stale
   tracking line; void is offered on `created` and on `in_transit` only pre-hub-scan.
9. **Weightless lines omit AAJ.** 8 variants still carry no weight — fix before go-live or
   those carts simply won't see AAJ.
10. Quote timeout 4 s, void scope `orders.manage`, nightly state-code drift check.

Kept against the review: the origin's state resolution via the pin (nearest LGA
centroid) rather than requiring `state_region` on every row — the seeded Ogudu row has
neither label nor FK, and resolving from the pin every row must have is more accurate
than blocking AAJ until someone edits a form. A global `AAJ_SENDER_POSTAL_CODE` stays: it
does not price, and a per-row postcode field is a migration for a label line no Nigerian
rider reads.

(a) retail `/quote` for the customer — yes; (b) `booked` yes, refusal no; (c) max only;
(d) same-state-first, not haversine-first; (e) every non-success; (g) neither moves the
order. Parallel `aaj/` package: right for client/quotes/capture/tracking; the read surface
is the one shared piece (`carrier_tracking`).

## 5. Verification

- `pytest`: 1,286 passed (full suite) incl. 26 client/states, 12 quotes/origins,
  16 capture, 6 tracking, 2 checkout E2E, audit/role/surface seatbelts.
- Admin: `tsc` clean, `AajPanel.test.tsx` 6/6, existing 72 green; storefront `tsc` (only
  the pre-existing `proxy.test.ts` errors), 93 green.
- LIVE against the sandbox through our code: quotes Lagos ₦2,779/2 d, Kano ₦9,099/8 d,
  Delta ₦4,701/5 d, FCT ₦3,861/3 d from the Kubwa origin (same-state rule); create-booking
  via `capture_shipment` with the switch off → `booked`, cost ₦2,392 vs charged ₦2,779
  (margin ₦387 in the timeline), name sanitised to "Adeola O Brien Smith", booking read
  back `paid:false` and deleted. Admin `/deliveries`, `/deliveries/aaj` and an order page
  with an AAJ panel rendered authenticated with real rows.

## 6. What is NOT verified and why

`process-booking` (the charge) and therefore the real `tracking_id`/label shape from it.
Both docx keys answer "Credit facility cannot be charged" on the sandbox; the docx's
own label example was processed in January 2026 with credit that has since lapsed. The
code follows the docx's recorded response shape and tolerates `labelDocuments` as
objects or strings. This is exactly what the kill-switch and §7 step 6 exist for.

## 7. Go-live runbook

1. **Ask AAJ** (techteam@aajexpress.org): production API key + our `accountNumber`;
   which `method` is enabled (CREDIT_FACILITY vs WALLET); enable test credit on the
   sandbox key so process-booking can be rehearsed; confirm there is no partner webhook;
   mention the unauthenticated `/quote` listing.
2. Prod env: `AAJ_BASE_URL=https://booking.aajexpress.org/api/v2`, `AAJ_API_KEY`,
   `AAJ_ACCOUNT_NUMBER`, `AAJ_PAYMENT_METHOD`, `AAJ_SENDER_EMAIL`; leave
   `AAJ_PROCESS_ENABLED` unset (off). Restart web + worker + beat.
3. Subscribe an address to **AAJ shipment needs attention** on Email Notifications.
4. Give the 8 weightless variants a weight (carts containing them get no AAJ option).
5. Smoke quote from a prod shell (`priced_options_for_address` with the option
   temporarily active, or the Delivery tester once active) — expect retail figures.
6. **First controlled booking**: activate the option, place a staff order, capture →
   it stops at `booked` (switch off). Check the DUE booking in AAJ's portal (amount, names,
   addresses). Then set `AAJ_PROCESS_ENABLED=true`, restart, press "Charge AAJ booking…"
   → tracking id + label. Verify the charge on the AAJ account statement. Void it if it
   was a test parcel.
7. Optional Plan-41 mask on `aaj` if the retail-vs-account margin should be larger or
   smaller than AAJ's own gap.

## 8. Open items

- Sandbox credit (§6) — on AAJ.
- Receiver postal code is sent only when the address has one (AAJ: optional domestic).
- `check_aaj_states` and the poll rely on beat being up — same as GIG.
- A refunded `created`/`in_transit` AAJ shipment is not auto-voided (ops window, not a
  refund consequence); the order timeline + deliveries table show it.
