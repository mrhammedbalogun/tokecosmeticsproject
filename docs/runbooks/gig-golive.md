# GIG go-live runbook (Plan-32a slice 7)

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
- [ ] **NEW 2026-08-11: `companyDetails/get` answers 401 "Company not found."** on
      production for `ECO078703` (login works). Ask GIG to fix the company record — until
      then the wallet balance is invisible to us: the low-balance monitor cannot arm and
      the capture pre-check degrades to "unknown" (capture still works; GIG's own
      insufficient-balance refusal is the fence).

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

## 4. Production data pass

- [ ] `manage.py load_lga_centroids` — idempotent; fills any LGAs seeded since.
- [ ] `manage.py sync_gig_coverage` — **against the production base URL**. This answers
      the open coverage question (the dev disputed the sandbox's 103 home-delivery LGAs):
      whatever production returns IS the coverage. Read the unmatched report; map any
      real-LGA stragglers in admin (GigLga → region); ignore street-zone rows.
- [ ] Verify the beat schedule is live on the VPS (celery beat logs show
      `sync-gig-coverage`, `poll-gig-tracking`, `monitor-gig-wallet`).

### 4b. Register the tracking webhook (once, from the VPS)

```
manage.py register_gig_webhook https://<api host>/api/v1/webhooks/gig/
```

It prints the `secret` GIG issues; put it in `backend/.env` as `GIG_WEBHOOK_SECRET`
and set `GIG_WEBHOOK_API_BASE=https://prod-agilitythirdpartyapi.theagilitysystems.com`
(their docs' dev-→prod- convention — if registration 404s on that host, confirm the
production hostname with GIG), then restart. Until the secret is set the receiver
answers 503, which keeps GIG retrying rather than dropping events. The receiver is
authenticated by decryption: only a body encrypted with our secret is accepted.

## 5. Fund the wallet

Transfer with GIG per your arrangement. Then confirm the number the API sees:
`GET /companyDetails/get` should show the balance (the admin order panel displays it once
any GIG order exists). **If production also reports `WalletAmount: null`, tell GIG** —
the low-balance alert cannot protect a number the API won't report, and the capture-time
guard becomes the only fence.

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

## 7. One real end-to-end order (staff, small value)

Place a real order to a covered Lagos address choosing GIG, pay it, capture the waybill
from the admin panel. **This debits the production wallet and dispatches a real rider** —
treat it as the live payment tests in Plan-26: one deliberate, small, verified. Confirm:
rider arrives, tracking scans appear on the order page, the wallet dropped by exactly the
stored cost, the label appears.

## 8. Flip it on

Admin → Settings → Delivery options → activate `Door Delivery (GIG)` (rename to taste —
the name is customer-facing). Decide `free_over` policy (charges the customer ₦0 above
the threshold; GIG still debits the full cost — the shipment row stores both).

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
