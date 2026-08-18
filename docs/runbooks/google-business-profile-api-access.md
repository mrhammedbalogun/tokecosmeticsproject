# Applying for Google Business Profile API access

**Why we need it:** to show Toke's real Google reviews on the homepage, updating
themselves, legally. The Places API — which the site already uses for the header
rating and count — cannot do this job. It returns only five reviews, and its terms
give no allowance to store review text at all (Maps Platform Service Specific Terms
§14.3 permits caching latitude and longitude, and nothing else). The Business
Profile API is the owner-authenticated API for *your own* listing: all 49 ratings,
free, no per-call billing, and review replies from admin if we ever want them.

**Who must do this:** you, signed in as the Google account that **owns or manages the
Toke Cosmetics Business Profile**. It cannot be delegated to a developer account that
isn't on the listing, and it cannot be done from the VPS.

**Time:** ~20 minutes of form-filling, then Google reviews it. Their stated window is
up to 14 days; in practice 3-10 business days is typical.

---

## Before you start — have these ready

| Thing | Value for Toke |
|---|---|
| Google account | the one that manages the Toke Cosmetics Business Profile |
| Business Profile | "Toke Cosmetics" (Place ID `ChIJj1450kjsOxARhI16Z0jVX-c`) |
| Google Cloud project | `tokecosmetics` — the SAME project the Maps keys live in (see `google-apis-setup.md`) |
| Website URL | `https://tokecosmetics.com` |
| Company name | Toke Cosmetics |

> Use the existing `tokecosmetics` Cloud project rather than making a new one. Access
> is granted **per project**, and having Maps and Business Profile in one place keeps
> the quota and billing story simple.

---

## Step 1 — Confirm you actually manage the listing

1. Go to <https://business.google.com/> and sign in.
2. You should see **Toke Cosmetics** with the role **Owner** (or Manager).
3. If it says "Manager", that is enough for the API, but Owner is smoother — if
   someone else is Owner, get them to run this application instead.

If the listing is unverified, verify it first. Google will not approve API access for
an unverified profile.

## Step 2 — Enable the APIs in the Cloud project

In <https://console.cloud.google.com/>, with the **`tokecosmetics`** project selected,
go to **APIs & Services → Library** and enable **all** of these. They are separate
APIs and access is granted per-API, so missing one means a half-working integration:

1. **Google My Business Account Management API** — lists accounts/locations. Without
   it you cannot even find the location ID, so nothing else works.
2. **My Business Business Information API** — location details.
3. **Google My Business API** — **this is the one that carries reviews.** It does not
   appear in the Library until access is approved; that is expected, enable the others
   now and come back for this one.
4. **My Business Notifications API** *(optional but wanted)* — lets Google push a
   Pub/Sub notification when a **new review arrives**, which is how the site becomes
   genuinely realtime instead of polling on a timer.

## Step 3 — Submit the access request

1. Go to the request form: <https://developers.google.com/my-business/content/prereqs>
   → follow the **"Request access"** link (it opens a Google Form; Google moves this
   URL occasionally, so navigate from the prereqs page rather than bookmarking it).
2. Fill it in. The fields that matter, and what to put:

   - **Google Cloud project ID** — the `tokecosmetics` project's *ID*, not its display
     name. Find it on the Cloud console dashboard; it usually has a number suffix.
   - **Google account email** — the Business Profile owner/manager address.
   - **Business/organisation name** — Toke Cosmetics.
   - **Website** — `https://tokecosmetics.com`
   - **How many locations do you manage?** — answer honestly (1, unless the other
     country listings are separate profiles).
   - **Are you managing your own business or acting on behalf of others?** — **your
     own business.** This is the easy path; the agency/third-party path gets more
     scrutiny.
   - **Use case / what will you build?** — the free-text box that decides the outcome.
     Draft below.

3. **Use-case text — copy this, adjust if anything is untrue:**

   > We operate Toke Cosmetics, a skincare retailer in Lagos, Nigeria, and we own the
   > associated Google Business Profile. We are integrating the API into our own
   > e-commerce website, tokecosmetics.com, for two purposes. First, to display our
   > own customer reviews on the site's homepage, each linking back to the review on
   > Google Maps, so the social proof shown to shoppers stays accurate and current
   > rather than being manually copied and going stale. Second, to read and reply to
   > new reviews from our internal admin dashboard so our small team can respond
   > promptly. This is for our own single business location only. We are not building
   > a product for third parties, not reselling access, and not aggregating data from
   > businesses we do not own. Our Google Cloud project already uses the Maps Platform
   > APIs for address autocomplete and delivery mapping on the same site.

   Why this wording works: it names a real verifiable website, states you own the
   listing, gives a concrete first-party use case, and explicitly rules out the
   reseller/aggregator pattern that Google is actually screening for.

4. Submit. You get an automated acknowledgement immediately — that is **not** approval.

## Step 4 — Wait, and know what approval looks like

- Approval arrives by email to the address on the form. Check spam.
- The real test is quota. In **Cloud console → APIs & Services → your API → Quotas**,
  a **`0` requests-per-minute** quota means **not approved**; **`300`** means approved.
  An approved-looking email with 0 QPM means the grant did not land on this project —
  reply to the thread quoting the project ID.
- **Common trap:** the Business Profile API can be approved while the *Account
  Management* API is still at 0 QPM, which silently blocks `accounts.list` and makes
  everything look broken. Check the quota on **every** API from Step 2, not just one.

## Step 5 — Tell me it landed

Once quota is 300, say so and I will build the sync. What that gets you, concretely:

- **All** reviews, not five — so the homepage can feature genuinely recent ones
  instead of the four two-year-old cards it shows today.
- A real refresh path. With the Notifications API + Pub/Sub, a new review can hit the
  homepage within seconds of being posted; without it, a scheduled pull (which is now
  free, so cadence is a design choice rather than a billing one).
- Review replies from the admin dashboard, if you want them.

I will need from you at that point: OAuth client credentials (a refresh token for the
owner account, stored in `.env.prod` alongside the other secrets — never in the repo).

## If it gets rejected

Rejections are usually one of:

- **Unverified or unclaimed Business Profile** → fix Step 1 and re-apply.
- **Vague use case** → re-apply with the concrete wording above; "improve our
  business" gets declined, "display our own reviews on tokecosmetics.com" does not.
- **Looks like an aggregator** → make the "our own single location, not for third
  parties" sentence prominent.

You can re-apply. Nothing about the current site breaks in the meantime: the curated
reviews stay live and the nightly header sync keeps running.

---

## Meanwhile (current state, 2026-08-18)

All five reviews Google publishes for the shop are live on the homepage, each linking
to its own review permalink, curated through **Admin → Content → Google reviews**. The
header rating and count sync from the Places API nightly. See `google-apis-setup.md`
for why that split exists and why it must not be "upgraded" to a Places review sync.
