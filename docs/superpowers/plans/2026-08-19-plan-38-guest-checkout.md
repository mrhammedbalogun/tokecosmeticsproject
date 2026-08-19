# Plan 38 — Guest checkout

**Date:** 2026-08-19. **Status:** BUILT + VERIFIED in dev; uncommitted, not deployed.

## Why

Customer feedback: people abandon at the forced sign-in. Hammed decided (2026-08-19) to
reverse **Decision 7** (master-tokerebuild.md — "Checkout REQUIRES an account",
2026-07-12) and allow checkout with just **email + phone** plus an inline address.
Decision 7's amendment lives in master-tokerebuild.md; this doc is the design record.

Settled product choices (Hammed, 2026-08-19):
- **Pure guest + auto-claim.** No shadow accounts, no set-password-at-confirmation.
  Guest orders attach to an account when that email is verified (existing
  `claim_legacy_orders`), now ALSO claimed at login for already-verified accounts.
- **No referral commission on guest orders.** `_refuse_attribution` keeps refusing
  anonymous buyers; revisit once guest volume is known.
- **All payment methods for guests**, including manual bank transfer.

## What was already guest-ready (verified)

- Carts: `Cart.user` nullable, guest identity = cart UUID via `X-Cart-Id`,
  `merge_guest_cart` on login. Cart endpoints AllowAny.
- Orders: `Order.user` nullable, `email`/`phone` plain fields, address JSON snapshots,
  emails send to `order.email`, `_customer_name` reads the snapshot.
- Signed tracking link + public redacted `/orders/[number]?token=` page.
- Coupons: per-user limits already fall back to `email__iexact`; `CouponRedemption.user`
  nullable.
- GIG capture reads the order snapshot, never the Address row.

## Design (post-dissent — a Fable dissent review changed three things)

1. **Durable idempotency key is namespaced for guests** (dissent BLOCKER 1). The
   backstop `Payment.objects.filter(idempotency_key=key, order__user=user)` becomes
   `user IS NULL` for guests — any guest could replay any other guest's key and read
   back their payment envelope. Fix: for guests the stored/looked-up key is
   `sha256("guest:{cart_id}:{client_key}")` (64 hex chars = the column width); the
   Redis namespace is `"guest:{cart_id}"` in place of `user.id`. Authed path unchanged.
   Guest retry (`/orders/{n}/pay/`) namespaces on `"guest-pay:{order_number}:{key}"`.
2. **Claim at login too** (dissent BLOCKER 2). `claim_legacy_orders` ran only at
   email-verify and password-reset-confirm — an EXISTING verified customer who
   guest-checks-out would never see the order in their account. `LoginView` now claims
   for users with `email_verified_at` set. Never claim at placement: the guest email is
   unproven there (order-history injection).
3. **Idempotency replay is checked BEFORE Turnstile** (dissent SERIOUS 3). Turnstile
   tokens are single-use; the same-key retry paths (gateway-502 resume, lost-201
   replay) would 403 at `require_turnstile` before the replay could answer. Order in
   the guest CheckoutView: `begin()` → replay? return stored 201 (no Turnstile — a
   replay does no work) → `require_turnstile` → `place_order`. The storefront resets
   the widget after every completed attempt (same `attempts` signal as SignInStep) so
   a real retry carries a fresh token.
4. **Guest order token in an httpOnly cookie, never the gateway return URL** (dissent
   SERIOUS 4). Paystack's dashboard-callback fallback drops our query string, so a
   token-in-URL guest could never verify the payment they just made. The checkout BFF
   sets `guest_order` (httpOnly, 7 days) from the 201's `guest_order_token` and strips
   the token from the browser response. New salt `orders.guest`, **7-day** TTL (the
   token opens the FULL order view + payment verify — strictly more than the 90-day
   redacted tracking token, which is unchanged). Token names the order; the URL never
   gets a vote.
5. **Guest quoting endpoints are POST** (dissent SERIOUS 7 — no PII in access logs)
   and require a non-empty guest cart (plausibility gate against anonymous GIG
   cache-busting; dissent SERIOUS 5). Kept as SEPARATE views
   (`/checkout/guest/delivery-options|gig-centres|quote/`) so the authed paths are
   untouched on a live store.
6. **Anti-mail-cannon** (dissent SERIOUS 6): guest place-order gets an email-keyed
   throttle (`guest_checkout_email` 6/hour) + loose IP throttle
   (`guest_checkout_ip` 60/hour, direct-to-API volume only — shared-egress caveat as
   ever), plus Turnstile per order. The storefront guest form double-enters email
   (typo protection — a typo'd bank-transfer guest is otherwise unreachable).
7. **Inline address = unsaved `Address` instance** built from
   `AddressSerializer(data=...)` with `instance=None` (so the LGA-required rule
   applies), threaded through `priced_options_for_address` and `_address_snapshot`.
   No schema change; no Address row is written. Billing = shipping for guests, v1.
8. **Guest quote threads the guest email** into `validate_coupon` (dissent MINOR 11)
   so the preview and place_order agree on per-email coupon limits.
9. Referrals: no change needed — `_refuse_attribution` already refuses `user=None`.
10. Buy Now works for guests: `BuyNowView` → AllowAny + `get_or_create_cart` (which
    already handles guests); the BFF forwards/persists the cart cookie.

## Surfaces touched

Backend: `orders/tokens.py` (+guest salt), `checkout/serializers.py`,
`checkout/services/checkout.py`, `checkout/views.py` (+3 guest views), `checkout/urls.py`,
`payments/views.py` (verify token path), `orders/views.py` (full-view guest_token
branch), `accounts/{views,claims,throttling}.py`, `config/settings/base.py`,
`orders/models.py` comment.

Storefront: `CheckoutContext` (+guest selections), `SignInStep` (continue-as-guest),
`AddressStep` (guest inline form, validated via the guest delivery-options call),
`DeliveryStep`/`ReviewStep` guest branches (+Turnstile on Review for guests),
BFF `api/checkout` (guest branch + cookie), `api/checkout/quote`, new
`api/checkout/guest-delivery-options` + `api/checkout/guest-gig-centres`,
`api/checkout/verify` (cookie fallback), `api/checkout/buy-now` (guest),
confirmation page guest branch (+copy), `lib/auth.ts` (+`GUEST_ORDER_COOKIE`),
`lib/orders.ts` (+guest fetcher), `BuyButtons`.

## Known residuals (named, accepted)

- Guest quote endpoints ride the global anon throttle (store-wide shared bucket); the
  real per-client volume cap still belongs at the Vercel/Cloudflare edge (same
  standing gap as login).
- A guest order claimed later by account A while a stranger holds the 7-day guest
  cookie: the cookie still opens the full order view until expiry. Same trust class
  as the emailed tracking link; accepted.

## Gap fixes (2026-08-19, same day — Hammed's ask before deploy)

Closed the two pre-existing gaps the first pass named:

1. **Pay-again UI (the FW-cert open item).** New `PayAgain.tsx` island on BOTH the
   account order page and the confirmation page whenever `status == pending_payment`
   — it re-uses the machinery that already existed but was only reachable mid-checkout:
   `PaymentMethodSwitch` (gained `excludeCurrent=false` — from an order page, retrying
   the same method is a fine first choice — and a `country` prop so the methods list
   follows the ORDER's market, not the browsing cookie) feeding `PaymentLauncher`
   (online) or the bank-handoff stash (transfer switch). `OrderSerializer` gained
   `country` (the market code) for that. The pay BFF route accepts the guest-order
   cookie (token forwarded in the body; authed session wins over a stale cookie),
   riding the guest token path built into `OrderPayView` in the first pass. Copy is
   status-aware: bank-transfer orders get "Prefer to pay another way?" under their
   instructions; online orders get "Payment not completed?" (which may be webhook
   lag, so it never presumes failure).
2. **The failed-redirect dead end.** `CheckoutReturn`'s failed state no longer links
   "Back to checkout" (placement converted the cart → "Your cart is empty" for
   someone holding a real unpaid order); it links to
   `/checkout/confirmation/{number}`, which now carries PayAgain and opens for authed
   sessions and guest cookies alike. The bare `/checkout` link survives only as the
   fallback when verify returned no order number.

Verified live in dev (order TC-100094, guest cookie): re-pay to Paystack minted
attempt `TC-100094-P63` (per-attempt reference suffix working), same-key replay
resumed it, bank-transfer switch returned instructions, no-cookie 401, confirmation
page renders the surface, order detail serves `country`.

## STATUS

- 2026-08-19: plan written after an Explore survey + Fable dissent review (3 findings
  folded in, listed above).
- 2026-08-19: BUILT, backend + storefront, all in one pass. Verified:
  - Backend: FULL suite green (2850 passed, 3 skipped) including 21 new tests in
    `apps/checkout/tests/test_guest_checkout.py` (placement, snapshot, cross-guest
    key isolation, Turnstile ordering incl. replay-without-reverify, guest quote
    twins + field errors + per-email coupon limit, token-scoped verify/pay/detail
    with salt-confusion refusals, claim-at-login verified/unverified, guest Buy Now).
  - Storefront: eslint clean; vitest 131 files / 938 tests green (3 old "guests get
    401" BFF tests rewritten to the new guest contract, +5 new BFF tests, +2
    SignInStep guest tests); `next build` compiles; `tsc --noEmit` adds no errors
    beyond the 7 pre-existing in proxy.test.ts on HEAD.
  - LIVE dev E2E through the real BFF (backend runserver + next dev, curl-driven):
    anonymous add-to-cart → guest delivery options (Lagos ₦1,800 priced) → address
    field-error pass → guest quote (₦20,300) → place with dev Turnstile test pair →
    **TC-100094** (bank_details, token stripped from body, httpOnly `guest_order`
    cookie set) → same-key replay returns same order → confirmation page 200 with
    the create-account nudge (307 bounce without the cookie) → verify via cookie →
    fresh-guest Buy Now mints + persists a cart. TC-100094 is a kept dev artifact.
- 2026-08-19 (later): the two gap fixes (see "Gap fixes" section) BUILT + VERIFIED —
  full backend suite 2850 passed / 3 skipped, full storefront suite 132 files / 944
  tests, `next build` compiles, tsc adds nothing beyond the 7 pre-existing
  proxy.test.ts errors, plus the live dev pay-again E2E on TC-100094. New/updated
  tests: PayAgain.test.tsx (3), pay.test.ts (+2 guest, 1 updated), CheckoutReturn
  (failed-link assertions +1), account order page mock gained useRouter,
  test_guest_checkout asserts the serializer's `country`.
- NOT done (deliberately): commit/tag/deploy — on Hammed's word, as always. Deploy =
  backend tag + BOTH Vercel apps. No admin-app changes were needed.
