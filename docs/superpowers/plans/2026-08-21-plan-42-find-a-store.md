# Plan 42 — Find a Store (public locator + admin directory)

**Date:** 2026-08-21 · **Status:** DEPLOYED 2026-08-22 — `d6774f1` → `backend-v0.50.0`
(CI deploy success, VPS on the tag, `stores.0001_initial` applied) + both Vercel apps,
live-verified: `api.tokecosmetics.com/api/v1/stores/places/` 200, `tokecosmetics.com/find-stores`
renders, `admin.tokecosmetics.com/find-stores` gates to login. Prod directory is EMPTY
until stores are added through the admin. (Pre-deploy: backend 60 + full suite green,
storefront 963, admin 949; both apps typecheck + lint clean; browser-walked.)

## What

A customer picks **Country → State → LGA** on `/find-stores` and sees the Toke
Cosmetics counters and authorized distributors there, each with an address, a phone
number that dials, and a directions link. Staff maintain that directory from a new
admin section, **Find a Store**, behind `products.manage`.

## Why it is its own app and not a table in `delivery`

`delivery.SenderLocation` looks like the same table and is not. Every ACTIVE row of it
is a candidate GIG shipping origin — `delivery/gig/origins.select_origin()` picks the
nearest active one by haversine — so filing a distributor in Kano there would silently
start routing real parcels through a shop that has never packed one. The two tables
answer different questions: SenderLocation answers "where do we ship FROM", `stores`
answers "where can I buy this today".

They overlap in the real world (an Ogudu counter is both). That overlap is handled by a
WARNING at create time — `services.possible_duplicates` looks at SenderLocation rows
too — rather than by a nullable FK that nothing enforces and nothing syncs.

## Decisions worth re-reading

1. **The cascade only offers places that HOLD a store.** `/stores/places/` is not
   `/meta/regions/`. A locator whose LGA dropdown lists all 57 Lagos LGAs invites the
   customer to pick one of the 50-odd that answer "nothing here" — that is the
   interaction failing, not the data. The consequence, stated plainly: the empty state
   is only reachable by a shared or bookmarked link whose store has since been
   archived, or by an empty directory. It is still built and still tested, because both
   happen. The ADMIN does the opposite and is right to: an operator filing a new shop
   must be able to pick an LGA that holds nothing yet.
2. **Slugs, never ids**, in the customer's URL: `?country=nigeria&state=lagos&area=alimosho`.
   Legible in the WhatsApp message this page will actually be shared in, and it keeps
   primary keys off a public page. `tests/test_slugs.py` pins the no-collision
   assumption underneath it.
3. **Three visibility states, not two.** `active` (listed), `inactive` (temporarily not
   listed, still fully editable), `archived` (`archived_at` set — what DELETE does,
   hidden from the admin list unless asked for, restorable). There is no hard delete
   and no purge endpoint; a bogus row lives out its life archived.
4. **Restore brings a store back INACTIVE.** The row was archived for a reason, and
   whoever restores it should confirm the address and phone before customers are sent
   there.
5. **Duplicates: a soft warning plus a narrow hard constraint.** Same name AND same
   address in the same place is the same shop (a unique index, split in two so it also
   binds outside Nigeria where `area_region` is NULL). Everything fuzzier — similar
   name, shared phone, look-alike address, a matching pickup location — is a 409
   carrying the rows it matched, which the operator overrides with `confirm_duplicate`.
   Two branches of "Beauty Hub" in Alimosho is an ordinary thing; refusing the second
   teaches the operator to invent fake names.
6. **Scope is `products.manage`** (Owner + Manager), matching Pickup locations exactly:
   both are lists of physical shops maintained by whoever runs the day to day.
7. **The finest place is mandatory**, and which one it is depends on the country: an
   LGA where the state has them, a town or city where it does not (GB/US/CA). A store
   filed only as "England" is not findable.
8. **Opening hours are one free-text line**, not a structured table. Structured hours
   mean public holidays, split shifts, timezones and an "open now" badge that is wrong
   on Boxing Day. The second question a store finder gets asked deserves an answer; it
   does not yet deserve a schema.

## How it hangs together

- **Backend** — `apps/stores`: `StoreLocation` + `services` (the cascade, slug
  resolution, `maps_url`, `whatsapp_url`, `possible_duplicates`), two anonymous public
  views (`/stores/places/`, `/stores/`) and one admin viewset with a `restore` action.
  Phone display is composed server-side (`core.phones.format_display`) so the storefront
  and the admin cannot drift about how a number reads: national form at home,
  international abroad, and every `tel:`/`wa.me` link built from the stored E.164.
- **Storefront** — `/find-stores` resolves the whole selection SERVER-SIDE so a shared
  link arrives with its cards in the HTML (crawlable, and no spinner flash for the one
  reader who was sent a specific shop). `StoreFinder` takes over from the first click:
  one monotonic ticket guards every fetch, so Alimosho's slow answer can never overwrite
  Ikeja's, and the URL is kept in step with `history.replaceState` rather than a Next
  navigation that would refetch what the click just fetched.
- **`PlacePicker`** is a searchable listbox, not a `<select>` — the brief asks for that
  by name, and a native option cannot carry the "3 stores" hint. One tab stop when
  collapsed, `aria-activedescendant` when open, Escape returns focus to the trigger.
  The filter box appears only past 7 options: below that it is furniture, and on a phone
  it raises the keyboard over the list it is meant to help you read.
- **Admin** — `/find-stores`: filters that combine in SQL (country, state, LGA, type,
  status, and a search that matches a phone typed the way it is printed on the door),
  DRF pagination, and an add/edit form whose cascade is filtered from the one
  `/admin/regions/` payload the page already loads. A real table from `lg` up, stacked
  cards below it — `overflow-x-auto` is a horizontal scrollbar with good manners, not a
  responsive strategy.

## Verified in a browser

Storefront (desktop 1440 and iPhone 13): cascade, keyboard-only selection, URL sync,
country change clearing results, GB's two-level cascade searching at state level, deep
link SSR with `LocalBusiness` JSON-LD, no horizontal overflow. Admin: nav item, list,
`Nigeria + Lagos + Authorized Distributor` narrowing to 4, phone-suffix search finding
an E.164 row from "0802 390 0964", the duplicate warning and its "Save anyway", create,
hide, two-step archive, and restore-comes-back-hidden.

## Edge-case review (2026-08-22, second pass)

A deliberate re-read after the build, hunting for the cases the brief lists. Found and
fixed, each with a test that fails without the fix:

- **Retry after a failed state/LGA load did nothing.** `retryPlaces` nulled the slug and
  re-called the pick handler, whose same-value guard read the slug from a closure the
  `setState` had not updated. Split into `pick*` (guarded) and `load*` (not) so the retry
  can never route through the guard again.
- **A failed fetch looked like an empty directory.** `getPlaces` swallowed errors into an
  empty list, so an outage rendered "Nothing here yet" with no way out. It now returns
  `null`; the page passes `placesFailed`; the pickers say "Couldn't load" and offer a
  Try-again that can refetch even the country list.
- **Half a pin could be saved.** `maps_url` only uses the pin when both coordinates are
  set, so a row with a latitude and no longitude looked pinned and was not. The
  serializer now refuses the half-pin and range-checks both.
- Smaller: slug matching on the server page was case-sensitive where the backend's is
  not; "Select an lga" lowercased an acronym; a stale `?area=` bookmark fell back to the
  whole state silently (it now says so, once); a single unbroken token could overflow a
  card; the empty-directory intro said "choose your country" to a dropdown with nothing
  in it.

## Known limitations

- **No map and no distance sort.** `latitude`/`longitude` exist and are used only to
  aim the directions link; nothing geocodes, and there is no "nearest to me".
- **No bulk import.** `bulk_create` bypasses `save()`, so the derived duplicate keys
  would be empty — a future importer must set `name_key`/`address_key` itself.
- **Renaming a region breaks links to it**, which is the cost of slugs. A stale `?area=`
  falls back to the state-wide answer rather than 404ing.
- **Prod has no store rows yet.** The page is live and empty until the directory is
  filled in; the countries dropdown only lists markets that hold a store, so an empty
  directory shows the intro state and nothing else.
