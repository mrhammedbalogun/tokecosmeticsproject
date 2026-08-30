# Plan-44 — Ad pixels and Conversions APIs (Meta, TikTok, Snapchat, Google)

**Status: BUILT 2026-08-29, ships DARK.** Every channel is seeded DISABLED with no
pixel id, so nothing loads and nothing is sent until Hammed fills the Advert tracking
screen in. Backend + storefront + admin complete; 102 new backend tests and 56 new
storefront tests green. **No vendor API has been exercised with real
credentials** — none of the four can be, without a live ad account. §8 is the go-live
runbook and the "Send test event" button is what proves each one.

Hammed's brief: "We need to run ads on all major social
media accounts. So, we need to properly implement their pixel or conversion api in some
of them. Especially for Facebook, Instagram, TikTok, and Snapchat."

Decisions taken with Hammed on 2026-08-29, before any code:

- **All four channels**, plus Google Ads + GA4 (he added Google to the brief).
- **Build the consent banner now**, not as a fast-follow.
- **Native code in the repo**, not Google Tag Manager.

## 0. The correction that shrinks the work

**Instagram is not a separate integration.** Meta Pixel + Meta Conversions API serve one
*dataset*, and that dataset is what both Facebook and Instagram ads optimise against.
There is no Instagram pixel to install. So the brief's four platforms are three
integrations, and Hammed's addition makes it four:

| Channel | Browser tag | Server-side | Click id |
|---|---|---|---|
| Meta (Facebook + **Instagram**) | Meta Pixel `fbq` | Conversions API | `fbclid` → `_fbc`; `_fbp` |
| TikTok | TikTok Pixel `ttq` | Events API 2.0 | `ttclid`; `_ttp` |
| Snapchat | Snap Pixel `snaptr` | Conversions API v3 | `ScCid`; `_scid` |
| Google Ads + GA4 | `gtag.js` | GA4 Measurement Protocol | `gclid`, `wbraid`, `gbraid` |

## 1. Measured facts (verified against vendor docs 2026-08-29)

Everything here was read from the vendor's own documentation on the day of writing, not
recalled. Where a version number appears it is **pinned in settings and overridable**,
because all four vendors version independently of us.

**Meta Conversions API.**
`POST https://graph.facebook.com/{version}/{dataset_id}/events?access_token={token}`.
Body `{"data": [event...], "test_event_code": "TEST123"}`. Per event: `event_name`,
`event_time` (Unix **seconds**, accepted up to 7 days late — which is why a retry queue
is safe), `event_id`, `event_source_url`, `action_source` (`website`), `user_data`,
`custom_data`, `opt_out`. **Hashed (SHA-256):** `em, ph, fn, ln, ct, st, zp, country,
external_id` — and each is an *array*. **Raw, never hashed:** `client_ip_address`,
`client_user_agent`, `fbc`, `fbp`. `custom_data`: `value` (number), `currency`,
`content_ids`, `content_type`, `contents[]`, `order_id`. Latest Graph version seen is
v26.0; docs example v25.0. **Default `META_GRAPH_API_VERSION=v25.0`** — a version Meta
documents today, changeable by env without a deploy of code.

**TikTok Events API 2.0.**
`POST https://business-api.tiktok.com/open_api/v1.3/event/track/`, header
`Access-Token`. Body: `event_source: "web"`, `event_source_id` (pixel id),
`test_event_code`, `data: [...]`. Per event: `event`, `event_time` (Unix seconds),
`event_id`, `user{}`, `page{url, referrer}`, `properties{}`. **Hashed:** `email`,
`phone` (E.164), `external_id`. **Raw:** `ttclid`, `ttp`, `ip`, `user_agent`. Standard
web events: `ViewContent`, `AddToCart`, `InitiateCheckout`, `PlaceAnOrder`,
`CompletePayment`. `page.url` is required for web events.

**NOTE — v1.2 is a trap.** Most blog examples still show the old shape
(`pixel_code`, `context{user{}}`, `timestamp` as an ISO string). That is Events API
**1.0/1.2** and it is not what we build. 2.0 is `event_source_id` + `data[]` + `user{}`.

**Snapchat Conversions API v3.**
`POST https://tr.snapchat.com/v3/{pixel_id}/events?access_token={token}`. **v2 was
deprecated in early 2025** — do not follow a v2 example. Body `{"data": [...]}`. Per
event: `event_name` **UPPERCASE** (`PURCHASE`, `ADD_CART`, `VIEW_CONTENT`,
`START_CHECKOUT`, `PAGE_VIEW`), `event_time`, `event_id`, `action_source: "WEB"`,
`event_source_url`, `user_data`, `custom_data`. `em`/`ph` are **SHA-256 hashed arrays**.
`sc_click_id` comes from the `&ScCid=` URL parameter; `sc_cookie1` is the `_scid` pixel
cookie. `custom_data.value` is a **string**, `currency` required for PURCHASE. Matching
needs at least one of: hashed email, hashed phone, or ip + user agent.

**GA4 Measurement Protocol.**
`POST https://www.google-analytics.com/mp/collect?measurement_id=&api_secret=`. Body:
`client_id`, optional `user_id`, `timestamp_micros` (**microseconds**), `consent{
ad_user_data, ad_personalization }`, `events[]` (max 25) with `purchase` params
`currency`, `value`, `transaction_id`, `items[]`. Payload cap 130 kB.

**Google Ads — the gap, now CLOSED (Plan-44b, 2026-08-30).** v1 shipped Google Ads as
browser-only, on the reasoning that a server-side upload meant the Google Ads API:
OAuth2 refresh token, developer token, and an approved access level.

That reasoning was overtaken. Google stopped accepting NEW adopters of offline
conversion imports through the Ads API on **2026-06-15** — a developer token not already
importing between Dec 2025 and May 2026 simply errors — so the path was shut before we
reached it. Its replacement, the **Data Manager API**, needs no developer token, no
access application and no OAuth consent screen: one service account key.

Built and **live-validated** on 2026-08-30 — see §9.

## 2. Why server-side is not optional here

`apps/payments/services.py::confirm_payment` is driven by **gateway webhooks**.
`CheckoutReturn.tsx` polls at most 5 times, 3 s apart, and then shows "we'll email you".
A Paystack or Flutterwave customer whose settlement is slow — or who simply closes the
tab on the gateway's page — **never renders a confirmation page**. Every browser-only
pixel would silently lose those purchases, and they are precisely the events the ad
platforms optimise delivery against. A pixel that under-reports purchases does not just
misreport ROAS; it actively teaches the ad platform to find worse customers.

The seam already exists. `apps/orders/state.py::_effects_for` registers post-commit
effects keyed on the DESTINATION status, and `"processing"` is the paid state — reached
from `pending_payment` (normal) *and* from `expired` (the late-payment re-reserve). One
effect appended there fires Purchase for every enabled channel, webhook or browser.

**The effect goes LAST in the tuple, and that is load-bearing, not stylistic.**
`state.py` already documents it: `on_commit` callbacks are not independent — Django's
`run_and_clear_commit_hooks` runs them in registration order and one that raises
abandons every callback after it. The customer's confirmation email must never be lost
to a marketing pixel. Belt as well as braces, the effect swallows its own exceptions in
the manner of `enqueue_staff_order_paid`.

## 3. Why the attribution has to be snapshotted at placement

The server-side Purchase runs from a webhook. There is no browser, no cookie jar, no IP
and no user agent at that moment — the same reason `Order.referral_code` is stamped at
placement rather than resolved later (its own comment makes this argument).

So the click ids, the pixel cookies, the user agent, the page URL and **the consent
state** are captured in the checkout request and written to `marketing.OrderAttribution`
(OneToOne with Order). The Purchase task reads only from that row.

Consent belongs in that snapshot for a reason that is not obvious: a customer may
withdraw consent between placing an order and the webhook landing. The lawful basis is
the state at collection, and a snapshot is also the only auditable answer to "why did
this event get sent".

## 4. Consent

Region-driven, because a single global rule is either illegal in the UK or needlessly
destroys Nigerian data:

- **Consent-required regions** (default `GB` + EEA, **stored as data** in
  `MarketingSettings.consent_required_countries`, so Hammed can add NG under NDPA
  without a deploy): nothing is stored and nothing loads until the visitor chooses.
  Click ids ride in memory through the landing render and are persisted only on grant.
- **Everywhere else**: banner shown, tracking on, with a genuine "Manage" route to
  withdraw. Withdrawal deletes the marketing cookies it can reach.

`tc_consent` is a first-party cookie carrying a version and the categories
(`necessary` always, `analytics`, `marketing`). Versioned so that adding a fifth channel
can legitimately re-ask. Readable server-side, which is what lets the BFF snapshot it.

## 5. Slices

1. **Consent foundation** (storefront) — cookie, provider, banner, preferences,
   region rule. Nothing else may ship before it.
2. **`apps/marketing`** — `MarketingSettings` (singleton) + `MarketingChannel` (one row
   per channel), `OrderAttribution`, `ConversionEvent` outbox, `hashing.py`, channel
   adapters, Celery delivery with retries, public config endpoint, admin API + audit.
3. **Storefront pixel layer** — consent-gated loaders, click-id capture in `proxy.ts`,
   shared `event_id`, event wiring, **`csp.ts` updated in the same commit**.
4. **Server-side Purchase** — the `_effects_for("processing")` effect + BFF attribution
   capture.
5. **Admin `/settings/marketing`** — per-channel enable, ids, credential status, test
   event code, and a "send test event" button.
6. **Product feed** — one Google-Shopping RSS 2.0 document, consumed by all four
   catalogues, with `content_ids` equal to the SKUs the pixel and CAPI send.

## 6. Traps this design is built around

- **`content_ids` must match everywhere.** Feed id, pixel id and CAPI id are one
  vocabulary. We use `OrderItem.sku` / `ProductVariant.sku`, which already survives
  product deletion in the order snapshot. A mismatch does not error — it silently
  disables dynamic retargeting, which is the expensive half of this work.
- **`?fbclid=` must not disturb `?ref=`.** `proxy.ts` already owns query-parameter
  attribution and has been bitten once (the 2026-08-15 bogus-`?ref=` clobber). Click-id
  capture is additive there and touches neither the referral cookie nor its normaliser.
- **CSP is report-only** (`csp.ts:44`). Pixels will appear to work and quietly log
  violations, then die the day someone sets `REPORT_ONLY = false`. Every origin is added
  in the same commit as the tag that needs it, with the same "why is this here" comment
  the existing entries carry.
- **`event_id` must be identical across browser and server** or every purchase counts
  twice. Purchase uses the order number, which both halves know.
- **Value and currency.** Orders exist in NGN/GBP/USD/CAD. Each event carries its own
  order's currency; the platforms convert. `value` is goods after every discount,
  excluding shipping and tax — one rule, stated once, used by all four adapters.
- **Never hash `fbc`/`fbp`/`ttclid`/`ttp`/`sc_click_id`/ip/user agent.** Hashing them
  does not fail loudly; it silently destroys match quality.
- **Secrets stay out of the database's public reach.** Pixel ids are public and live in
  the DB (the browser gets them anyway). Access tokens are env-backed like every gateway
  key in `payments/`; the admin screen reports *configured / not configured*, never the
  value.

## 7. Open items for Hammed

- Business Manager / Events Manager access to mint: Meta dataset id + CAPI token,
  TikTok pixel id + Events API token, Snap pixel id + CAPI token, GA4 measurement id +
  MP api_secret, Google Ads conversion id + label.
- Whether Nigeria joins the consent-required list under NDPA 2023.
- Google Ads API access application, if server-side Enhanced Conversions is wanted
  later. Not needed for v1.


## 8. Go-live runbook

Nothing below needs a deploy. Steps 1-3 are per channel and can be done one at a time.

1. **Mint the credentials.** In each platform's Events Manager: the public id (Meta
   dataset, TikTok pixel code, Snap pixel id, GA4 measurement id, Google Ads conversion
   id + label) and, for the first four, a Conversions API access token.
2. **Put the tokens in `/opt/tokecosmetics/.env.prod`** and restart the API container:
   `META_CAPI_ACCESS_TOKEN`, `TIKTOK_EVENTS_ACCESS_TOKEN`, `SNAPCHAT_CAPI_ACCESS_TOKEN`,
   `GA4_API_SECRET`. The admin screen names whichever is missing. Pixel ids do NOT go
   here — they are public and belong in the admin.
3. **admin.tokecosmetics.com/settings/marketing**: paste each public id, set a test event
   code, switch the channel on, press **Send test event**, and confirm it arrives in that
   platform's test console. Then CLEAR the test event code — a forgotten one is a silent
   zero in the ad account, and the screen warns about it.
4. **Point each catalogue at the feed:**
   `https://api.tokecosmetics.com/api/v1/marketing/feed/products.xml?country=NG`
   (and `?country=GB` / `US` / `CA` for those ad accounts). Meta Commerce Manager, TikTok
   Catalog Manager, Snapchat Catalogs and Google Merchant Center all accept it.
5. **Watch the outbox** at `/admin/marketing/events/` for the first day. A `failed` row
   carries the vendor's own words in `last_error`; a `skipped` row says why we did not
   send. Both are more useful than the ad dashboards for the first 24 hours.
6. **Decide on Nigeria and consent.** The list currently asks first in GB + the EEA and
   runs opt-out everywhere else. If NDPA 2023 should put Nigeria in the first group, it
   is one edit on the same screen.

### What is NOT proven, and cannot be from here

- No vendor API has been called with a real credential. The adapters are pinned against
  the vendors' documented shapes and against recorded fixtures; the first real call is
  step 3 above.
- The browser pixels have been unit-tested for the GATE (what loads, for whom) but never
  watched loading a real vendor script in a real browser, because there is no real pixel
  id to load one with yet. Worth ten minutes with DevTools open after step 3.
- Event Match Quality — Meta's score for how well the identifiers match — can only be
  read after real traffic. It is the number to look at in week one, and the thing most
  likely to want tuning.


## 9. Plan-44b — Google Ads server-side (BUILT + LIVE-VALIDATED 2026-08-30)

`apps/marketing/channels/google_ads.py`, via
`POST https://datamanager.googleapis.com/v1/events:ingest`.

**This is the only adapter of the five whose wire format was checked against the real
API.** Google's `validateOnly: true` validates a request in full and records nothing, so
the whole chain — service account key, API enablement, Ads permission, customer id,
conversion action id, customer-data terms, and the exact body the adapter emits — was
verified against Toke's live ad account without writing a single conversion. The other
four have no equivalent, which is what the admin's Send test event button is for.

### Two things the live API taught us that the documentation did not

1. **`address.postalCode` is REQUIRED, not optional.** Google's reference reads as
   though it were optional. It is not, and an address without one is a **400 for the
   entire batch**, not a dropped identifier:
   `events[0].user_data.user_identifiers[2].address.postal_code — Required field is
   missing.` This matters more here than it would elsewhere: **Nigerian addresses very
   often have no postcode**, so Toke's main market would have failed most orders. The
   adapter now sends an address only when all four parts are present and falls back to
   email + phone, which are the stronger identifiers anyway. Pinned by
   `test_an_address_without_a_postcode_is_dropped_not_sent_incomplete`.

2. **Three realistic order shapes were validated end to end** (2026-08-30): an NG order
   with gclid + email + phone and no postcode; a GB order with a complete address; and a
   guest with an email and no click id at all. All three accepted.

### The gmail trap

Google normalises gmail.com/googlemail.com by stripping dots and `+tags` before hashing.
Meta, TikTok and Snapchat explicitly do NOT, and `hashing.normalize_email` is
deliberately literal for their sake. Sending the shared hash to Google matches **no Gmail
customer at all** — most of a Nigerian consumer list — and reports no error anywhere.
`channels/google_ads._google_email` is the separate normaliser;
`test_google_normalisation_differs_from_the_shared_one_on_purpose` fails if the two ever
agree.

### One conversion action, not two

`server_destination_id` must name the SAME conversion action the browser tag reports to.
Google deduplicates on `transactionId` — our order number — exactly as the other three
dedupe on `event_id`. A separate "server purchases" action double-counts every sale that
arrives both ways, and looks like a good month rather than a bug.

### Why the credential is base64 in `.env.prod`

The API container takes its whole configuration from
`env_file: /opt/tokecosmetics/.env.prod` and mounts only static, media and the migration
paths. A key FILE would need a new volume mount — a compose edit, a deploy, and a second
place a secret lives. One more line in a file that is already 0600, already holds every
gateway key and is already backed up needs none of that. Base64 because a PEM private key
contains newlines and an env file does not carry them.

### Configuration (2026-08-30)

| Value | Where it lives |
|---|---|
| Service account | `toke-ads-conversions@tokecosmetics-website.iam.gserviceaccount.com` |
| Cloud project | `tokecosmetics-website` (its own, not the Maps project) |
| Ads customer id | `3352855298` — admin screen |
| Conversion action id | `7577766208` — admin screen |
| Manager (MCC) | none — `loginAccount` is not sent |
| Key | `GOOGLE_ADS_DM_CREDENTIALS_B64` in `.env.prod` |

### Still to do

- Put the base64 key in `.env.prod` on the VPS and restart the API container.
- Switch the channel on at `admin.tokecosmetics.com/settings/marketing`.
- Delete the service account JSON from the Desktop once it is on the server.
