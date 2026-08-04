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
