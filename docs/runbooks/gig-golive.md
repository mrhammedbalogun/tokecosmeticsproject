# GIG go-live runbook (Plan-32a slice 7)

> **RUN 2026-08-13 (by Claude, on Hammed's go-ahead).** Steps 3, 4, 4b, 5, 6 and 8 are
> DONE — both GIG rows are ACTIVE in production and priced correctly in checkout
> (door ₦3,532.97 / pickup ₦3,747.85 for a 15k Ikeja test basket). Still open:
> **step 7** (staff E2E order — Hammed; this also confirms the rider collects from the
> right address) and the two flagged items below: the **sender pin** (set to Ogudu
> Mall; an Ikorodu-factory pin would price +85% — confirm parcels dispatch from Ogudu)
> and the **Cloudflare UA fence** on the webhook receiver (step 4b note).

Everything is built and shipped **dark**: the `Door Delivery (GIG)` option row is
`is_active=False`, so nothing customer-facing exists until step 8 flips it. Steps 1–5 are
safe to do any time; 6–8 are the cutover and take minutes. Sandbox base URL and creds
stay in place until this runbook runs.

The build's own verification trail: quote → checkout → placement snapshot → admin capture
(live sandbox waybill 1349113107, driven from the admin UI in a browser) → tracking poll
(label harvested) are all exercised against the sandbox; 2,126 backend / 759 storefront /
748 admin tests.

## 1. Product data — the 8 weightless variants (admin, any time)

Weight is currently ignored by GIG's pricing under 5 kg (measured), so these won't
misprice TODAY — but they are the only variants that would if GIG changes that, and the
DHL slice will need real weights regardless. Admin → Products:

`0.266` (carrot shea butter) · `TC-WP-4123` (Hair Grow Oil) · `TC-WP-2797` (Hydrating
Facial Wash) · `TC-WP-2812` (Kids Shampoo) · `TC-WP-4013` (Rinse Off Conditioner) ·
`TC-WP-4024` (8 OZ White Plastic Bottle) · `TC-WP-7979` (Glow Gift Box) ·
`TC-WP-12251` (Men's Essential Skincare Set)

## 2. Ask GIG for (WhatsApp, before cutover)

- [x] **Production API credentials** (email + password) and confirmation of the
      production base URL (`https://thirdpartynode.theagilitysystems.com`).
      **2026-08-10:** issued (`ECO078703` / `tokefactory1@gmail.com`, stored commented in
      dev `backend/.env`). **2026-08-11:** the Third Party Role is GRANTED — production
      `/login` succeeds and returns a token. Steps 3+ are unblocked.
- [x] **The tracking webhook** — GIG sent their Notion docs 2026-08-11; the receiver is
      built (`apps/delivery/gig/webhook.py`, `POST /api/v1/webhooks/gig/`) and the docs
      are mirrored in `docs/gigimplementationresearch.md` §2f. Registration is step 4b
      below. The 2h poll stays on as the fallback either way.
- [x] Confirm **Bike (VehicleType 1)** — confirmed 2026-08-11: the enum is
      `{Car: 0, Bike: 1, Van: 2, Truck: 3}`, matching what we measured and ship.
- [x] Confirm **rider pickup hours** — confirmed 2026-08-11: **the cutoff is 3 pm**;
      waybills created after it are pushed to the next day. Packing desk rule: capture
      before 3 pm for same-day rider dispatch.
- [ ] The **insufficient-balance error** shape from `capture/preshipment` (we pre-check
      the balance regardless; this only tightens the error copy).
- [x] ~~`companyDetails/get` answers 401 "Company not found."~~ **RESOLVED 2026-08-12 —
      it was our bug, not GIG's.** The lookup is case-sensitive against the stored
      record: `Email=tokefactory1@gmail.com` (lowercase) returns the full company
      record; the UPPERCASE casing GIG issued the creds in (and we stored) 401s.
      `wallet_balance()` now lowercases before asking (capture.py). Production record
      verified: CompanyId 113743, `WalletAmount: null` (wallet unfunded — see step 5).

## 3. Environment (backend/.env on the VPS, then restart)

```
GIG_BASE_URL=https://thirdpartynode.theagilitysystems.com
GIG_EMAIL=<production merchant email>
GIG_PASSWORD=<production password>
GIG_SENDER_NAME=Toke Cosmetics
GIG_SENDER_PHONE=<real office phone — GIG's validator REFUSES captures without it>
GIG_SENDER_ADDRESS=<real pickup address>
GIG_SENDER_LOCALITY=<neighbourhood, e.g. Gbagada>
GIG_SENDER_LATITUDE=<office latitude — every quote prices FROM here>
GIG_SENDER_LONGITUDE=<office longitude>
GIG_WALLET_ALERT_THRESHOLD=50000   # ₦; tune to a week of expected shipping
```

Get the coordinates by dropping a pin on the office in Google Maps (right-click → the
lat/long is first in the menu). Wrong sender coordinates mis-price EVERY quote.

**DONE 2026-08-13** (backup `.env.prod.bak-gig-golive-20260813-045733`): all vars set —
email lowercase, phone `+2347074800702` and address from GIG's own company record,
pin = the "Ogudu Mall" Google listing (6.5765217, 3.3893872). **OPEN QUESTION FOR
HAMMED**: the Toke Cosmetics Google listing itself sits in Ikorodu/Igbogbo
(6.5937412, 3.5680512) — quoting from there is **+85%** (₦6,526 vs ₦3,533 for the
same Ikeja parcel, measured). Quote and wallet-debit stay consistent either way (both
read the same setting), but the RIDER drives to this pin — if parcels actually
dispatch from the Ikorodu factory, edit the two coordinate lines + address, restart,
and quotes re-price within the 15-min cache. Step 7's rider arrival is the check.

## 4. Production data pass

- [x] `manage.py load_lga_centroids` — done 2026-08-11 (774/774).
- [x] `manage.py sync_gig_coverage` — **DONE 2026-08-13 against production**: 350
      active LGAs, **91 home-delivery** (production's real number; the sandbox's 103
      is history), 58 unmatched. Four unmatched rows were REAL LGAs and are now
      hand-mapped: LAGOS/Ifako/Ijaye→Ifako-Ijaiye (home delivery!), FCT/Municipal
      Area Coun→Municipal Area Council (home delivery!), Ogun Yewa North/South→Egbado
      North/South. The rest are street zones, ignored per this runbook.
- [x] Beat schedule verified live: `monitor-gig-wallet` 6h, `poll-gig-tracking` 2h,
      `sync-gig-coverage` + `sync-gig-centres` daily.
- [x] Centre sync — DONE 2026-08-13: 46 stations, **180 centres** created
      (`apps.delivery.gig.centres.sync_gig_centres()` — it is a beat task, not a
      management command).

### 4b. Register the tracking webhook (once, from the VPS)

**DONE 2026-08-13.** GIG answered with a secret for ECO078703 against
`https://api.tokecosmetics.com/api/v1/webhooks/gig/`; `GIG_WEBHOOK_SECRET` and
`GIG_WEBHOOK_API_BASE=https://prod-agilitythirdpartyapi.theagilitysystems.com` are in
the VPS `.env.prod`, containers restarted. **Receiver verified end-to-end**: a test
event encrypted with the real secret → HTTP 200 `Webhook received successfully`
(unknown waybills are safely ignored). Until the secret is set the receiver answers
503, which keeps GIG retrying rather than dropping events; the receiver is
authenticated by decryption — only a body encrypted with our secret is accepted.

Two measured facts GIG's docs never said:

- **Auth**: `add-webhook-user` REJECTS the third-party node JWT (401 in every header
  spelling). The webhook host is its own "Third Party API v1" service with
  `POST /api/ThirdParty/login` (`{username, password}`, same creds) → `data.token` →
  standard `Authorization: Bearer`. `register_gig_webhook` now does this (fixed
  2026-08-13); the swagger at `{GIG_WEBHOOK_API_BASE}/swagger/v1/swagger.json` is the
  reference (it also reveals `POST /api/ThirdParty/cancelshipment/{waybill}` — worth
  a future ask, the main docs claim cancellation doesn't exist).
- **Cloudflare UA fence**: api.tokecosmetics.com is Cloudflare-proxied and 403s SOME
  non-browser User-Agents (measured: `Python-urllib` blocked; empty UA and browser
  UAs pass). GIG's .NET sender most likely passes (default HttpClient sends no UA),
  but if webhook events never arrive, add a Cloudflare WAF skip rule for
  `POST /api/v1/webhooks/gig/` — safe, the receiver authenticates by decryption.
  The 2h poll is the fallback either way.

## 5. Fund the wallet

**DONE 2026-08-12: wallet funded ₦50,000 — and `WalletAmount` still reads `null`**
(re-measured after funding; the API never surfaces the balance for this account, and
there is no other wallet-read endpoint). Decision: **manual monitoring** — reconcile
the funded amount against `GigShipment.cost` rows (§9); the low-balance email will
never fire and the capture-time guard (GIG's own insufficient-balance refusal) is the
only automated fence.

## 6. Production smoke (one real quote, no waybill)

With prod creds in place but the option still dark, run from the VPS:

```
manage.py shell -c "
from decimal import Decimal
from collections import namedtuple
from apps.core.models import Country, Region
from apps.delivery.gig.quotes import quote_home_delivery
FakeVariant = namedtuple('F','weight_grams')
ikeja = Region.objects.get(country_code='NG', level='area', name='Ikeja', parent__name='Lagos')
class A: country_code='NG'; state_region=ikeja.parent; area_region=ikeja
print(quote_home_delivery(A(), 500, Decimal('15000')))"
```

Sanity-check the price against what you actually pay GIG today. This is where a wrong
sender coordinate or a production tariff surprise shows up — before any customer sees it.

**DONE 2026-08-13**: home 500g/₦15k to Ikeja = **₦3,532.97** (GrandTotal; includes a
20% rank discount and ₦1,000 SurchargeFee, VAT 0 on home delivery) — sane against the
sandbox's ₦4,175 for the same parcel.

## 7. One real end-to-end order (staff, small value)

**STILL OPEN — the one remaining runbook step, on Hammed.**

Place a real order to a covered Lagos address choosing GIG, pay it, capture the waybill
from the admin panel. **This debits the production wallet and dispatches a real rider** —
treat it as the live payment tests in Plan-26: one deliberate, small, verified. Confirm:
rider arrives (**at the Ogudu Mall shop — this validates the sender pin, see step 3**),
tracking scans appear on the order page, the wallet dropped by exactly the stored cost
(read it off the shipment row — the API reports no balance), the label appears.

## 8. Flip it on — BOTH rows (32b slice 6 addendum)

**DONE 2026-08-13**: rows 7 (`Door Delivery (GIG)`) and 8 (`Pickup at GIG Centre`)
are `is_active=True`; checkout for an Ikeja address offers Lagos Delivery ₦1,500 /
GIG door ₦3,532.97 / GIG pickup ₦3,747.85 (nearest centre) / Nationwide ₦3,500.
`free_over` left unset on both (customers pay the quoted price) — set per row in
admin if wanted. Pickup price-check done: Ikeja centre **₦3,807.86**, i.e. production
prices pickup slightly ABOVE door (₦3,533) — the REVERSE of the sandbox's ordering
(₦3,899 vs ₦4,175). Not a blocker (customers see honest prices), just reality.

Admin → Settings → Delivery options → activate **`Door Delivery (GIG)`** AND
**`Pickup at GIG Centre`** (rename to taste — the names are customer-facing). Decide
`free_over` policy per row (charges the customer ₦0 above the threshold; GIG still
debits the full cost — the shipment row stores both).

Keep **Lagos Delivery / Nationwide Delivery active** — they are the fallback when GIG is
down or an LGA is uncovered, by design.

## 9. First-week watch

- [ ] Wallet balance vs `GigShipment.cost` rows (the reconciliation trail).
- [ ] `create_unconfirmed` shipments (admin panel warns; resolve each WITH GIG before
      any retry — a blind retry can pay twice and dispatch two riders).
- [ ] Unknown scan codes in the logs (`gig scan code`): send them to GIG for meanings,
      then extend `tracking.STATUS` maps.
- [ ] Quote cache hit rate vs GIG latency if checkout feels slow (`gig /price/v3` log
      lines; the budget is 3 s and failures only cost the option, never the checkout).

## Plan-26 UAT additions

Add to `docs/uat-checklist.md`: covered-LGA checkout shows GIG priced beside the flat
options; uncovered-LGA checkout shows flat options only; GIG-down (unplug `GIG_BASE_URL`)
checkout still completes on a flat option; admin capture → wallet debit → rider; customer
order page shows scans; wallet below threshold → one email, none while it stays low.

**Pickup scenarios (32b slice 6):**
- Pickup-only LGA (active, no home delivery): checkout offers Pickup but NOT GIG door.
- Clicking Pickup opens the centre picker (nearest first); the step cannot complete
  without a centre; switching to a door option clears the centre.
- Review totals re-price to the CHOSEN centre (pick the far one — the number changes).
- Placement snapshots the centre; confirmation email says "Collect from <centre>" with
  order number + photo-ID line and NO "Delivering to"; order page shows the centre.
- Admin order panel shows the pickup centre; capture creates a waybill that GIG tracks
  with `PickupOptions: SERVICECENTER` (verified on sandbox waybill 1349113400 through
  the real capture code, 2026-08-11).
- Address rebuild: a Places-pick address saves a pin; a free-text address with a
  hand-dropped pin saves it; a no-pin checkout still completes (centroid fallback).
- Centre-vanishes case: deactivate a centre after placement — the order page and
  emails still name it (snapshot), and a NEW checkout no longer offers it.
