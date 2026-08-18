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
admin). The API pull only feeds the header numbers.

### Why curated — re-examined 2026-08-17, ruling upheld on DIFFERENT grounds

The original 2026-08-04 reason was "the API has no per-review permalink". **That is no
longer true** — Places API (New) returns `googleMapsUri` on every review object. Do not
take that as licence to build a sync; three things kill it, and the first is decisive.

1. **Storing the reviews is off-terms.** Maps Platform Service Specific Terms §14.3, for
   Places API, reads in full: *"Customer may temporarily cache latitude and longitude
   values from the Places API for up to 30 consecutive calendar days, after which
   Customer must delete the cached latitude and longitude values."* That is the entire
   caching allowance; §A.3 adds Google IDs (`place_id`). Review text, author names and
   avatars have **no** storage allowance — not 30 days, none. Refresh frequency does not
   fix this: a `cms.GoogleReview` row holding API-pulled text is off-terms at any cadence.
2. **The cost trap.** Requesting the `reviews` field promotes the whole call from *Place
   Details Essentials* (10,000 free calls/month) to **Place Details Enterprise +
   Atmosphere**, whose free allowance is **1,000 calls/month**. Hourly polling is ~730 —
   nominally free, with no headroom for retries, staging or a manual re-sync, and
   billing at the platform's most expensive SKU the moment it overflows.
3. **It would be a marketing own-goal.** The API returns five relevance-picked reviews.
   Four of Toke's five are two years old, so a synced homepage would read "2 years ago"
   four times across the front door's social proof — and the policies require *"a clear
   notice that describes how reviews are being ordered and filtered"*, so quietly hiding
   the stale or low-starred ones is itself a disclosure obligation.

### The sanctioned route to real automation

**Google Business Profile API** — not the Places API. Places is a third-party *lookup*
tool; Business Profile is the owner-authenticated API for a business's own listing.
`accounts.locations.reviews.list` returns **all** reviews (Toke has 49 ratings, versus the
five Places will ever hand back), it is **free** with no per-call billing, and it carries
review-reply support. The catch is an access application: Google reviews the request in
up to 14 days (commonly 3-10 business days), and an unapproved project sits at 0 QPM.

**Step-by-step application guide, including the use-case wording that gets approved:
`google-business-profile-api-access.md`.** Until it is approved, curation is both the
compliant answer and the only one available.

### Attribution obligations (they apply to anything Google-sourced)

- Displaying Places content **without a Google map** requires the Google logo (the text
  "Google Maps" is acceptable where space is tight). The homepage cards carry the real
  four-colour Google mark for this reason — a hand-drawn letter "G" does not qualify.
- Reviews must credit the author "using all available resources (avatar, name, and
  profile link) when space allows", and end users must be able to reach the review on
  Google via its `googleMapsUri`. The cards link to the permalink; that is the one that
  matters most.

## 1. Project + billing (once)

1. https://console.cloud.google.com — sign in with the business Google account (use the
   same account that owns the Google Business Profile if possible; not required though).
2. Top bar project picker → **New project** → name `tokecosmetics` → Create, and switch
   to it (every later step happens INSIDE this project).
3. **Billing** (left menu) → link a billing account (card required). Pricing note: since
   March 2025 Google Maps Platform gives **10,000 free calls/month per Essentials SKU**,
   5,000 per Pro SKU and only **1,000 per Enterprise SKU**. Autocomplete and Geocoding
   are Essentials. **Place Details is not one SKU** — the tier is set by the fields you
   ask for, and the whole call is billed at the highest tier any requested field belongs
   to. Our nightly reviews-header call asks for `rating` + `userRatingCount`, which are
   *Enterprise* fields: ~30 calls/month against a 1,000 allowance, so still ₦0, but the
   headroom is 1,000 and not 10,000. Adding `reviews` would drop it another tier again
   (see "Why curated" below). The caps in §4 are what make ₦0 a guarantee.

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
