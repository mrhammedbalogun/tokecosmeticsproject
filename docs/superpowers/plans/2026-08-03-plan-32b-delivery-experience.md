# Plan-32b — the delivery experience: GIG centre pickup + address accuracy

Two workstreams, one phase, because they rework the same stretch of checkout and feed the
same coordinates. **In scope before cutover** — Hammed's ruling 2026-08-03: no cutover
until the project is completely done.

- **A. Centre pickup**: in the ~200 active-but-no-home-delivery LGAs, pickup at a GIG
  centre is the ONLY GIG service (their dev, confirmed). Building it takes GIG from 103
  LGAs to 303.
- **B. Address accuracy**: Places autocomplete as an ASSIST plus a confirm-your-pin map
  step. The pin — not the text — is what a rider navigates by, and it upgrades GIG from
  LGA-centroid to door coordinates.

## Grounding (measured in 32a, or settled)

| Fact | Source |
|---|---|
| `serviceCentresByStation?StationId=` → name, street address, coordinates per centre (64 for Lagos) | measured 2026-08-02 |
| `PickUpOptions` 0/1 on `/price/v3`; sandbox priced them identically | measured; production pricing TBC |
| How `capture/preshipment` expresses centre delivery | **UNKNOWN — task 0 + WhatsApp Q pending** |
| 303 active / 103 home-delivery LGAs (sandbox); production list at go-live | coverage sync |
| Region centroids 774/774; `Address` has NO lat/long yet | slice 1 / research §2b |
| Centroid-vs-door price spread ~2–3% intra-city, 0% inter-state | measured — the pin matters for the RIDER, barely for the price |

## Design rulings

1. **The structured state → LGA selection stays the source of truth.** It drives
   pricing, coverage and the centroid fallback, cannot be misspelled, and works for the
   addresses Google doesn't know. Google is an assist, never a gate: free text always
   remains valid, and no customer can be dead-ended by an unmapped street.
2. **The pin is the deliverable of the address rebuild.** `Address` gains nullable
   `latitude`/`longitude`. The map step prefills from the Places pick, else the LGA
   centroid, and asks the customer to drop it on their gate. With a pin, GIG quotes and
   waybills use door coordinates and `InputtedReceiverAddress` keeps the typed text;
   without one, everything falls back to the centroid exactly as today. Nothing breaks
   in either direction.
3. **The customer chooses the centre; we sort by distance.** Nearest-to-home is often
   not most-convenient (work beats home). The picker lists the closest centres to the
   address pin (else LGA centroid) with name + street address, computed by haversine
   from data we already hold — no third-party call.
4. **The chosen centre is SNAPSHOTTED onto the order** (name, address, GIG ids), like
   the shipping address is: centres close and move, and "where do I collect my parcel"
   must answer from the order forever.
5. **Two dark option rows, one integration.** `DeliveryOption` gains
   `carrier_service` (`"home"`/`"pickup"`); a second seeded row "Pickup at GIG Centre"
   covers NG, inactive. Home delivery offers only in home-delivery LGAs (as now);
   pickup offers in every active LGA. Both live-quoted with the `PickUpOptions` flag;
   both omit-on-failure onto the flat rates.
6. **Pickup changes the words everywhere.** Confirmation and shipped emails say
   "collect from <centre>, <address> — bring your order number and ID", never doorstep
   language. The admin panel and the customer order page show the centre. `GigShipment`
   records it.
7. **The LGA-mismatch nudge, never an override.** If a Places pick resolves to a
   different LGA than the customer selected, prompt to update — silently overriding
   would let Google's admin boundaries (which do not match LGA names cleanly) corrupt
   the field that prices delivery.
8. **Cost control is structural**: autocomplete with session tokens, mounted on the
   street field only, NG checkouts only; browser key referrer-locked to our domains.
   A few cents per completed checkout. Mapbox is the named fallback if billing ever
   offends; Google's Nigeria coverage earns the default.
9. **`GigCentre` is synced nightly like `GigLga`** (per-station sweep), because the
   picker needs fresh centres — but the order's snapshot (ruling 4) is what fulfilment
   and the customer read.

## Task 0 — sandbox first (blocks slice 5 only)

Create one centre-pickup preshipment in the sandbox to learn the capture field shape
(`DestinationServiceCenterId` + centre coordinates as `ReceiverLocation` is the guess).
The WhatsApp question is already queued; whichever answers first wins. Also re-verify
pickup-vs-home pricing on production credentials when they arrive.

## Slices

1. **Backend data.** `Address.latitude/longitude` (nullable, migration);
   `GigCentre` model + nightly sync + haversine helper; `DeliveryOption.carrier_service`
   + seeded dark pickup row. *Verify:* live sandbox sync lands Lagos's 64 centres;
   nearest-centres helper spot-checked against a map.
2. **Quote layer + picker API.** Pickup quoting (`PickUpOptions=1`); authenticated
   `centres-near-address` endpoint (address id → sorted centres, throttled). Address
   pin, when present, replaces the centroid in BOTH services' receiver location.
   *Verify:* respx suites for both services; live sandbox quotes for a pickup LGA.
3. **Address rebuild (storefront).** Autocomplete assist + pin-confirm map + mismatch
   nudge, in checkout AND the account address book; pin round-trips through the
   address API. Env: `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (Hammed creates the billing
   account + referrer-locked key). *Verify:* browser walkthrough — mapped address via
   suggestion, unmapped address via free text + hand-dropped pin, both save
   coordinates; a checkout with no pin still completes.
4. **Centre picker (storefront).** The pickup option reveals the sorted centre list;
   placement carries the centre; `GigShipment` + order snapshot store it.
   *Verify:* browser walkthrough in a pickup-only LGA; the order page and emails name
   the centre.
5. **Fulfilment + capture** (after task 0 answers). Pickup capture shape; admin panel
   shows the centre; pickup-flavoured email copy. *Verify:* one live sandbox
   centre-pickup waybill end to end, driven from the admin UI.
6. **Closeout.** UAT scenarios (pickup-only LGA checkout, mismatch nudge, no-pin
   fallback, centre snapshot after a centre vanishes from sync); go-live runbook
   addendum (flip BOTH GIG rows, verify production pickup pricing).

Sequencing: 1–2 backend-parallel; 3 and 4 are the same checkout surface — 3 first, 4 on
top of it; 5 gated on task 0. All of it lands before Plan-26 UAT, per the no-cutover
ruling.

---

## STATUS — recorded 2026-08-04 (paused here to work other tracks)

### Done and pushed

**Plan-32a (GIG home delivery) — COMPLETE, shipped dark.** All seven slices: client +
centroids (774/774), coverage sync (nightly), live quotes at checkout with flat-rate
fallback, GigShipment born at placement, the admin capture surface (verified with a live
browser-driven sandbox capture, waybill 1349113107), tracking poll + wallet monitor, and
the go-live runbook (`docs/runbooks/gig-golive.md`). Both option rows exist and are
INACTIVE until that runbook runs.

**Plan-32b slices 1–2 — done** (commits `88dbc0b`, `2dc8f9c`):
- `Address.latitude/longitude` (the pin, null = centroid fallback); `GigCentre` synced
  nightly (181 centres live); `nearest_centres` haversine helper; `carrier_service` on
  DeliveryOption; "Pickup at GIG Centre" seeded dark.
- Pickup quoting (`PickUpOptions=1`, priced to the centre, cached per centre) — live
  sandbox: pickup ₦3,899.27 vs door ₦4,175.20, genuinely cheaper. Pin overrides centroid
  for door delivery. `/api/v1/checkout/gig-centres/?address_id=` feeds the picker.

### Slice 3 — DONE 2026-08-11

Keys created by Hammed per `docs/runbooks/google-apis-setup.md` and live-verified.
Shipped: headless Places autocomplete on the street field (New Places JS classes,
session tokens, NG only, free text always valid), confirm-your-pin map (pin committed
only on a pick or a map interaction — an untouched centroid is never saved as a door),
LGA-mismatch nudge (prompt, never override; quiet when Google names an LGA we can't
price), in checkout AND the address book. Pin round-trips the address API
(`AddressSerializer` lat/long, both-or-neither rule, ±90/±180 bounds), rides the
placement snapshot, and the WAYBILL now ships snapshot-pin coordinates
(capture.py) with pair-wise centroid fallback. `RegionSerializer` exposes centroids
for the map prefill. CSP grew Google's Maps allowlist (report-only as before).
All Google traffic goes through the one seam `lib/googleMaps.ts`, mocked in tests.
Verified: 2,300 backend + 793+ storefront tests, lint/typecheck clean, and a REAL
browser walkthrough (Playwright, live Google key): suggestion pick saved door
coordinates for Allen Avenue; free text + hand-dropped pin saved clicked
coordinates near the Agege centroid; both cleaned up after.

### Slice 4 — DONE 2026-08-11

Shipped: the pickup option now opens a centre picker (nearest-first from
`/checkout/gig-centres/`, new BFF proxy) and cannot complete step 3 without a centre;
placement carries `gig_centre_id`, re-quotes the CHOSEN centre server-side
(`priced_options_for_address(pickup_centre=)` — free_over/omit-on-failure stay
single-sourced), and refuses with `centre_required`/`centre_invalid` (409) when the
picker was skipped or the centre died. `GigShipment.centre` snapshots
{id, station_id, name, address} at placement (migration 0012, ruling 4). QuoteView
accepts `gig_centre_id` so the review totals price the same centre and
`expected_total` can't mismatch. The confirmation email switches "Delivering to" →
"Collect from <centre> … bring your order number and a photo ID" (ruling 6, placement
half; shipped-email flavour is slice 5); `OrderSerializer.pickup_centre` + the account
order page show the same. Verified: pickup E2E tests incl. near/far re-quote proof and
the email copy switch; full suites green. Still dark: the option row stays inactive
until the go-live runbook flips it.

### Task 0 + slices 5–6 — DONE 2026-08-11 (PLAN COMPLETE except go-live itself)

**Task 0 answered by sandbox probe** (research §2g): the pickup capture field is
`ReceiverDetails.DestinationServiceCenterId` — every other placement, and PickUpOptions
in any spelling, is a Joi 400. The tracked shipment then reads
`PickupOptions: "SERVICECENTER"`. **GIG does not validate the id** (999999 minted a
waybill) — our placement validation + snapshot are the only fence, so capture refuses
malformed snapshots (`centre_snapshot_invalid` / `centre_coordinates_missing`) and
never falls back to door.

**Slice 5 shipped**: pickup-aware capture (snapshot coords → ReceiverLocation, centre
address as receiver address, region/centroid not needed — pickup-only LGAs can't be
blocked by door mapping), snapshot now carries centre coordinates, shipped email says
"Collect from" (same block as confirmation; ruling 6 complete), admin panel + GigPanel
show the centre with a routing warning. **E2E verified against the LIVE sandbox through
the real capture code**: waybill 1349113400, tracked as SERVICECENTER, ₦3,136.76
(dev-DB artifact order TC-TASK0E2E kept, like TC-GIGLIVE1).

**Slice 6 shipped**: go-live runbook step 8 now flips BOTH rows with a production
pickup price-check + centre-sync precondition; UAT pickup scenarios recorded in the
runbook's Plan-26 section.

### Left to do

| # | Work | Gated on |
|---|---|---|
| 32a go-live | `docs/runbooks/gig-golive.md` steps 1–9 | Hammed: send the WhatsApp asks (final draft in chat 2026-08-03); GIG: production creds, webhook, Bike + pickup-hours confirmations; wallet funding |

### Loose ends worth remembering

- The 8 weightless variants (runbook step 1) — admin data entry, any time.
- Dev walkthrough account password was reset to `WalkThru!2026` during slice-5
  verification (owner-walk@tokecosmetics.local).
- Sandbox order `TC-GIGLIVE1` + waybills 1349113095/1349113107 exist in the dev DB for
  testing; the tracking poll runs against them harmlessly.
- Full backend suite last gated green at slice 6 of 32a (2,126); 32b slices 1–2 gated on
  the touched suites (156 delivery+checkout) — run the full suite before the next
  32b commit.
