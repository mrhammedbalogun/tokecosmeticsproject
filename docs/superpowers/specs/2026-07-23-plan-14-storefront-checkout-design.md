# Plan-14 — Storefront checkout (cart → checkout → bank transfer → confirmation) — Design

**Status:** Approved by Hammed 2026-07-23 (payment scope, split into 14/14b, Stripe dropped, flow). Ready for implementation-plan authoring.

## Goal

Turn the Plan-12 cart/checkout skeletons into the real purchase flow: a cart page, an Amazon-style
5-step checkout, and order confirmation — wired **end-to-end to bank transfer**, the only currently
live payment method. Guests can check out via silent inline account creation. Ships independently and
is verifiable without any external gateway.

## Scope split (decided)

- **Plan-14 (this spec):** cart page + full 5-step checkout flow + inline guest signup + Buy-Now guest
  resume + bank-transfer order placement + confirmation + failure/cancel UX. Checkpoint: Hammed places
  a real bank-transfer order on his phone.
- **Plan-14b (next, separate spec/plan):** layer **Paystack, Flutterwave, PayPal** onto the payment
  step, each with its own sandbox test. Hammed has all three sets of test credentials.
- **Stripe: dropped** (was the master-guide Apple Pay / Google Pay / international-card path).
  Explicitly out of scope for 14 and 14b. Revisit only if international-card coverage becomes a need.

## Hard constraints (verified against the backend)

- `POST /api/v1/checkout/` (place order) and `GET /checkout/delivery-options/` are **`IsAuthenticated`**.
  → There is **no pure-guest order**; every checkout must end with an authenticated user. The inline
  signup in step 1 is the mechanism (silent account creation), not an optional nicety.
- `GET /checkout/payment-methods/` is **`AllowAny`** and returns only **active** methods per country.
  All gateways are deactivated (Plan-09); bank transfer is the sole active method → the payment step
  naturally renders one option this plan. When 14b activates a gateway, it appears here automatically.
- `GET /checkout/delivery-options/?address_id=&cart_id=` requires a chosen address **and** a non-empty
  cart (both user-owned) — so the delivery step must come **after** the address step.
- The browser never holds a JWT: all authed calls go through Route Handlers / `fetchWithAuth`
  (Plan-12 pattern). Money strings are displayed verbatim; never computed/rounded in the storefront.

## Architecture

Storefront + BFF only — no backend changes in Plan-14.

**Pages**
- `src/app/(shop)/cart/page.tsx` — the cart page (replaces the skeleton).
- `src/app/(shop)/checkout/page.tsx` — the checkout flow host (replaces the skeleton).
- `src/app/(shop)/checkout/confirmation/[number]/page.tsx` — order confirmation.

**Components** (`src/components/checkout/`)
- `CheckoutFlow.tsx` — client host owning step state (which step is open/complete) + shared checkout
  context (chosen address, delivery option, payment method).
- `StepShell.tsx` — one collapsible step: header with number/title, "Change" when complete, one-line
  summary when collapsed, body when open. Mobile-first; keyboard-operable; single-open accordion.
- `SignInStep.tsx` — logged-in → auto-complete/skip; guest → email + first name + password (silent
  create + login); existing-email detection → password (login) instead.
- `AddressStep.tsx` — address-book cards + "Add new address" (per-country structured form; NG shows
  State → LGA labelled by `area_label`; country locked to the shopping country with a "changing
  country restarts pricing" note). Reuses the Plan-11 address components/BFF where possible.
- `DeliveryStep.tsx` — radio cards from `/checkout/delivery-options/` for the chosen address; re-fetches
  when the address changes.
- `PaymentStep.tsx` — options from `/checkout/payment-methods/`; this plan wires **bank transfer**
  (account-details screen after placement). Structured so 14b drops gateways in without a rewrite.
- `ReviewStep.tsx` — full order summary (items, address, delivery, totals incl. tax line), optional
  order note, single **Place order** button (nothing happens before this click).
- `OrderSummary.tsx` — sticky sidebar on desktop / collapsible on mobile; reused on cart + checkout.
- `CartView.tsx` — cart line items (qty editors, remove), coupon field with specific inline errors,
  totals, estimated delivery (shipping preview), free-shipping progress bar when a `free_over` rate
  exists for the country, trust badges.

**BFF Route Handlers** (`src/app/api/`)
- `checkout/route.ts` — `POST` proxy to `POST /api/v1/checkout/` via `fetchWithAuth` (authed;
  forwards cart_id/address_id/billing_address_id/delivery_option_id/note; returns order number +
  bank-transfer initiation payload).
- Reuse existing: `/api/cart` (lines/qty/coupon), `/api/auth/[action]` (register/login for inline
  signup), plus Plan-11 address BFF. Add a coupon apply/remove path if not already covered by the cart BFF.

**Backend endpoints consumed** (all exist): cart + coupon + totals (Plan-08), delivery-options
(Plan-08b/14a), payment-methods + place_order + bank-transfer initiation (Plan-09/09b),
addresses (Plan-11), register/login (Plan-11/12).

## Checkout flow (the Amazon sequence)

Stacked collapsible steps; completed steps collapse to a one-line summary with "Change"; the totals
summary is always visible (sticky desktop / collapsible mobile). Nothing is charged/placed until the
final "Place order" click.

1. **Sign in / inline signup** — logged-in users are pre-completed and the step is collapsed. Guests
   enter email + first name + password → account created silently + logged in (no detour to a separate
   register page). If the email already exists → the field set flips to email + password (login).
2. **Delivery address** — selectable address-book cards + "Add new address". New-address form is the
   per-country structured form (NG: State → LGA dropdowns; country locked to the shopping country).
   Selecting/adding an address completes the step and unlocks step 3.
3. **Delivery options** — `GET /checkout/delivery-options/?address_id=&cart_id=`, rendered as radio
   cards (name, price, ETA). Re-fetches and resets whenever the chosen address changes.
4. **Payment method** — `GET /checkout/payment-methods/`; bank transfer is the only active option now.
   Selecting it just records the choice; the account details appear after placement (step 5 → place).
5. **Review & place order** — full summary (items, address, delivery, totals incl. tax), optional note,
   one **Place order** button → `POST /api/checkout` → order created (pending) + bank details returned.

## Bank-transfer placement, confirmation, failure

- **After Place order:** show the **bank-transfer details** (account name/number/bank + the exact
  amount + the unique bank reference) with an **"I've paid / I'll pay"** acknowledgement that routes to
  the confirmation page. The order is **pending** until staff confirm the transfer (existing Plan-09b
  flow; storefront does not mark it paid).
- **Confirmation page (`/checkout/confirmation/[number]`):** order number, items, totals, delivery
  estimate, **bank details re-shown** (so they aren't trapped only in the email — master-guide
  follow-up), and — for a guest who just auto-signed-up — a gentle "your account is ready" note (they
  already have a password). Tracking-link explanation.
- **Failure / abandonment:**
  - Reservation/stock expired before placement → clear message + cart restored; user restarts checkout.
  - **Customer-visible cancel** on a pending order (surfaces the existing `orders.services.cancel_order`)
    so an abandoned "see the account number and walk away" checkout doesn't hold thin NG stock for 24h.
    Placement error (e.g. an item went out of stock mid-checkout) → specific message pointing at the line.

## Buy-Now guest resume (deferred from Plan-13 D6)

Guest Buy Now already stashes `{variant_id, quantity}` in `sessionStorage["toke-buynow-intent"]` and
routes to `/login?next=/checkout`. This plan completes the loop: after inline signup/login, the
checkout host reads that intent, ensures the express/standard cart holds the item, clears the intent,
and lands the user in checkout with the item intact.

## Testing & verification

- **Unit (Vitest + RTL):** step-state machine (single-open, complete/collapse, "Change" reopen);
  SignInStep branch (new vs existing email); coupon inline-error rendering; free-shipping progress math
  (display only, never rounds money); OrderSummary totals rendering; the checkout BFF (authed forward,
  401 without session, upstream-error passthrough); Buy-Now intent resume.
- **Live (prod build + Playwright — the hydrating browser; the Claude preview pane does not hydrate):**
  NEW-customer inline-signup checkout end-to-end to a pending bank-transfer order; returning-customer
  checkout; Buy-Now-while-logged-out → signup → resume with item intact; a Lagos address showing
  LGA-specific delivery vs a UK address showing UK options; mobile 375px walkthrough (no horizontal
  scroll); cancel-a-pending-order path; reservation-expired path.
- **Lighthouse** on cart + checkout ≥ 90 (checkout will carry 3rd-party gateway JS in 14b — load those
  lazily only when a gateway is selected; not a concern for 14's bank-transfer-only build).

## Checkpoint

🚦 **Hammed places a real bank-transfer order himself on his phone** (new-customer inline signup path),
reaches the confirmation page with the bank details shown, and confirms the pending order appears in
the backend. Blocks merge. On sign-off: merge → main; Plan-14b starts.

## Decisions record

- **D1 — Payment scope:** bank transfer only in Plan-14; Paystack/Flutterwave/PayPal in 14b; Stripe
  dropped entirely. (Hammed, 2026-07-23.)
- **D2 — Split 14/14b:** ship a bank-transfer checkout first, layer gateways after. (Hammed.)
- **D3 — No pure guest:** silent inline account creation, forced by the authed backend. (Constraint.)
- **D4 — No backend changes** in Plan-14; storefront + BFF only (all endpoints already exist).

## Carried gaps / out of scope

- Gateway integrations (14b). Order-history / account order-detail UI (Plan-15). Live delivery quotes
  beyond the existing options endpoint. Prod throttle/proxy + real media host + Django revalidate
  webhook (Plan-22). Rich Results public-URL test (deploy).
