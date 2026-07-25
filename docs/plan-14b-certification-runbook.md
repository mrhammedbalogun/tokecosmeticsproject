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
| **Paystack** (NG) | ✅ test key configured | ✅ **certified** — TC-100041 → `processing` | ⬜ not yet |
| Flutterwave (NG) | ⬜ no credentials yet | ⬜ | ⬜ |
| PayPal (intl) | ⬜ no credentials yet | ⬜ | ⬜ |
| Bank transfer | n/a | ✅ still works — TC-100042 | n/a |

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

## Task 18 — sign-off

- Hammed does a test-mode purchase on his phone through **each** of the three gateways.
- Explicit sign-off that all three certify, bank transfer still works as the fallback, and
  no real money moves until Plan-27.

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
