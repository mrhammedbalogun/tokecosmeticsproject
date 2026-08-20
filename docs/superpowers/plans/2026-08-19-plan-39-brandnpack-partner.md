# Plan 39 — BrandNPack delivery partner (per-LCDA Lagos rates + partner portal)

**Date:** 2026-08-19 · **Status:** built + verified locally (full backend suite green,
both frontends typecheck/test green, all flows exercised over live dev servers).
NOT yet committed or deployed. Before sharing the portal link: set BrandnPack's real
email + a password on /settings/partners (seed login is unusable on purpose).

## What

BrandNPack is a small Lagos-only courier with no API: a static price per LCDA,
irrespective of weight and pickup location. Source of truth arrived as a Word doc
(`BrandNPack_Logistics.docx`): 55 rows of LGA / LCDA / Major Locations & Landmarks /
Dispatch Zone / Standard Rate. 47 rows carry a clean rate; 3 Badagry + 3 Epe rows have
no rate and Eti-Osa East + Lekki LCDA carry *ranges* — Hammed's ruling: import those
8 as **inactive** until BrandNPack fills a real price.

Three deliverables:

1. **Checkout**: for a Lagos address, each active BrandNPack LCDA row in the chosen
   LGA appears as its own delivery option — `Door Delivery - {LCDA} (BrandnPack)` with
   an "Areas covered: …" line (the doc's Major Locations & Landmarks), the flat rate,
   and a 1–3 day ETA — alongside the existing options (Hammed: "extra option, customer
   picks", "don't disrupt the current LGA structure").
2. **Partner portal**: a link BrandNPack logs into (email+password) and manages all
   five doc fields themselves. Edits go live immediately — no staff approval
   (Hammed's explicit call).
3. **Admin oversight**: staff page to enable/disable the partner, set their login
   credentials, and see/fix/deactivate zone rows.

## Rulings (Hammed, 2026-08-19)

- Keep the LGA-only address structure; show ALL matching LCDA options for the chosen
  LGA, each labelled with its LCDA name.
- Blank/range rows: import inactive, partner fills prices later.
- Partner access: login; edits live immediately; manage all 5 fields.
- Checkout placement: extra options alongside GIG et al.

## Design

### Data (backend, `apps/delivery`)

- `DeliveryPartner(name, code, user OneToOne→User, is_active)` — `is_active` is the
  staff kill-switch; the linked user is `is_staff=False` and exists only to log in.
- `PartnerZone(partner FK, lga_region FK→core.Region, lcda_name, areas_covered,
  dispatch_zone, price nullable, min_days=1, max_days=3, is_active)`.
  `price=NULL` means "needs a price" and the row never reaches checkout. Currency is
  implicitly NGN (partner options only appended for NGN orders).
- Seed migration: the BrandnPack partner (user seeded with an UNUSABLE password —
  staff set real credentials in admin before sharing the link) + all 55 rows. Doc
  LGA names map onto the `ng_regions.json` spellings via an alias map
  (`Eti-Osa → Eti Osa`, `Surulere → Surulere Lagos State`); an unmatched name FAILS
  the migration loudly rather than dropping rows.

### Checkout options (virtual expansion — no DeliveryOption rows)

`services.options_for_address` appends partner options after the DeliveryOption list:
active partner + active zone + non-null price + `lga_region` in the address's region
set + order currency NGN. Dict shape: `id="pz:{pk}"` (string — collision-proof
against DeliveryOption int pks), `kind="partner"`, `carrier_code=partner.code`,
`areas_covered`, flat `price`, `quote_required=False`.

Why virtual, not one DeliveryOption row per zone: a single source of truth the
partner edits, no 47-row clutter in the staff delivery-options CRUD, no sync between
two tables. Orders only snapshot `delivery_option_name`, so nothing downstream needs
an FK. `kind="partner"` passes untouched through `carriers.py` (only `kind="carrier"`
is decorated) and trips neither the GigShipment nor the ShippingQuote hook in
`place_order`.

String ids ripple three places, all made tolerant via `str(a) == str(b)` matching:
`place_order`, `QuoteView`, `GuestQuoteView` — and the two quote serializers'
`delivery_option_id` fields go `IntegerField → CharField` (DRF CharField accepts ints
from old clients). The checkout POST reads the id raw off `request.data`, so it
already round-trips strings.

### Partner auth (`toke-partner` audience)

Mirrors the admin audience machinery: `PARTNER_AUDIENCE = "toke-partner"` on the same
`toke_aud` claim, `PartnerJWTAuthentication(_AudienceScopedJWTAuthentication)`,
minted only by `mint_partner_token_pair` from the partner login view. The audience
equality check keeps partner tokens out of the admin surface and vice versa.
`CustomerJWTAuthentication` now refuses the partner audience too (same reasoning as
preauth: an external business's credential must not open the customer surface).
Permission `IsDeliveryPartner` re-reads `user.delivery_partner.is_active` from the DB
every request — flipping the switch revokes access immediately, mirroring `is_staff`.

No TOTP for the partner (Hammed accepted "login, edits go live"); compensations:
hard login throttles (own IP + email buckets), a surface of exactly one table, and
the staff kill-switch.

### API surfaces

- `/api/v1/partner/` (new prefix — deliberately NOT under `/admin/`, whose guard test
  pins `AdminJWTAuthentication` exactly): `auth/login/`, `auth/logout/` n/a (BFF
  clears cookies), `me/`, `lgas/` (Lagos area regions for the dropdown), `zones/`
  CRUD (own rows only; region must be an NG area-level region).
- `/api/v1/admin/partners/` (list + PATCH is_active/email + `password/` action) —
  `settings.manage` (credential minting = Owner). `/api/v1/admin/partner-zones/`
  full CRUD — `products.manage` (same scope as delivery options).

### Frontends

- **Storefront**: `DeliveryOption.id: number | string`, optional `areas_covered`
  rendered as a muted "Areas covered: …" line on the option card (matches Hammed's
  sample screenshot). `CheckoutContext.deliveryOptionId` widens to `number | string`.
- **Admin app — partner portal**: `/partner/login` + `/partner` (rates table:
  add/edit/delete rows, LGA dropdown, price, badge for rows needing a price). Own
  cookies (`partner_access`/`partner_refresh`, httpOnly, Strict), own branch in
  `proxy.ts`; all data flows through `/api/partner/*` BFF route handlers (route
  handlers may write cookies, so a single silent-refresh helper suffices — no RSC
  bounce machinery needed).
- **Admin app — staff page**: `/settings/partners` — partner on/off, set login
  email/password, zones table with deactivate/delete/edit.

## Out of scope (v1)

- Express Rate column (empty in the doc; schema has no field for it yet).
- Additional partners UI-side (model is generic; creating one is a migration/shell task).
- Waybill/tracking integration — BrandNPack has no API; fulfilment is manual.
