# Plan-14b — test-mode certification runbook (Phase D)

Everything in Phases A–C is built, tested and committed on `plan-14b-online-payments`.
What remains is **manual** and needs a human with the gateway dashboards: Tasks 15–18 of
`docs/superpowers/plans/2026-07-24-plan-14b-online-payments.md`.

> **No real money moves at any point in this runbook.** Every key below is test/sandbox.
> Going live is a separate gated step (Plan-27).

---

## Status — 2026-07-24

| Gateway | Keys | Task 16 (UI payment) | Task 17 (webhook) |
| --- | --- | --- | --- |
| **Paystack** (NG) | ✅ test key configured | ✅ **certified** — TC-100041 → `processing` | ✅ **signature + idempotency certified**; one Paystack-*originated* delivery still owed (needs the dashboard URL — do it at deploy) |
| **Flutterwave** (NG) | ✅ test key configured 2026-08-12 | ✅ **certified 2026-08-12** — TC-100052 → `processing`; decline + same-order recovery on TC-100056 | ✅ **verif-hash + idempotency certified 2026-08-12** over a cloudflared tunnel; one Flutterwave-*originated* delivery still owed (dashboard webhook URL + secret hash — do it at deploy) |
| PayPal (intl) | ⬜ no credentials yet | ⬜ | ⬜ |
| Bank transfer | n/a | ✅ still works — TC-100042 | n/a |

Confirmation emails from the Task 16 orders all landed at
`billztechnologiesofficial+paystacktest1@gmail.com` — confirmed by Hammed 2026-07-24.

Hammed's call (2026-07-24): Flutterwave and PayPal stay **switched on** in their markets
while unconfigured, so customers choosing them get a 503 until the keys land. CA/US
likewise stay without a `BankAccount`. Both are known and deliberate — see "Known gaps".

**Three bugs were found by driving this, all fixed:**

1. **Paystack amount reconciliation** (launch blocker). The Paystack dashboard has
   *customers bear transaction fees* ON, so the customer is debited the order total plus
   the fee and `verify.amount` never equalled the order total — every Paystack order was
   flagged `needs_review` and none were fulfilled (TC-100039). The adapter now reconciles
   against `requested_amount`. **Business decision still open for Hammed:** whether to keep
   customers bearing the fee (they pay ~2.2% more than the price shown at checkout) or
   switch it off in Settings → Preferences so Toke absorbs it. The code is correct either
   way — this is purely about who pays.
2. **Confirmation page told card customers to make a bank transfer.** It hardcoded
   bank-transfer copy from Plan-14. `OrderSerializer` now reports `payment_gateway`.
3. **Every delivery option showed "undefined days"** — the storefront read `eta_min_days`,
   the API sends `min_days`.

---

## Task 15 — configure test-mode keys

### 15.1 Backend — `backend/.env` (never committed)

Add these. Values come from each gateway's dashboard **with the dashboard in test mode**.
`backend/.env.example` carries the same list with notes.

The variable **names** matter — Django reads exactly these. Keys pasted under any other
name (`Paystack_Test_Secret_Key`, say) are silently ignored and the gateway stays
unconfigured. `PAYSTACK_PUBLIC_KEY` is *not* needed by this integration: we price the
transaction server-side and resume it with an access code, so the browser never holds a
Paystack key. Nothing Paystack belongs in `storefront/.env.local`.

| Variable | Where it comes from |
| --- | --- |
| `PAYSTACK_SECRET_KEY` | Paystack dashboard → Settings → API Keys & Webhooks → **Test** secret key (`sk_test_…`) |
| `FLUTTERWAVE_SECRET_KEY` | Flutterwave dashboard → Settings → API → **Test** secret key (`FLWSECK_TEST-…`) |
| `FLUTTERWAVE_SECRET_HASH` | You choose it. Paste the same long random string into the dashboard's webhook "verif-hash" field |
| `PAYPAL_CLIENT_ID` | PayPal Developer → Apps & Credentials → **Sandbox** → your app → Client ID |
| `PAYPAL_CLIENT_SECRET` | Same app → Secret |
| `PAYPAL_WEBHOOK_ID` | Same app → Webhooks → the webhook's ID (required to verify signatures) |
| `STOREFRONT_BASE_URL` | The origin the customer actually browses. `http://localhost:3000` locally; the **preview URL** once deployed |

Leave `PAYPAL_API_BASE` alone — it already defaults to sandbox.
Do **not** set any `STRIPE_*` key: Stripe was dropped in Plan-14 and is inactive everywhere.

### 15.2 Storefront — `storefront/.env.local` (never committed)

```
NEXT_PUBLIC_PAYPAL_CLIENT_ID=<the same sandbox client id as PAYPAL_CLIENT_ID>
```

This one is public by design — it ships to the browser. The **client secret must never**
appear in the storefront. Without this value the PayPal option reports a failed attempt
instead of rendering buttons.

### 15.3 Verify the keys landed

```bash
cd backend && .venv/Scripts/python.exe manage.py check
```

`payments.W001` now warns **only** for a gateway that is switched on in a market but
missing its keys, and it names those markets. When all three are configured, the only
warning left should be `payments.W002` for `CA, US` (see "Known gaps" below).

Before configuring, it reads:

```
(payments.W001) Payment gateway 'flutterwave' is active in NG but is not configured (missing: …)
(payments.W001) Payment gateway 'paypal' is active in CA, GB, US, ZZ but is not configured (missing: …)
(payments.W001) Payment gateway 'paystack' is active in NG but is not configured (missing: …)
(payments.W002) bank_transfer is active but has no BankAccount for: CA, US
```

### 15.4 Confirm every value is test/sandbox

Open each dashboard and confirm it is in **test/sandbox** mode before driving a payment.
A live secret key in `backend/.env` would take real money on the very first test order.

Two checks that do not need a dashboard:

```bash
cd backend && .venv/Scripts/python.exe manage.py shell -c "from django.conf import settings; print(settings.PAYSTACK_SECRET_KEY[:8])"
```

must print `sk_test_`. And Paystack's own verify response carries `"domain": "test"` on a
test transaction — that is the authoritative answer for a payment that already happened.

Keep live keys out of the dev env entirely. `backend/.env` holds the live pair commented
out under a DO-NOT-ENABLE banner purely so the values are not lost; going live happens in
the production environment (Plan-27), never by uncommenting them here.

### 15.5 Deploy the branch to preview

Set the same variables in the preview environment, with `STOREFRONT_BASE_URL` pointing at
the preview origin — Flutterwave builds its return URL from it, and a stale value sends
the customer back to localhost.

---

## Task 16 — one test-mode payment per gateway, through the real UI

> **Paystack: done 2026-07-24.** TC-100041 — inline pop-up, test-mode "Success", order
> flipped to `processing`, event `status:processing - payment 43 verified via paystack`,
> confirmation page correct. Bank-transfer fallback re-checked on TC-100042. Driven with
> Playwright against the production build on localhost; a **phone** pass is still Task 18.
> Two earlier orders are certification artefacts, not faults: **TC-100039** is the
> pre-fix flagged order (leave it, it is the evidence) and **TC-100040** the first order
> after the fix.

- **Paystack (NG):** place an order → inline pop-up → Paystack **test card** → order flips
  to `processing`, stock commits, confirmation page, confirmation email.
- **PayPal (an international market):** inline Buttons → **sandbox** buyer approves →
  capture → `processing` + email.
- **Flutterwave (NG):** redirect to hosted page → **test card** → back to
  `/checkout/return?ref=…` → `processing` + email.
- **Bank transfer** still works as the fallback in NG and in an international market.
- Walk a **mobile viewport** for at least Paystack and PayPal.
- **Cancel/close** a pop-up (Paystack, PayPal) and a hosted payment (Flutterwave). You
  should land on "Your payment didn't go through", with the order number shown and two
  routes out — **Try again** (re-opens the same attempt) and **Choose another method**
  (opens a new attempt on a different gateway). Confirm both finish the same order rather
  than creating a second one.

## Task 17 — prove each webhook signature path once

- Deliver one signed webhook per gateway (dashboard simulator, or a tunnel such as
  cloudflared) and confirm it verifies and is idempotent against the return-verify: no
  double fulfilment, no error.
- Confirm an amount/currency mismatch still flags `needs_review` and does **not** fulfil.

### Paystack — done 2026-07-24

Driven over a **public URL**, not a test client: `cloudflared tunnel --url http://localhost:8000`
gave `https://<random>.trycloudflare.com`, and every request below crossed the real
internet into `POST /api/v1/webhooks/paystack/`. `cloudflared.exe` was downloaded to the
session scratchpad and never installed — quick tunnels need no Cloudflare account, and the
URL dies with the process.

The webhook body was **Paystack's own data**: the script pulled the live
`transaction/verify/TC-100041` response (`id=6389173914`, `domain=test`, `amount=659899`,
`requested_amount=640000`, NGN) and enveloped it as `charge.success`, then signed the raw
bytes with HMAC-SHA512 of `PAYSTACK_SECRET_KEY` — the exact scheme `parse_webhook` checks.
Note the two amounts in that payload: ₦6,598.99 debited against ₦6,400.00 requested. That
is the fee-bearing overage from bug 1, visible in a real transaction.

| Delivery | Result |
| --- | --- |
| Signature replaced with `0`×128 | **HTTP 400** `invalid_signature`, **no** `WebhookEvent` row written |
| Valid signature | **HTTP 200** `accepted` — one `WebhookEvent`, `kind=payment`, `processed_at` set, `error=""` |
| Same event delivered again | **HTTP 200** `duplicate` — still exactly one ledger row, not reprocessed |
| Unsigned POST (plain curl) | **HTTP 400** `invalid_signature` |

**Idempotency against the return-verify — the point of the exercise.** TC-100041 was
already `processing`, fulfilled minutes earlier by the customer-return verify. After the
webhook:

- order still `processing`, one payment (43, `succeeded`, ₦6,400.00) — no second payment,
  no re-flip;
- order timeline unchanged — still a single `payment 43 verified via paystack`, so
  `confirm_payment` recognised the replay and did nothing;
- `StockMovement` for reference `TC-100041` still exactly two rows — `reservation`
  (+1 reserved) and `sale` (−1 qty, −1 reserved). **No third movement: stock was not
  committed twice.** This is the failure the whole ladder exists to prevent, and it is the
  one thing unit tests with a fake gateway can only approximate.

**Amount/currency mismatch — already proven with real money data, not re-staged.** Both
paths call the *same* `confirm_payment`, so the guard cannot differ between them. Its
real-world evidence is TC-100039, which Paystack really did report differently:

```
status: pending_payment
review_reason: payment 41: gateway reported 14619.29 NGN, order total is 14300.00 NGN — not fulfilling
```

Flagged, and **not fulfilled** — no stock committed, order left awaiting payment. Unit
cover: `test_confirm_amount_mismatch_flags_for_review`,
`test_confirm_currency_mismatch_flags_for_review`, and
`test_verify_reports_the_short_amount_when_the_customer_underpaid` (which is what stops the
bug-1 fix from swallowing a genuine shortfall). Manufacturing a fresh live mismatch would
have meant either corrupting the TC-100039 evidence or hand-editing an order total, so it
was not done.

**Still owed: one delivery that Paystack itself sends.** Everything above proves our
verification is correct; it does not prove Paystack's dashboard can reach us, or that
Paystack signs the same bytes it transmits. That needs the webhook URL pasted into
**Paystack → Settings → API Keys & Webhooks → Test Webhook URL** and one payment driven
afterwards. Since that URL is a per-environment setting Hammed sets again at deploy, it is
folded into Task 18 / the deploy checklist rather than done twice against a throwaway
tunnel. **Trailing slash is required** (`…/api/v1/webhooks/paystack/`) — Django's
`APPEND_SLASH` will not redirect a POST.

Script used: `task17_signed_replay.py` (session scratchpad; read-only against Paystack).

### Flutterwave — done 2026-08-12

Driven headlessly (Playwright, scripts in the session scratchpad) against the dev servers
with the TEST secret key. Keys live in `backend/.env` under the exact names Django reads;
the live pair is parked commented under the DO-NOT-ENABLE banner. `FLUTTERWAVE_SECRET_HASH`
is a generated random string — **at deploy it must be pasted into Flutterwave dashboard →
Settings → Webhooks → Secret hash**, along with the webhook URL
`https://<api-origin>/api/v1/webhooks/flutterwave/` (trailing slash required).

**Task 16 (UI payment)** — order **TC-100052**: checkout → hosted page (branded, test-mode
banner) → MasterCard test card `5531 8866 5214 2950` + PIN 3310 + OTP 12345 → redirect to
`/checkout/return?ref=…` → confirmation, order `processing`. Payment `succeeded ₦2,800`,
Flutterwave transaction id `10427340` persisted in `raw_response.verify.id` (refund-ready).
Exactly two `StockMovement` rows (reservation + sale). Confirmation email for the follow-up
order TC-100056 **delivered** by Resend to a real inbox
(`billztechnologiesofficial+flwcert@gmail.com`); TC-100052's bounced only because the
walkthrough account uses a `.local` address.

**Failure surface** — the insufficient-funds test card (`5258 5859 2266 6506`) produced
Flutterwave's inline decline; nothing was fulfilled and the returning customer sees
"Your payment didn't go through." Their hosted page deliberately stays open on decline
(retry-in-place is their design), and its Cancel/X control never redirected in headless —
the failure screen was certified by returning to `/checkout/return?ref=…` directly, which
is byte-identical to what their `status=failed` redirect does.

**Certification found and fixed a real bug (same-gateway retry 500).** `retry_payment`
creates a new Payment row per attempt, but every real adapter sent the BARE order
reference as the gateway reference → second attempt on the same gateway violated
`uniq_payment_gateway_reference` → HTTP 500 (reproduced live on TC-100056; latent for
paystack and bank_transfer too — the retry tests' fake gateway minted `FAKE-{pk}` refs and
dodged it). Fix (2026-08-12, after a dissent review rejected reusing the payment row):
the **service** now mints references in `_initiate_payment` — bare order reference for the
first goods attempt (the exact bytes Paystack was certified on), `-P<pk>`-suffixed for
retries — persisted BEFORE the gateway call (intent-then-act; a crashed initiate now
leaves the handle to find the half-created transaction). Adapters send
`payment.gateway_reference` verbatim; the durable backstops now key "initiate finished"
off `raw_response` instead of the reference; `confirm_payment` gained a terminal-state
guard (a stale failed verify can never un-succeed a fulfilled payment — Flutterwave allows
several charge attempts per tx_ref, so verify-by-reference answers are ambiguous by
design). Proof on TC-100056: decline (payment 58, `failed`, bare ref, decline evidence
intact) → retry via `POST /orders/{number}/pay/` → payment 61 `succeeded` on
`TC-100056-P61` (own flw id 10427378) → SAME order `processing`, no double-payment flag,
still exactly two stock movements. Regression tests:
`test_retry_payment.py` (same-gateway retry, bank-transfer retry, attempt-suffixed return
URL, crashed-initiate replay) and
`test_confirm_payment.py::test_confirm_never_downgrades_a_succeeded_payment`.

**Task 17 (webhook)** — over a real cloudflared tunnel into
`POST /api/v1/webhooks/flutterwave/`, body = Flutterwave's own verify data for TC-100052
enveloped as `charge.completed`:

| Delivery | Result |
| --- | --- |
| `verif-hash` = `0`×64 | **HTTP 400** `invalid_signature`, no `WebhookEvent` row |
| No `verif-hash` header | **HTTP 400** `invalid_signature` |
| Correct `verif-hash` | **HTTP 200** `accepted` — one `WebhookEvent`, processed, `error=""` |
| Exact redelivery | **HTTP 200** `duplicate` — still one row (derived event id dedupe) |

Idempotency against the return-verify: TC-100052 unchanged after the webhook — one
payment, still `processing`, still two stock movements. Amount-mismatch guard not
re-staged: same shared `confirm_payment` as Paystack (its TC-100039 evidence + unit tests
cover both).

**Gaps found while certifying (open):**

- **Redirect-flow dead end.** After a failed/cancelled Flutterwave payment the failure
  screen's only exit is "Back to checkout", which lands on an EMPTY cart (the order
  consumed it). Paystack dodges this only because its popup keeps the checkout page
  mounted. The backend retry endpoint exists and is certified; what's missing is UI —
  a "Pay now" on `/account/orders/[number]` (page exists now) and/or Try-again on the
  failure screen. Decision owed by Hammed.
- **Flutterwave account limit.** The dashboard reports "Merchant limit is set at 3000
  pending go live" — test transactions cap at ₦3,000 until Flutterwave finishes their
  account review. Certification worked around it with a temporarily cheap dev product
  (restored). **Check the go-live review status before planning a live cutover** — the
  live keys likely cannot take real money until it clears.

## Task 18 — sign-off

> **Deferred to deploy, by Hammed 2026-07-24.** A phone pass against `localhost` needs the
> dev box exposed to his handset; against the preview URL it is just "open the site and
> buy something". So Task 18 runs on the first deployed preview, and it now carries the
> last-mile webhook step from Task 17.

At deploy, before the phone pass:

1. Set `STOREFRONT_BASE_URL` to the preview origin (Flutterwave builds its return URL from
   it; a stale value sends customers back to localhost).
2. Paste `https://<preview-api-origin>/api/v1/webhooks/paystack/` into **Paystack →
   Settings → API Keys & Webhooks → Test Webhook URL**. Trailing slash required.

Then:

- Hammed does a test-mode purchase on his phone through **each** configured gateway.
- Confirm Paystack's own delivery lands: a `WebhookEvent` row appears with
  `processed_at` set and `error=""`, and the order it names is fulfilled exactly once
  (compare against the Task 17 evidence above).
- Explicit sign-off that the configured gateways certify, bank transfer still works as the
  fallback, and no real money moves until Plan-27.

---

## Known gaps to be aware of while certifying

- **`payments.W002` for `CA, US`** — bank transfer is active in those markets with no
  `BankAccount` row, so customers there cannot use the fallback. Pre-existing, unrelated
  to Plan-14b: either add the accounts in Django admin or deactivate bank transfer there.
- **A closed tab is still a dead end.** The retry and method-switch routes both live on the
  payment step. A customer who closes the browser after placing an order has no way back to
  it, because there is no order-detail page yet (`/account` is a stub). The endpoint that
  would power it already exists — `POST /api/v1/orders/{number}/pay/` — so this is UI-only
  work, and its natural home is the Plan-15 account order page.
- **PayPal is loaded per-currency.** The SDK is keyed to the order's own currency, so
  certifying in one currency does not prove the others. Worth one sandbox order in a second
  currency (e.g. GBP and USD) if you can.
- **Flutterwave and PayPal are offered but unconfigured.** Deliberate, per Hammed
  2026-07-24 — the credentials are coming. Until they land, a customer who picks
  Flutterwave in NG or PayPal in CA/GB/US/ZZ gets a 503. NG still has Paystack and bank
  transfer; GB and ZZ still have bank transfer. To switch them off instead, deactivate the
  `CountryPaymentGateway` rows — `payments.W001` names exactly which markets are affected.
- **Unrelated to payments, seen while certifying:** product images 400 from
  `/_next/image` in this local setup (`.env` runs local media rather than S3), and the
  cart client throws on `.reduce` of undefined when a session expires mid-page rather than
  degrading. Neither blocks certification; both are worth a look later.
