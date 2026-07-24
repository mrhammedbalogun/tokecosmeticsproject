# Plan-14b — Online payments (Paystack, Flutterwave, PayPal) on the checkout — Design

**Status:** Approved by Hammed 2026-07-24 (gateway scope, menu ordering, test-mode framing, **Approach: Hybrid** — Paystack + PayPal inline pop-ups, Flutterwave redirect). Ready for implementation-plan authoring.

> **History:** an earlier draft of this spec chose Approach A (uniform redirect + verify-on-return).
> After reading the three adapters, Hammed chose the **Hybrid**: give the two gateways that support
> inline cleanly (Paystack, PayPal) a native pop-up so the customer never leaves the site, and leave
> Flutterwave on the redirect it's already built for — avoiding a new Flutterwave public key, a
> client-supplied amount, and a redundant server call. See "Approach" below.

## Goal

Turn on the three online payment gateways — **Paystack + Flutterwave** (Nigeria) and **PayPal**
(international) — on the storefront checkout, and drive the deferred Plan-09 sandbox certification for
each. Bank transfer stays a customer-facing fallback everywhere. This is done **in test mode on the
preview site**: no real card is charged by this work. Live keys + one small real transaction per
gateway happen later, at cutover (Plan-27 §4).

## Scope (decided)

- **In:** reactivate the three gateways per country; **Paystack + PayPal collect money in an on-page
  pop-up** (no redirect); **Flutterwave redirects** to its hosted page and confirms on return; thread a
  server-built return URL for the Flutterwave redirect; expose the PayPal order id to the client;
  certification of all three in test mode; Hammed does a test purchase on his phone.
- **Out:** Stripe (dropped in Plan-14; stays code-complete but deactivated). **Flutterwave inline**
  (`FlutterwaveCheckout`) — deliberately not done: it needs a new public key and a client-supplied
  amount for marginal gain on the *secondary* NG rail. Live keys / real money (cutover). Any change to
  the manual bank-transfer flow.

## Approach (decided: Hybrid — inline where clean, redirect where not)

Each gateway uses the collection mechanism it is already built for, chosen per what its adapter returns:

| Gateway | Mechanism | Why | What the client uses |
|---|---|---|---|
| **Paystack** (NG primary) | **Inline pop-up** — `@paystack/inline-js` `resumeTransaction(access_code)` | The adapter **already returns `access_code`** in `init.data`; the pop-up needs nothing else. Highest-volume rail gets the best UX for ~zero backend cost. | `payment.data.access_code` |
| **PayPal** (international) | **Inline Buttons** — PayPal JS SDK `createOrder`/`onApprove` | The adapter **already creates the v2 order** and `verify()` already captures an `APPROVED` order. Buttons need the order id + a public client-id. | `payment.data.order_id` + `NEXT_PUBLIC_PAYPAL_CLIENT_ID` |
| **Flutterwave** (NG secondary) | **Redirect** — hosted page → return page → verify | Inline would need a **new public key** and a **client-supplied amount**; not worth it on the secondary rail. Its adapter already returns a hosted-page `redirect_url`. | `payment.data.redirect_url` |
| **Bank transfer** | Unchanged | Zero-fee fallback in every market. | `action="bank_details"` handoff |

**All three confirm money the same way:** the customer-side outcome (pop-up success callback, Buttons
`onApprove`, or return-page load) calls the **already-built** `POST /api/v1/payments/{reference}/verify/`,
which runs the same `confirm_payment()` the webhook runs. The happy path never waits on a webhook, and
there are **no client-side gateway *secret* keys** — only public keys/client-ids that are designed to be
public. The webhook remains the idempotent backstop.

**Why not full inline (all three)?** Flutterwave's `FlutterwaveCheckout` is entirely client-driven: it
needs a new `FLUTTERWAVE_PUBLIC_KEY` surfaced to the browser, the amount pushed from the client (a new
tampering wrinkle — guarded server-side, but new), and it makes the adapter's existing `/v3/payments`
call dead weight. The hybrid keeps the amount **server-fixed for every gateway** (Paystack access_code
and PayPal order are both minted server-side) and adds no new secret surface.

## Menu (decided)

Read from `CountryPaymentGateway` (active rows, sort order). After reactivation:

- **NG:** Paystack (sort 1, default) · Flutterwave (sort 2) · Bank transfer (sort 3)
- **GB / US / CA / ZZ:** PayPal (sort 1, default) · Bank transfer (sort 2)

Bank transfer stays `is_active=True` in every market as a zero-fee fallback. The storefront preselects
the lowest sort_order visually (already implemented in `PaymentStep`).

## Hard constraints (verified against the current code)

- **Backend checkout is already complete for networked gateways.** `POST /api/v1/checkout/` calls
  `_initiate_payment()` → `gateway.initiate()` and returns
  `{order_number, payment:{gateway, action, data}}` (`apps/checkout/views.py:143-153`,
  `services/checkout.py:186-194`). `action` is always `"redirect"` for these three today; `data` is
  `init.data`. Deactivation (migration `0007`) only gates the `/payment-methods/` menu and the
  chosen-gateway validation; the initiation plumbing behind it is live.
- **`payment.gateway` is in the response** (`views.py:147`) — the storefront dispatches on it. The
  storefront must **not** rely on `action` to tell inline from redirect (all three say `"redirect"`);
  it branches on the gateway code. `action="bank_details"` still distinguishes the bank handoff.
- **Paystack already returns what inline needs.** `paystack.py:69` returns
  `data={"redirect_url": ..., "access_code": ...}`; `access_code` is exactly what
  `@paystack/inline-js` `resumeTransaction()` consumes. **No adapter change.**
- **PayPal already creates the order.** `paypal.py:92-122` POSTs a v2 CAPTURE order and returns its id
  as `init.reference`, but `init.data` is only `{"redirect_url": approve}` — the **order id is not in
  `data`**, so the Buttons SDK can't see it. This is the **one adapter change** (below).
- **PayPal capture-on-verify already exists.** `verify()` captures an `APPROVED`-but-uncaptured order,
  then re-reads it (`paypal.py:136-161`) — so the Buttons `onApprove` → `verify/` path both captures and
  confirms with the code that's already there. Safe to retry (repeat capture → still reports COMPLETED).
- **Return-verify endpoint exists.** `POST /api/v1/payments/{reference}/verify/`
  (`apps/payments/views.py` `PaymentStatusView`, `IsAuthenticated`, scoped to the requesting user's own
  orders) re-verifies with the gateway and returns `{order_number, order_status, payment_status}`.
  Idempotent against the webhook. Reused unchanged by both the inline callbacks and the Flutterwave
  return page.
- **Retry path exists.** A failed/expired attempt re-initiates on the same order by bumping
  `reservation_reference` to the next attempt suffix, then reserve+commit (Plan-09). The storefront's
  retry reuses the existing place/verify calls; no new backend logic.
- **Amount/currency guard exists.** `confirm_payment()` flags the order `needs_review` and does **not**
  fulfil if `verify()`'s amount/currency ≠ the order total. No new work; must stay covered. In the
  hybrid the amount is server-fixed for all three, so this guard is defence-in-depth, not the primary
  control.
- **Flutterwave needs a return URL.** `_initiate_payment()` currently calls `initiate(payment, order)`
  **without** a `return_url` (`services/checkout.py:190`), so a redirected Flutterwave customer has
  nowhere to come back to. Flutterwave's adapter already wires `return_url` → `redirect_url`
  (`flutterwave.py:76-77`); it just needs to be supplied. Paystack (`callback_url`) and PayPal
  (`return_url`/`cancel_url`) also accept it — harmless to pass uniformly; their inline flows ignore it.
- The browser never holds a JWT: all authed calls go through Route Handlers / `fetchWithAuth`
  (Plan-12/14 pattern). The verify call is authed → it goes through a BFF route, not directly from the
  client.

## Architecture

### Backend (four small changes)

1. **Reactivation data migration** (`apps/payments/migrations/000N_reactivate_online_gateways.py`),
   reversible:
   - `CountryPaymentGateway`: set `is_active=True` and the sort orders above for `paystack`+`flutterwave`
     on NG and `paypal` on GB/US/CA/ZZ. Leave `bank_transfer` untouched (already active).
   - Reverse = set those rows back to `is_active=False` (mirrors `0007`'s intent; reactivation is
     otherwise a human checkpoint, so a rollback must be able to switch them off).
   - **Note:** activation is safe because these are test keys and the production storefront is not cut
     over — no real money is reachable. Live go-live is a separate, gated step (Plan-27).
2. **Expose the PayPal order id to the client.** In `paypal.py` `initiate()`, add the order id to the
   result data: `data={"redirect_url": approve, "order_id": body["id"]}`. `order_id` is what the
   Buttons SDK's `createOrder` returns. (It equals `init.reference`, but the client contract is "the SDK
   reads everything from `payment.data`", so it lives in `data` too.) One line; covered by
   `test_paypal.py`.
3. **Server-built return URL (for the Flutterwave redirect).** In `_initiate_payment()`, build
   `return_url = f"{settings.STOREFRONT_BASE_URL.rstrip('/')}/checkout/return?ref={order.reservation_reference}"`
   and pass it to `initiate(payment, order, return_url=...)`. **Security:** the URL is constructed
   server-side from a trusted setting and the order's own reference — never accepted from the client (a
   client-supplied return URL is an open-redirect / tampering vector). Passed uniformly to all gateways;
   only Flutterwave acts on it. `STOREFRONT_BASE_URL` is a new setting (env-driven; dev = preview URL).
   Bank transfer ignores `return_url` (no behaviour change).
4. **Add `payment.reference` to the checkout `201` body** (`checkout/views.py:144-151`):
   `"reference": result.payment.gateway_reference`. This is the value the verify endpoint keys on; the
   `PaymentLauncher` and Flutterwave return page use it uniformly. One line. (See O1.)

### Config

- **Secret settings already exist** for every gateway (`base.py:217-226`: `PAYSTACK_SECRET_KEY`,
  `PAYSTACK_PUBLIC_KEY`, `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_SECRET_HASH`, `PAYPAL_CLIENT_ID`,
  `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_API_BASE` — the last already defaults to the
  PayPal **sandbox** base). Plan-14b populates the `.env` **test-mode** values (never committed) and
  documents them in Appendix A.
- **Client-exposed public keys** (safe in the browser by design):
  - `NEXT_PUBLIC_PAYPAL_CLIENT_ID` — loads the PayPal JS SDK. Sandbox client-id in test mode; the
    SDK's live/sandbox behaviour is determined by the client-id itself.
  - **Paystack needs no public key client-side** — `resumeTransaction(access_code)` uses the
    server-minted access code, so `PAYSTACK_PUBLIC_KEY` stays server-only/unused here.
  - **No Flutterwave public key** — Flutterwave stays redirect, so nothing Flutterwave is exposed to
    the browser. (This is the concrete saving vs. full inline.)
- **One new backend setting:** `STOREFRONT_BASE_URL` (env-driven; the preview URL in dev/staging) —
  used only to build the Flutterwave return URL.
- Adapters read keys lazily and raise `GatewayNotConfigured` (→ 503) if a gateway is enabled before its
  keys are deployed — fail-safe.

### Storefront

**Third-party scripts (new surface on the checkout page — treat as security-relevant):**
- PayPal JS SDK (`https://www.paypal.com/sdk/js?client-id=…&currency=…&intent=capture`) — loaded only
  when PayPal is the selected/available gateway.
- Paystack inline-js (`https://js.paystack.co/v2/inline.js`, or the `@paystack/inline-js` npm package
  bundled — **prefer the npm package** so the version is pinned and it's covered by our lockfile/SRI
  posture rather than a runtime CDN fetch on the money page).
- Both must have a **load-failure fallback**: if the SDK fails to load or the pop-up can't open, show a
  retryable error and surface "choose another method" (bank transfer is always available) — never a dead
  button. CSP `script-src` must allowlist the PayPal origins (and `js.paystack.co` if the CDN route is
  taken).

**Pages / components**
- `src/components/checkout/PaymentStep.tsx` — **no logic change**; it already renders whatever
  `/payment-methods` returns. Confirm `paymentLabel` (`src/lib/payment-labels.ts`) has friendly copy for
  `paystack` / `flutterwave` / `paypal` (add labels if missing).
- `src/components/checkout/ReviewStep.tsx` — extend the `201` handler (currently
  `ReviewStep.tsx:200-206`, which only stashes bank handoff → confirmation). Dispatch on the response:
  - `action === "bank_details"` → **unchanged** (`stashBankHandoff` → push to confirmation).
  - otherwise (online) → hand `{gateway, data, reference}` to a new **`PaymentLauncher`** (below), where
    `reference` is the new `payment.reference` field in the 201 body (= `gateway_reference` — see O1).
- **New** `src/components/checkout/PaymentLauncher.tsx` — the per-gateway collection switch. It is the
  one place that knows gateway-specific SDK glue. Every branch confirms via the **same uniform field**
  `payment.reference` (= `gateway_reference`, added to the 201 body — see O1):
  - **paystack** → open the inline pop-up with `data.access_code`. On success callback → BFF
    `verify(reference)` → `router.replace('/checkout/confirmation/' + <order_number from verify>)`. On
    the customer closing the pop-up → a "Payment not completed" state with **Retry** (re-run place-order
    for the same cart) and "choose another method".
  - **paypal** → render Buttons; `createOrder: () => data.order_id`; `onApprove` → BFF
    `verify(reference)` → confirmation; `onCancel`/`onError` → the same not-completed/retry state.
  - **flutterwave** → `window.location.assign(data.redirect_url)`. **No stash needed** (see below).
    Guard a missing `redirect_url` (retryable error, never navigate to `undefined`).
- **New** `src/app/(shop)/checkout/return/page.tsx` — **only Flutterwave returns here** (`?ref=<reference>`).
  `?ref` is the `reservation_reference` we baked into the server-built return URL, which equals
  `gateway_reference` for Flutterwave — so it's exactly what verify keys on. The page calls the BFF
  verify route with `ref` and reads `order_number` **from the verify response** (no stash). It polls:
  - `succeeded` → `router.replace('/checkout/confirmation/<order_number>')`.
  - `failed` / `cancelled` → an inline "Payment didn't go through" state with a **Retry** button and a
    "choose another method" link back to checkout.
  - still `pending`/`initiated` after ~N polls (e.g. 5 tries over ~15s) → a calm "We're confirming your
    payment — you'll get an email as soon as it clears" terminal state (the webhook reconciles later).
    Never spins forever.
- **New** BFF route `src/app/api/checkout/verify/route.ts` — authed passthrough to
  `POST /api/v1/payments/{reference}/verify/` via `fetchWithAuth`. Takes `{reference}` from the body; the
  browser never calls the backend directly. Used by both the inline callbacks and the return page.

**Reference persistence.** No sessionStorage stash is needed for any gateway. Inline (Paystack/PayPal)
keeps `reference` in component memory across the pop-up; Flutterwave's return page gets `reference` from
`?ref` and `order_number` from the verify response. (This is a simplification vs. the earlier draft —
the verify endpoint returning `order_number` removes the mapping problem entirely.)

> **⚠️ Next.js note:** this storefront runs a modified Next.js — read the relevant guide in
> `node_modules/next/dist/docs/` before writing the `<Script>`/return-page/route-handler code
> (`storefront/AGENTS.md`). Don't assume App-Router APIs match public docs.

## Flow

### Inline (Paystack / PayPal), happy path
1. Customer picks Paystack (NG) or PayPal (intl) in step 4, clicks **Place order** in step 5.
2. `POST /api/checkout` → backend creates order + payment, `initiate()` runs; response carries
   `gateway` + `data` (Paystack `access_code`, PayPal `order_id`).
3. `PaymentLauncher` opens the on-page pop-up / Buttons — **the customer never leaves the site.**
4. Customer pays (Paystack test card / PayPal sandbox). Success callback / `onApprove` fires client-side.
5. Client → BFF → `verify/` runs `confirm_payment()` (PayPal: captures then confirms): order →
   `processing`, stock committed, confirmation email enqueued.
6. `PaymentLauncher` routes to the confirmation page.

### Redirect (Flutterwave), happy path
1. Customer picks Flutterwave, clicks **Place order**.
2. Backend `initiate()` returns `data.redirect_url` (hosted page).
3. `PaymentLauncher` stashes `{order_number, reference}`, redirects to the hosted page.
4. Customer pays; Flutterwave redirects to `/checkout/return?ref=<reference>`.
5. Return page → BFF → `verify/` → `confirm_payment()` → confirmation.

**Webhook** (if it arrives first or the customer never returns/closes the pop-up) does the same
`confirm_payment()` — idempotent, so it's a benign race for all three.

## Verification

**Automated (must stay green):**
- Existing backend payments/checkout suites (adapters, webhooks, refunds, initiate-failure→retry,
  amount-mismatch→needs_review) — unchanged, must remain green.
- New backend: reactivation migration test (three gateways active with correct sort per country; bank
  transfer still active); PayPal `initiate()` includes `order_id` in `data` (respx); `_initiate_payment`
  passes a correctly-built `return_url` that reaches Flutterwave's payload and is **never** sourced from
  request data.
- New storefront: `ReviewStep` dispatch (bank_details vs online); `PaymentLauncher` per-gateway
  (paystack success→verify→confirmation, cancel→retry; paypal onApprove→verify→confirmation,
  cancel→retry; flutterwave→redirect + stash); SDK load-failure fallback; return-page polling states
  (succeeded→confirmation, failed→retry, pending→email-us); BFF verify route authed passthrough.

**Manual test-mode certification (the deferred Plan-09 checkpoint — the real risk):**
- One full test-mode payment **through the real preview UI** per gateway: **Paystack inline pop-up**
  (test card), **PayPal sandbox Buttons**, **Flutterwave redirect** (test card) — from Place-order →
  collect → confirmation, verifying the order flips to `processing` and stock commits.
- Prove each gateway's **webhook signature path** once (temporary tunnel, e.g. cloudflared, or the
  gateway dashboard's webhook simulator) so the live webhook is known-good — not gating checkout, but
  must be shown to work.
- NG (Paystack/Flutterwave) and an international context (PayPal) both walked; **mobile viewport**; a
  cancelled/closed-pop-up retry; bank transfer still works as the fallback in each market.

## Checkpoint

Hammed does a **test-mode** purchase himself on his phone through each of the three gateways on the
preview site, sees the order confirm. Explicit sign-off that (a) all three certify, (b) bank transfer
still works as fallback, (c) he understands no real money moves until live keys at cutover.

## Risks / things to watch (flagged per Hammed's review preference)

- **Third-party JS on the money page (new in the hybrid).** Paystack inline-js + PayPal SDK now load on
  checkout. Mitigations: prefer the pinned npm package over a runtime CDN fetch; CSP allowlist; a
  hard load-failure fallback to a retry + bank-transfer path (never a dead pay button). Call this out in
  review.
- **Pop-up / Buttons never resolves** (customer closes, SDK error) — every inline path must reach a
  terminal state: success→confirmation, close/error→retry-or-choose-another. No infinite spinner. The
  webhook still reconciles a genuinely-paid-but-abandoned session.
- **Open-redirect via return URL (Flutterwave)** — mitigated: URL is server-built from a trusted setting
  + the order's own reference, never client input. Call this out explicitly in review.
- **Accidental real charge** — mitigated: test keys only, `PAYPAL_API_BASE` = sandbox, sandbox PayPal
  client-id, production storefront not cut over. The reactivation migration touches only `is_active`;
  going live is a separate gated step.
- **Amount/currency mismatch** — already handled (`needs_review`, no fulfilment). In the hybrid the
  amount is server-fixed for all three (Paystack access_code, PayPal server order, Flutterwave hosted
  page), so there is **no client-supplied amount** — this guard is defence-in-depth. Keep the test.
- **Stuck "pending" UX (Flutterwave return)** — the return page must always reach a terminal state
  (bounded polls → "we'll email you"), never an infinite spinner.
- **Reference/order mapping** — no longer a risk (O1): verify keys on `gateway_reference` and returns
  `order_number`, so the client never has to persist a mapping. Uniform `payment.reference` field.
- **Webhook not on the critical path** but must still be signature-verified — already unit-tested; prove
  once live-style during certification so a future spoofed webhook can't fulfil an order.

## Open items to resolve in the implementation plan

- **O1 — expose the payment reference to the client. ✅ RESOLVED.** The verify endpoint keys on
  `payment.gateway_reference` (`payments/views.py:47-50`) and its response returns `order_number`. The
  checkout `201` body currently has `gateway/action/data` only, so **add `payment.reference`
  (= `gateway_reference`) to the body** — one line in `checkout/views.py:144-151`, alongside change #2.
  Every `PaymentLauncher` branch then uses one uniform `reference` field, and no sessionStorage stash is
  needed anywhere (verify returns `order_number`). This is now a backend change (#4 below), not an open
  question.
- **O2 — Paystack inline delivery.** Decide npm `@paystack/inline-js` (preferred: pinned, no runtime CDN
  on checkout) vs. the `js.paystack.co` script tag. Affects CSP and the load-failure fallback shape.
- **O3 — PayPal SDK currency.** The SDK loads per-currency; confirm the intl markets (GBP/USD/CAD/EUR)
  and whether one SDK load with a currency param per order is sufficient or a reload is needed on
  currency change.

## Appendix A — required `.env` (test mode; never committed)

| Setting | Where | Notes |
|---|---|---|
| `PAYSTACK_SECRET_KEY` | backend | test secret |
| `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_SECRET_HASH` | backend | test secret + webhook hash |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` | backend | sandbox app creds + webhook id |
| `PAYPAL_API_BASE` | backend | already defaults to sandbox |
| `STOREFRONT_BASE_URL` | backend | **new** — preview URL, for the Flutterwave return URL |
| `NEXT_PUBLIC_PAYPAL_CLIENT_ID` | storefront | **new** — sandbox client-id for the Buttons SDK |
