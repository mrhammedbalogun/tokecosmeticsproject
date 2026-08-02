# Plan-32a — GIG Logistics for Nigerian shoppers

Pulled forward from Plan-32 ("post-launch: DHL + GIG"). NG-only, `capture/preshipment`
(pickup) flow only. Grounded in `docs/gigimplementationresearch.md` §2c–§2d — every claim
below about GIG's behaviour was **measured on the sandbox on 2026-08-02**, not read from
their docs, which §2d shows to be wrong in at least four load-bearing places.

## What is settled (do not re-litigate)

| Decision | Source |
|---|---|
| GIG **picks up from the office**; drop-off flow, TempCode, `create/dropOff` are dead | Toke team, 2026-08-02 |
| Coordinates are mandatory and come from a **static LGA→centroid table** — no checkout geocoding, no per-lookup billing | Measured: centroid-vs-street spread ≤ ~3% intra-city, 0% inter-state |
| Wallet is debited the full quoted `GrandTotal` **at waybill creation** | GIG dev, second reply |
| Creating a waybill **summons a rider immediately** | GIG dev, second reply |
| `ShipmentType=1`, `IsCashOnDelivery=false`, `IsVolumetric=false`, VehicleType default **1 (Bike)** (pending casual confirm) | Measured / §0 |
| `GrandTotal` is authoritative, never recomputed from parts | Measured twice |
| No cancel/amend API exists | GIG dev, first reply |
| Tracking is **poll now, webhook at go-live** | GIG dev |

## Open with GIG — gates go-live, not the build

1. Production home-delivery coverage list (dev disputed the sandbox's 103 LGAs).
2. Error shape of `capture/preshipment` on insufficient balance (we pre-check regardless).
3. Bike default + rider pickup hours (operational).

---

## Design rulings

### 1. A waybill is a debit and a rider — so creation is an admin act, never a hook

The wallet loses the full `GrandTotal` and a rider starts moving the moment the call
succeeds, and there is no cancel API. Therefore waybill creation is a **button on the
admin order detail** (`orders.manage`, audited), pressed when the parcel is packed —
never a payment-confirmation side effect. The button double-guards: order must be
`processing`, and a live wallet-balance check must cover the stored cost, with a clear
"fund the wallet" refusal otherwise.

**Corollary — no automatic retry on timeout.** Idempotency of `capture/preshipment` is
unknown; a timed-out call that actually succeeded would, on retry, debit the wallet twice
and dispatch two riders. A timeout leaves the shipment in `create_unconfirmed` and shows
admin a "check with GIG before retrying" state (the `apiId` we logged is their lookup key).

### 2. The GIG option appears only where we know it works, and checkout never waits on GIG

`options_for_address` stays pure (its docstring is a contract). A thin
`delivery/carriers.py` layer decorates its result: for a `kind="carrier",
carrier_code="gig"` option on an NG order it resolves the address's LGA →
(a) LGA is in the synced home-delivery coverage set, (b) LGA has a centroid, (c) a quote
is obtainable — cached (Redis, key = LGA region id + ceil(kg) bucket, TTL 6h) or live
within a **3-second budget**. Any of the three failing means the GIG option is simply
**omitted** and the existing flat-rate manual options carry the checkout. GIG being down
must never block an order; it may only make delivery cost ₦3,500 flat instead of a live
₦2,900.

Price charged to the customer = quoted `GrandTotal`, quantized. No markup in 32a — but
cost and charged are stored as **separate figures** from day one (research §6), so a
markup later is a pricing change, not a schema change.

### 3. Coordinates live on `core.Region`; coverage lives in its own synced table

- `Region` gains nullable `latitude`/`longitude`, loaded once by a management command
  from a bundled public LGA-centroid dataset (source recorded in the command's docstring).
  Nullable is honest: a Region without a centroid simply never offers GIG.
- `GigLga` (name, state, home_delivery, `region` nullable FK, synced_at) is refreshed by
  a nightly Celery beat task sweeping `/lga/active` + `/homedelivery/active` per StateId
  (the only filter the validator allows). Rows auto-match to `Region` by normalized name
  (casefold, strip hyphens/spaces); the FK is editable so a human can fix the tail. A
  management command prints the unmatched report — same philosophy as the
  unpriced-per-market checklist: nothing is invisibly lost.
- Production coverage supersedes sandbox numbers at go-live by pointing the same sync at
  the production base URL. Nothing else changes.

### 4. One `GigShipment` row is the whole story, and Plan-20 can aggregate it

Created **at order placement** (status `quoted`) whenever a GIG option was chosen,
holding the full quote breakdown; enriched at capture (waybill, `apiId`, debited cost);
advanced by the tracking poll. One table answers "what did GIG cost us this week" for the
Plan-20 reports layer, and its rows are the wallet-reconciliation trail.

```
GigShipment
  order            OneToOne(orders.Order, PROTECT, related_name="gig_shipment")
  status           quoted → created → in_transit → delivered
                   + create_unconfirmed (timeout limbo — ruling 1)
                   + abandoned (order cancelled before capture; terminal, costs nothing)
  quote            JSONField   # full /price/v3 breakdown at checkout time
  cost             Decimal null   # what the wallet lost, set at capture (= quote GrandTotal today)
  charged          Decimal        # what the customer paid us (= Order.shipping_total)
  waybill          CharField blank
  capture_api_id   CharField blank   # GIG support's lookup key
  label_url        URLField blank
  last_scan        JSONField default=dict   # newest raw tracking entry, verbatim
  last_tracked_at  DateTimeField null
```

Existing `Order.tracking_carrier`/`tracking_number` are set to `"GIG"`/waybill at capture
so every surface that already renders tracking keeps working without knowing GIG exists.

### 5. GIG's status vocabulary is unpublished, so the mapping must be openly incomplete

We observed `MCRT`; docs name `MAHD`, `DLP`, `CRT`; the dev described an `Assigned`
stage. A small explicit map drives our transitions (`DLP` → `delivered` +
order `shipped→delivered`; first non-`MCRT` scan → `in_transit` + order
`processing→shipped` via the existing state machine, which also fires the shipped email).
**Unknown codes update `last_scan`, are logged, and change nothing else.** The customer
order page renders the raw scan history verbatim — truthful even when our map is behind.
Poll: beat task every 2h over non-terminal shipments with waybills, batched through
`/track/multipleMobileShipment`.

### 6. The wallet monitor is the difference between an alert and a stuck order desk

Debit-at-creation plus prepaid wallet means an empty wallet halts fulfilment, not
checkout — visible only when someone is standing at the packing bench. So: beat task
(6h) reads `WalletAmount` from `/companyDetails/get`, caches it, emails admins below
`GIG_WALLET_ALERT_THRESHOLD`; the order-detail shipment panel always shows the cached
balance next to the create button; the capture endpoint re-checks live. Sandbox
`WalletAmount` is null — the monitor treats null as "unknown", shows it as such, and
does not block capture on it (the live pre-check at capture is the guard that matters).

### 7. The client copies the payments-gateway housekeeping, plus three GIG-specific rules

`apps/delivery/gig/client.py`, httpx via the same discipline as
`payments/gateways/_http.py`. GIG-specific, all measured: (a) send a real `User-Agent` —
the WAF 403s library defaults; (b) the envelope is **single**-nested `{message, apiId,
status, data}`; (c) log the `apiId` of every call. Token: JWT of unknown lifetime →
cache in Redis, one re-login retry on 401, **except no retry of any kind on capture**
(ruling 1). Secrets: `GIG_EMAIL`/`GIG_PASSWORD` from env only.

### 8. Deferred out of 32a, deliberately

- **Service-centre pickup** (`PickUpOptions=1`) — needs a centre-picker UI in checkout
  and centre-address handling in fulfilment. Real demand (Nigerians use it heavily), its
  own slice: 32b.
- **Webhook receiver** — GIG provides it at go-live; the poll is the foundation anyway.
- **Markup on delivery** — schema-ready (cost vs charged), policy later.
- **DHL** — Plan-32c, on the same `carriers.py` seam.
- **Label printing UX** — 32a exposes "fetch label" (retrying politely on GIG's
  "not found until station-processed" behaviour); print-batch workflows wait for real
  ops feedback.

---

## Tasks

1. **Client + centroids.** `delivery/gig/client.py` (+ Redis token cache), `Region`
   lat/long migration, `load_lga_centroids` command with bundled dataset,
   `GIG_*` env keys in the Appendix-A env table and `.env.example`s.
   *Verify:* client tests against recorded single-nested envelopes incl. WAF-UA and
   401-relogin cases; command loads ≥ 700 centroids; spot-check 5 LGAs against a map.
2. **Coverage sync.** `GigLga` model, nightly beat sweep, name matcher, unmatched
   report command. *Verify:* live sandbox sync lands 303/103; matcher report shows the
   unmatched tail; re-run is idempotent.
3. **Quote layer + checkout.** `delivery/carriers.py` decoration, Redis quote cache,
   3s budget, omit-on-failure; seed the `DeliveryOption` row (`kind="carrier"`,
   `carrier_code="gig"`, NG, **inactive**). *Verify:* existing checkout tests untouched
   and green; new tests for covered-LGA quote, uncovered-LGA omission, GIG-timeout
   omission; live sandbox quote for an Ikeja address appears in the cart API with the
   manual options still listed.
4. **`GigShipment` + placement.** Model, placement hook (GIG option chosen → `quoted`
   row with breakdown), order-cancellation hook (`quoted` → `abandoned`).
   *Verify:* placement snapshot test; cancelled-before-capture test.
5. **Fulfilment surface.** Capture + fetch-label + shipment-panel endpoints under
   `/api/v1/admin/` (declared in `ADMIN_SURFACE`, `orders.manage`, write-audited);
   wallet pre-check; `create_unconfirmed` on timeout; admin order-detail panel with
   balance, create button, label button, scan history. *Verify:* the four guard suites
   pass (undeclared-endpoint tripwire); tests for insufficient-balance refusal, timeout
   limbo, double-click idempotency on our side; **one live sandbox capture driven from
   the admin UI in a browser**.
6. **Tracking poll + wallet monitor.** Both beat tasks, status map + unknown-code
   logging, `processing→shipped→delivered` transitions with existing emails, threshold
   alert email, storefront order page shows scan history. *Verify:* transition tests per
   mapped code; unknown-code no-op test; beat-schedule audit test picks up both tasks;
   sandbox waybill `1349113095` polls without error.
7. **Ops + go-live checklist** (`docs/runbooks/gig-golive.md`): the 8 weightless
   variants get weights (admin); real office coordinates + sender fields into env;
   production creds; coverage re-sync against prod; wallet funded + threshold set;
   activate the DeliveryOption row; webhook request to GIG; UAT scenario added to
   Plan-26's script.

Slices 1–4 are backend-only and parallel-safe with anything; 5 depends on 4; 6 on 5.
The option row stays **inactive until the go-live checklist** — everything before that
ships dark and testable.
