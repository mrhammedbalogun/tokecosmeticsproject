# GIG Logistics API — integration research

**Date:** 2026-07-30
**Author:** Claude (research pass for Hammed)
**Source:** <https://gig-logistics.readme.io> — read in full via the site's AI index at
`https://gig-logistics.readme.io/llms.txt`; every reference page is fetchable with a `.md`
suffix. Docs last updated 2026-03-16.
**Scope:** Nigeria-only delivery. GIG delivers domestically for us; the international
endpoints are deliberately out of scope.

---

## 0. Decisions already taken (Hammed, 2026-07-30)

These are settled and shape everything below.

- **No cash on delivery.** The customer pays for goods and delivery together, upfront, at
  checkout. `IsCashOnDelivery` stays `false` and we build no COD reconciliation.
- **Getting parcels to GIG is arranged offline.** Either our team drops the day's orders at
  a nearby GIG centre, or GIG collects from the office. It is an operational agreement, not
  something the integration models.
- **Settlement is manual, weekly or biweekly.** We do not pay GIG per shipment through the
  API. What we *do* need is **reporting in our own admin**: total GIG shipment cost by day,
  week, month and year, with a breakdown we can check a GIG invoice against. See §6.
- **Support runs through an existing WhatsApp group** with the GIG developer, so no support
  or escalation process needs designing.

---

## 1. Summary

GIG's third-party API ("Agility Systems") covers everything we need for a Nigerian delivery
option: live rate quoting, shipment creation, printable waybill labels, and tracking. There
is no webhook — tracking is pull-only.

The decisive finding is that GIG exposes **two different shipment flows with very different
requirements**, and only one of them fits the address data we collect. See §3.

Our codebase is already shaped for this: `DeliveryOption.kind` has a `"carrier"` choice and
a `carrier_code` field commented `# "dhl", "gig" — Plan-32`
(`backend/apps/delivery/models.py:7-11`). Nothing implements it yet.

Two pages of the documentation are effectively blank — `/lga/active` and
`/homedelivery/active` both show `"data": {}` as their only example response. Those are
precisely the endpoints that determine how we map our 774 Nigerian LGAs onto GIG's network,
so they can only be resolved with live sandbox access.

---

## 2. The API surface

**Base URLs**

| Environment | URL |
|---|---|
| Development | `https://dev-thirdpartynode.theagilitysystems.com` |
| Production | `https://thirdpartynode.theagilitysystems.com` |

**Authentication.** `POST /login` with `{email, password}` returns a payload containing an
`access-token` (a JWT), plus `Id`, `UserName`, `CompanyType`, `SystemUserRole`. Every other
endpoint takes that JWT in an `access-token` **HTTP header**. No documented expiry and no
refresh endpoint.

**Response envelope.** Every endpoint returns the same shape — note it is double-nested,
which is easy to get wrong:

```json
{
  "success": true,
  "data": {
    "message": "Success",
    "apiId": "uuid-for-support-tickets",
    "status": 200,
    "data": { }
  }
}
```

Errors use the same envelope with `status` 400 / 401 / 500 and a message. The `apiId` is a
per-request trace ID and should be logged on every call — it is what GIG support will ask for.

### Endpoint inventory

| Group | Endpoint | Purpose |
|---|---|---|
| Auth | `POST /login` | Obtain `access-token` |
| Pricing | `POST /price` | Quote (v1, requires coordinates) |
| Pricing | `POST /price/v3` | Quote (v3, requires coordinates, breaks out VAT) |
| Pricing | `POST /price/bulk` | Bulk quote |
| Pricing | `POST /dropOff/price` | **Quote, no coordinates needed** |
| Pricing | `POST /dropOff/price/bulk` | Bulk drop-off quote |
| Create | `POST /capture/preshipment` | Create shipment (pickup flow) → returns `Waybill` |
| Create | `POST /capture/bulk/preshipment` | Bulk create |
| Create | `POST /create/dropOff` | **Create drop-off shipment** → returns `TempCode` |
| Create | `POST /create/dropOff/bulk` | Bulk drop-off create |
| Track | `GET /track/mobileShipment?Waybill=` | Full scan history |
| Track | `POST /track/multipleMobileShipment` | Batch tracking |
| Track | `GET /get/preshipment?Waybill=` | Shipment detail + status + label URL |
| Geography | `GET /localstations/get` | All Nigerian stations |
| Geography | `GET /serviceCentresByStation?StationId=` | Centres per station, with coordinates |
| Geography | `GET /lga/active` | Active LGAs (**docs example empty**) |
| Geography | `GET /homedelivery/active` | Active home-delivery areas (**docs example empty**) |
| Geography | `GET /country/get` | Country list |
| Account | `GET /companyDetails/get?Email=` | Merchant record: `CustomerCode`, `WalletAmount`, `Discount`, `SettlementPeriod`, bank details |
| Account | `PUT /chargeWallet` | Debit wallet — **for utility bills, not shipments** (see §7) |
| Labels | `POST /invoice/generate` | `{Waybill}` → waybill-label PDF URL (S3) |
| International | 5 endpoints | Out of scope |

---

## 2b. AMENDED 2026-07-31 — GIG's engineer disagreed, and was right

We sent the questions. The reply was three sentences and answered none of them:

> "before I respond I would advise you study the capture preshipping endpoints, that would
> help us navigate these areas and help provide clarity to all the concerns you have"

Reading `/capture/preshipment` properly shows why. **It dissolves three of the four
blockers** §3 below was built to work around:

| blocker (§7, and the questions doc) | under `/capture/preshipment` |
|---|---|
| `create/dropOff` returns a `TempCode`, not a `Waybill` | **Gone.** This returns `{"Waybill": …}` directly, so tracking and labels work. |
| Mapping 774 LGAs onto `ReceiverStationId` | **Gone.** `ReceiverStationId` is **optional**; GIG resolves the station from the coordinates. |
| Knowing an address is deliverable before quoting | **Largely gone.** `/price/v3` either prices the coordinates or refuses them. |
| `/lga/active` and `/homedelivery/active` are blank in the docs | Mostly moot — they exist to build a mapping we would no longer need. |

**So the recommendation in §3 is withdrawn.** It optimised for avoiding coordinates and in
doing so chose the flow with no working waybill story. That was the wrong trade, and their
engineer identified it in one sentence.

**What the coordinate flow costs instead**, and it is not small:

1. `Address` gains `latitude` / `longitude` — a migration.
2. **Checkout may have to geocode** — and may not; see the withdrawn timing argument below.
   We collect country → state → LGA → street text and no coordinates. If door-level accuracy
   is required this means Places autocomplete or server-side geocoding, both billed per
   lookup and both changing Plan-14's deployed checkout. If LGA-level accuracy suffices it
   means a static lookup table and no checkout change at all. **GIG's answer decides which,
   so nothing here is built yet.**
3. Pricing becomes **distance-based between two points** rather than flat per LGA — more
   accurate, less predictable.
4. `VehicleType` becomes required, so somebody must choose a default for a cosmetics parcel.

**~~The timing argument, and it is the strongest thing in this document.~~ WITHDRAWN
2026-07-31 after a Fable review, which was right.** The original ran: production holds 2
users, 1 address and 1 order, so adding coordinate columns now is free and doing it after
Plan-22 imports thousands of legacy addresses is expensive — "cheapest today and gets worse
monotonically."

**It conflates two different costs, and neither behaves that way.**

- **Adding two nullable columns costs the same at 1 row or 10,000.** A nullable column with
  no default does not rewrite a Postgres table. There is no monotonic anything.
- **Backfilling coordinates is the expensive half, and that cost is identical whenever the
  columns land.** Worse, it may not be owed at all: Plan-22's legacy addresses are
  *historical*. Only an address used at a FUTURE checkout needs coordinates, and that one can
  be geocoded when it is used.

**And it may collapse entirely.** Question 3 of `docs/gig-reply-capture-preshipment.md` asks
what precision GIG needs. If an LGA-level centre point prices correctly, the whole thing is a
**static 774-row LGA → centroid table computed once** — no Places autocomplete, no per-lookup
billing, no checkout change. Building geocoding before that answer arrives would be building
plumbing for a requirement that may resolve to a lookup table.

**Revised position:** add the nullable `latitude`/`longitude` columns whenever convenient —
a five-minute migration, harmless either way — and build **no geocoding at all** until GIG
answers questions 2 and 3.

**Still open, and it decides the size of the build:** whether a shipment can be priced and
created from a structured address — `ReceiverStationId` plus `DestinationServiceCenterId`,
omitting `ReceiverLocation` — or whether coordinates are truly mandatory. That is question 2
of `docs/gig-reply-capture-preshipment.md`.

---

## 3. The two flows — original analysis, superseded by §2b

### Flow A — PreShipment Mobile (GIG collects from us)

`POST /price` or `POST /price/v3` → `POST /capture/preshipment`

Requires `SenderLocation` **and** `ReceiverLocation` as `{Latitude, Longitude}` — mandatory
on both the quote and the capture.

### Flow B — DropOff (we take parcels to a GIG service centre)

`POST /dropOff/price` → `POST /create/dropOff`

Requires **no coordinates at all**. Only `SenderStationId`, `ReceiverStationId`,
`DestinationServiceCenterId`, `DeliveryType`, `PickUpOptions` and the item list.

### Why this matters

Our `Address` model has **no latitude or longitude** (`backend/apps/accounts/models.py:275`
— `line1`, `line2`, `country_code`, `state_region`, `area_region`, `city_text`,
`state_text`, `postcode`, and nothing else). Adopting Flow A would mean:

- new lat/long fields and a migration on `Address`,
- a Google Places-style geocoded address picker rebuilt into checkout **and** the account
  address book **and** admin,
- an ongoing third-party geocoding bill,
- and a fallback story for every one of the addresses we migrate that cannot be geocoded.

**Recommendation: Flow B (DropOff).** It maps directly onto the structured
country → state → LGA address we already collect and validate.

### A naming trap worth spelling out

`PickUpOptions` describes how the **receiver** gets the parcel, not how we hand it over:

- `0` = HomeDelivery — GIG delivers to the customer's door
- `1` = ServiceCentre — the customer collects from a GIG centre

So **DropOff + `PickUpOptions=0`** means: we drop parcels at a GIG centre, GIG delivers to
the customer's address. That is the standard e-commerce arrangement, and it needs no
coordinates from anyone.

---

## 4. What we can build

1. **Live GIG rates at checkout.** `POST /dropOff/price` per Nigerian address, priced on
   real cart weight.
2. **Two customer-facing options from one integration.** Home delivery (`PickUpOptions=0`)
   and centre collection (`PickUpOptions=1`) are the same call with one flag flipped.
   Centre collection needs a picker fed by `GET /serviceCentresByStation`, which returns
   name, code, street address and coordinates per centre. Nigerian customers use centre
   collection heavily and it is usually cheaper.
3. **Automatic waybill creation** on payment confirmation via `POST /create/dropOff`.
4. **Printable labels** via `POST /invoice/generate` → a PDF URL on S3.
5. **Tracking** via `GET /track/mobileShipment`, which returns a scan history with `Status`
   codes (`MAHD`, `DLP`, `CRT` are the documented examples), `ScanStatusIncident`,
   `ScanStatusReason`, `ScanStatusComment`, WAT and UTC timestamps, and location. Enough to
   drive a customer-facing tracking panel and shipment emails.
6. **Admin cost reporting.** Every quote we accept and every shipment we create is money we
   will owe GIG at settlement. Storing the quoted breakdown per order gives us
   cost-by-period reporting in admin, which is what the manual weekly/biweekly settlement
   needs. See §6.

**Deliberately not built: cash on delivery.** Both create endpoints accept
`IsCashOnDelivery` and `CashOnDeliveryAmount`, but the decision is that customers pay
upfront (§0). We send `IsCashOnDelivery: false` and skip COD reconciliation entirely.

**Not available: no webhook.** Nothing in this documentation pushes status to us, so
tracking means a scheduled Celery poll. GIG's public marketing site mentions a webhook; this
third-party API does not expose one. Worth asking.

---

## 5. Our data readiness (measured in production, 2026-07-30)

| | |
|---|---|
| Product variants | 122 |
| Variants with a usable weight | **114** |
| Variants with no weight | **8** |
| Weight range | 25 g – 3,850 g, median 292 g |
| Variant dimensions (L/W/H) | **none — the field does not exist** |
| NG states seeded (`core.Region`) | 37 |
| NG LGAs seeded (`core.Region`) | 774 |
| Existing NG delivery options | Lagos Delivery ₦1,500; Nationwide Delivery ₦3,500 (both flat, `kind="manual"`) |

No dimensions means `IsVolumetric: false` and weight-only pricing. Acceptable for
cosmetics, but it forfeits any volumetric discount and may under-price bulky-but-light
items (the gift boxes especially).

**The 8 variants with no weight** — these will mis-price until fixed:

- `0.266` — Toke carrot shea butter
- `TC-WP-4123` — Toke Hair Grow Oil
- `TC-WP-2797` — Toke Daily Hydrating & Brightening Facial Wash
- `TC-WP-2812` — Toke Kids Shampoo
- `TC-WP-4013` — Nourishing & Grow Rinse Off Conditioner
- `TC-WP-4024` — 8 OZ White Plastic Bottle
- `TC-WP-7979` — Glow Gift Box (Customizable)
- `TC-WP-12251` — Men's Essential Skincare Set

---

## 6. Impact on our codebase

**`backend/apps/delivery/services.py` is pure and synchronous.** Its docstring says
"no HTTP", and `options_for_address()` is called from three places:
`checkout/views.py:57`, `checkout/views.py:75`, and
`checkout/services/checkout.py:93`. Introducing a live carrier call there requires:

- a quote cache keyed on (address, weight bucket) so we do not hit GIG on every cart render,
- an explicit timeout,
- and a documented fallback when GIG is unreachable. A checkout that hard-fails because a
  carrier API is slow is worse than one that falls back to a flat rate.

**LGA → GIG station mapping.** We have 37 states and 774 LGAs; GIG has its own station list
and its own active-LGA list. Nothing joins them. This is the bulk of the data work and
cannot be scoped until `/lga/active` returns something we can see.

**`Order` needs new fields:** waybill (or `TempCode`), the GIG price breakdown as stored at
quote time, the label URL, and the last known tracking status plus its timestamp.

**Admin cost reporting (new scope, from §0).** Because settlement with GIG is manual and
periodic, we owe ourselves a report showing what we owe. Storing the full quoted breakdown
per order — not just the total we charged the customer — lets admin answer "what did GIG
cost us this day / week / month / year", broken down enough to check against their invoice.
Two things follow:

- Store the **cost to us** and the **price charged to the customer** as separate figures. If
  we ever mark delivery up, or absorb part of it, one number cannot represent both — and at
  settlement time the difference is exactly what we need to see.
- This is a natural fit for **Plan-20** (`apps/analytics/`, dashboard and reports), which is
  not yet built. The GIG work should store the data in a shape Plan-20 can aggregate, rather
  than building a one-off report screen that later has to be rewritten.

**Existing manual options.** Decide whether GIG replaces Lagos/Nationwide or sits alongside
them. Recommendation: keep them as the unreachable-API fallback.

---

## 7. Risks and unknowns

### The `/price/v3` response does not reconcile arithmetically

Documented example:

```json
{
  "GrandTotal": 417960,
  "DeliveryOptionPrice": 100,
  "DeliveryPrice": 388800,
  "Vat": 29160,
  "Discount": 7776,
  "InsurancePrice": 7776,
  "SurchargeFee": 200
}
```

`388800 + 29160 = 417960` exactly — so `GrandTotal` appears to be `DeliveryPrice + Vat`
alone, with insurance, surcharge, the option price and the discount **not** summed in. We
must treat `GrandTotal` as authoritative and never recompute it from its parts. This has to
be confirmed against live sandbox calls before we charge a customer.

### `/create/dropOff` returns a `TempCode`, not a waybill

`POST /capture/preshipment` returns `{"Waybill": "1349107274"}`, but `POST /create/dropOff`
returns `{"TempCode": "PRE000568-APH"}`. Tracking (`/track/mobileShipment`) and label
generation (`/invoice/generate`) both take a **Waybill**. The documentation never explains
how a `TempCode` becomes a `Waybill`. This is a functional gap in the flow we intend to use.

### Settlement is manual — but the API may not know that

Settling weekly/biweekly by hand (§0) removes most of the billing complexity, but **one
technical risk survives it**: `GET /companyDetails/get` exposes `WalletAmount` alongside
`SettlementPeriod`, which suggests some accounts are prepaid. If ours needs a funded wallet
balance for `POST /create/dropOff` to succeed, then a zero balance means paid customer
orders silently fail to get a shipment — during checkout, after we have taken their money.

If that turns out to be the case we need a balance monitor that alerts us before the floor
is hit. This is question 20 to GIG. (`PUT /chargeWallet` is not the answer — its `BillType`
enum covers Class / TV / Airtime / Data / Electricity subscriptions. It is a utility-bill
endpoint, not a freight one.)

### Undocumented enums and identifiers

- `DeliveryType` (`0` | `1`) on the drop-off endpoints — meaning never stated.
- `ShipmentType` differs between endpoints: `/price/v3` documents `0=Special, 1=Regular,
  2=Ecommerce, 3=Store, 4=Haulage`, but `/dropOff/price` and `/create/dropOff` restrict it
  to `0 | 1`. We would expect to be `2 = Ecommerce`.
- `SpecialPackageId` is referenced by four endpoints; no endpoint lists the packages.
- `CustomerCode` and `CustomerType` are required by `/price` v1 with no stated source
  (presumably `CustomerCode` from `/companyDetails/get`).
- `PricingStrategy` on `/capture/preshipment` — undocumented.

### Operational unknowns

No documented rate limits, no token lifetime, no sandbox test-data conventions, no
cancellation or returns endpoint, and no published list of tracking `Status` codes.

---

## 8. Recommendation and sequencing

This is **Plan-32** in `master-tokerebuild.md` (post-launch: "DHL + GIG Logistics APIs"),
being pulled forward. It is plan-sized in its own right — roughly comparable to Plan-08b —
and it modifies checkout, which is already built and deployed. It warrants its own design
spec rather than being appended to Plan-17a.

**Proposed order of work:**

1. Send GIG the questions in `docs/gig-questions-for-developer.md` (24 questions, four of
   them blocking) via the existing WhatsApp group.
2. Meanwhile, verify the credentials we already hold against
   `dev-thirdpartynode.theagilitysystems.com` and call `/lga/active`,
   `/homedelivery/active`, `/localstations/get` and `/dropOff/price` for real. Several of
   the questions may answer themselves.
3. Write the design spec against actual response shapes.
4. Implement.

**Cost of doing this now:** it pushes back Plan-17a, 17b/c and Plan-18. Plan-18 is the one
that makes bank transfer fulfillable — today a Nigerian customer can pay and never be
shipped. GIG makes delivery cheaper and automated; Plan-18 makes fulfilment possible at all.
If both are wanted before launch, GIG should still go second.
