# Google Cloud setup — Maps/Geocoding (32b slice 3) and Reviews (homepage)

Two consumers, two keys from ONE Google Cloud project:

| Key | Lives in | Used by | APIs allowed |
|---|---|---|---|
| Browser key | `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (storefront `.env.local` + Vercel) | Places autocomplete assist, confirm-your-pin map, client geocoding (32b slice 3) | Maps JavaScript API, Places API, Places API (New), Geocoding API |
| Server key | `GOOGLE_PLACES_API_KEY` (backend `.env` on the VPS) | Place Details pull that refreshes the homepage rating + review count (`cms.GoogleReviewsMeta`) | Places API (New) only |

Two keys because the browser key is PUBLIC by definition (`NEXT_PUBLIC_` ships in the
bundle) — its only fence is the website restriction. The server key never leaves the VPS
and is IP-locked. Never reuse one for the other's job.

The featured homepage reviews themselves stay CURATED (share-link permalinks pasted into
admin) — design ruling 2026-08-04, recorded on `cms.GoogleReview`: the API returns at
most five "most relevant" reviews with no per-review permalink. The API pull only feeds
the header numbers ("4.8", "300+").

## 1. Project + billing (once)

1. https://console.cloud.google.com — sign in with the business Google account (use the
   same account that owns the Google Business Profile if possible; not required though).
2. Top bar project picker → **New project** → name `tokecosmetics` → Create, and switch
   to it (every later step happens INSIDE this project).
3. **Billing** (left menu) → link a billing account (card required). Pricing note: since
   March 2025 Google Maps Platform gives **10,000 free calls per month per Essentials
   SKU** (Autocomplete, Geocoding, Place Details are all Essentials). At Toke's traffic
   the expected bill is ₦0; the caps in §4 make that a guarantee.

## 2. Enable the four APIs

**APIs & Services → Library**, search and Enable each:

1. **Maps JavaScript API** — the pin-confirm map.
2. **Places API (New)** — autocomplete data + Place Details for the reviews meta.
3. **Places API** (legacy) — the classic JS `Autocomplete` widget still calls this one;
   enabling both costs nothing extra and removes a whole class of "REQUEST_DENIED".
4. **Geocoding API** — address → lat/long and reverse.

## 3. Create + restrict the two keys

**APIs & Services → Credentials → Create credentials → API key**, twice.

**Key 1 — rename `tokecosmetics-browser`:**
- Application restrictions → **Websites**, add:
  - `https://tokecosmetics.com/*`
  - `https://*.tokecosmetics.com/*`
  - `https://*.vercel.app/*` (Vercel previews; tighten to the project's preview pattern later)
  - `http://localhost:3000/*` (local dev)
- API restrictions → **Restrict key** → tick exactly: Maps JavaScript API, Places API,
  Places API (New), Geocoding API.
- Save; put the key in `storefront/.env.local` as `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` and
  in Vercel → Project → Settings → Environment Variables (all three environments).

**Key 2 — rename `tokecosmetics-server`:**
- Application restrictions → **IP addresses** → add the VPS IP `203.161.38.201`.
- API restrictions → Restrict key → tick only **Places API (New)**.
- Save; goes into `backend/.env` on the VPS as `GOOGLE_PLACES_API_KEY` (never into the
  repo, never into the storefront).

## 4. Spend guard-rails (do not skip)

1. **Billing → Budgets & alerts** → Create budget, e.g. $10/month, email alerts at
   50/90/100%.
2. **APIs & Services → Enabled APIs** → open each of the four → Quotas → cap
   requests-per-day to generous-but-finite numbers (e.g. Geocoding 2,000/day,
   Autocomplete 5,000/day, Place Details 500/day). A leaked/looping key then plateaus
   instead of billing through the roof.

## 5. The place ID (for the reviews meta pull)

The Place Details call needs the shop's `place_id`:

1. https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder
   → search "Toke Cosmetics" (the Business Profile listing) → copy the `ChIJ…` id.
2. It is not a secret; it will live in admin/env when the pull task is wired.

Sanity-check from the VPS once the server key exists (single free call):

```
curl -s "https://places.googleapis.com/v1/places/PLACE_ID?fields=rating,userRatingCount" \
  -H "X-Goog-Api-Key: $GOOGLE_PLACES_API_KEY"
```

Expected: `{"rating": 4.8, "userRatingCount": 312}`-shaped JSON. That pair is exactly
what will refresh `GoogleReviewsMeta` (rating, review_count_text) on a schedule.

## 6. What the code calls (reference)

- Storefront (browser key): Maps JS `Autocomplete`/`PlaceAutocompleteElement`, the map
  for pin-confirm, `google.maps.Geocoder` — all loaded via the Maps JS script tag.
- Backend (server key): `GET https://places.googleapis.com/v1/places/{place_id}` with
  `fields=rating,userRatingCount`, header `X-Goog-Api-Key` — the ONLY server-side call
  planned; anything more needs a fresh look at quotas and restrictions.
