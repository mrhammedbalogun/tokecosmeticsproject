# Referral programme — runbook

The customer half of Plan-29. Every registered customer is automatically a referrer;
there is no application, no approval, and no "join" button. The admin half (payout queue,
fraud review screen, blocking, manual adjustments) is **not built yet** — see
[What is not built](#what-is-not-built-yet).

Published terms, which this implements: <https://tokecosmetics.com/affiliates-2/>

---

## The numbers, and where they live

Every published number is a Django setting, env-overridable, in `config/settings/base.py`.
They are settings rather than `SiteSetting` rows deliberately: each one is a promise
printed on a public page, so changing one is a deploy *and* a terms update, together.

| Setting | Default | What it is |
|---|---|---|
| `REFERRAL_COMMISSION_PERCENT` | `10.00` | Commission on qualifying net sales |
| `REFERRAL_COOKIE_DAYS` | `30` | Click-attribution window |
| `REFERRAL_HOLD_DAYS` | `60` | Holding period, counted **from shipping** |
| `REFERRAL_PAYOUT_THRESHOLDS` | `NGN 20,000 · GBP 20 · USD 25 · CAD 30` | Minimum payout, per currency |
| `REFERRAL_ELITE_THRESHOLDS` | `NGN 200,000` | The ₦200k Club |
| `REFERRAL_ELITE_WINDOW_DAYS` | `90` | Rolling window for the tier |
| `REFERRAL_TERMS_VERSION` | `2026-08-14` | Stamped on a referrer at first payout |

`REFERRAL_COOKIE_DAYS` is mirrored in `storefront/src/lib/referral.ts`
(`REFERRAL_COOKIE_DAYS`). **They must match** — one is how long the browser keeps the
code, the other is what the account page tells the referrer the window is.

The commission rate is SNAPSHOT onto every `Commission` row at accrual, so changing the
setting never rewrites what has already been earned.

---

## The three ways a referral is claimed

All three end in the same place — the httpOnly `tc_ref` cookie — because that cookie is
the *only* thing the checkout reads.

| Form | Example | Who writes the cookie |
|---|---|---|
| Link | `tokecosmetics.com/?ref=AMINA7K3P` | `proxy.ts`, on any route |
| Short link | `tokecosmetics.com/r/AMINA7K3P` | `proxy.ts`, then redirects to `/` |
| Typed code | "Friend's referral code" box on the cart page **and** the checkout review step | `POST /api/referral`, after validating upstream |

The typed-code path exists because people share codes in captions and voice notes, not
only as links. It renders in two places because two routes reach payment without ever
loading /cart — "Buy now" on a product page and the mini-cart drawer's checkout button —
so a cart-only field is invisible to anyone taking either. Same component, same
`POST /api/referral`; only the surrounding chrome differs (`variant="inline"` in the
review step, which has no per-section box of its own). Applying it there costs no
re-quote: the code never enters the quote payload, only the cookie the BFF reads at
placement. It goes through the server for the same reason everything else does: the
browser may *ask* for a code to be applied, but only the server may write the cookie that
decides who gets paid. A `referral_code` in the checkout request body is still discarded.

`GET /api/v1/referrals/lookup/?code=X` is the only public endpoint in the app. It answers
`{valid, referrer_name}` — a first name and nothing else — is throttled
(`referral_lookup`, 60/min), gives the same answer for a blocked code as for a
non-existent one, and tells an authenticated caller applying their own code so, rather
than confirming a link that will never pay them.

## How a commission happens

```
  ?ref=CODE  ──► proxy.ts sets httpOnly cookie tc_ref (30d, last-click wins)
  /r/CODE    ──┤   (same cookie, then a redirect home)
  typed code ──┘   (same cookie, written by POST /api/referral after validation)
                     │
  checkout   ──► BFF reads the COOKIE (never the request body) and sends referral_code
                     │
  place_order ─► attribution_code_for_order() validates, stamps Order.referral_code
                     │                        (unknown / blocked / self-referral → "")
  payment     ─► _fulfil_locked() calls accrue_for_order() → Commission(status=pending)
                     │
  shipping    ─► nightly mature_commissions() stamps matures_at = shipped_at + 60d
                     │
  +60 days    ─► same task flips pending → available
                     │
  customer    ─► request_payout() claims the balance → PayoutRequest(requested)
                     │
  staff       ─► mark_payout_paid() → email with the bank reference
```

**Attribution is decided at placement and nowhere else.** Payment confirmation runs off a
gateway webhook with no browser and no cookie behind it, so a commission worked out at
that point would have nothing to work from. `Order.referral_code` is the bridge.

**The commission base** is `subtotal − discount_total`, minus `tax_total` in markets where
`prices_include_tax` (Nigeria). Shipping never enters it. See
`referrals/services.commission_base` for the full reasoning.

---

## Things that will surprise you

**`Commission.status = 'paid'` means "claimed by a payout", NOT "the money arrived."**
Requesting a payout re-labels the claimed commissions immediately, which is what makes
the balance drop to zero and stops a second tab requesting the same money.
`PayoutRequest.status` is the truth about the money; `Commission.status` is the truth
about whether a row is still claimable. Rejecting a request puts them back.

The customer never sees the raw word: `CommissionSerializer.get_status_label` reads
through to the payout and says "In a payout being reviewed" / "being sent" / "Paid out".
**Anyone writing a report against this table must do the same** — counting
`status='paid'` as money out of the door will overstate it by every open request. (The
status is arguably misnamed; `claimed` would be clearer. Left alone because the
customer-facing lie — the thing that generates support tickets — is fixed at the
serializer, and renaming it now buys clarity for future readers at the cost of a
migration plus churn through the UI.)

**One recompute, called from three places.** `_reverse_locked` is the only code that
decides what an order owes after a refund. The refund webhook, the nightly sweep, and
`reject_payout` releasing commissions all reach it (the latter two via
`recompute_for_order`, which reads the refund total from the ledger itself). Every one
of them recomputes *from scratch* against the running refund total, which is what makes
replays and overlapping paths converge instead of stacking. **Do not add a fourth path
that adjusts commission incrementally.**

**A balance can go negative.** If an order is refunded *after* its commission was paid
out, the money cannot be recalled, so the shortfall is written as a negative
`ReferralAdjustment` and nets against future earnings. `request_payout` refuses while the
balance is under water. The customer sees a plain-English explanation on their wallet card.

**The holding clock starts at shipping, not payment.** An order that took three weeks to
reach Lagos has not had its return window run down by the shipping time. An order that is
paid but never dispatched never starts its clock at all — which is also what "fully paid
and shipped" in the published terms requires.

**A `shipped` order with no `status:shipped` timeline event is left unstamped.** That
happens for migrated legacy orders. The sweep declines to invent a date rather than guess
a payout date; the row simply waits. An unpaid commission is recoverable, an early payout
is not.

**Accrual and reversal can never raise.** Both run inside money-critical transactions
(`_fulfil_locked`, `apply_succeeded_refund`) and swallow every exception, because an error
there would roll back a payment that has already been charged, or block a refund. Failures
are logged at `exception` level, so they reach Sentry. **Both have a repair path** —
without one, "log and continue" is just a silent leak: accrual has
`backfill_referral_commissions`, and reversal is re-derived nightly by the sweep's
recompute pass, which recomputes every order that is dead or has refund activity.

**Refunds are attributed to the goods first, and this is approximate.**
`payments.Refund` carries free-text `reason`, not a type, so there is no reliable way to
tell a returned item from a goodwill refund of the delivery fee. Goods-first is the
conservative direction, and it has a known wart: a pure shipping refund does reduce
commission, which sits awkwardly beside "commission excludes shipping". Accepted
knowingly. If refund typing ever lands, `services._surviving_base` is the one function to
change.

**Refund amounts are gross; the commission base is net.** `_surviving_base` does its
arithmetic in gross space and scales back to net at the end. Subtracting a gross refund
straight off a tax-stripped base under-pays the referrer by the tax fraction on every
partial refund — systematic, in the shop's favour, and exactly what a ₦200k Club affiliate
would reconcile. Pinned by
`test_reversal_edges.py::test_a_partial_refund_on_a_tax_inclusive_order_does_not_under_pay`.

**"Earned all time" is net of returns.** Lifetime nets ALL adjustments, clawbacks
included. Counting only credits made it path-dependent: a return before payout dropped
the commission out of lifetime, while the identical return after payout left it counted
and the clawback ignored — so lifetime permanently overstated by the refunded amount.

---

## When something goes wrong

### "referral accrual failed for order TC-xxxxx" in Sentry

The order still carries its `referral_code`, so the commission is recoverable:

```bash
# See what is missing
manage.py backfill_referral_commissions --dry-run
# Fix everything, or one order
manage.py backfill_referral_commissions
manage.py backfill_referral_commissions --order TC-100042
```

Idempotent — `Commission.order` is unique and the command only creates missing rows. It
never edits an existing commission, so a re-run cannot rewrite history.

### A referrer says their balance is wrong

1. `Commission.objects.filter(referrer__email=...)` — check `status` and `matures_at`.
   `matures_at IS NULL` means the order has not shipped (or has no shipping event).
2. `ReferralAdjustment.objects.filter(referrer__email=...)` — a clawback is the usual
   answer to "it went down".
3. The nightly sweep is `apps.referrals.tasks.mature_commissions`; it is safe to run by
   hand and is idempotent. It returns
   `{stamped, recomputed, released, stalled}` — **`stalled` is the one to watch.** It
   counts commissions still `pending` on orders shipped more than the holding period ago,
   i.e. work the sweep should have done and did not, and it is logged at ERROR when
   nonzero. A sweep that has silently broken and a sweep with nothing to do are otherwise
   identical from the outside.

Each of the three passes runs in its own transaction and is allowed to fail alone. They
shared one block originally, which meant a single poison row rolled back all three — and
would again every night after, with nobody the wiser until a customer asked why their
balance had said "pending" for three months.

### A referrer says they never got a payout

`PayoutRequest.reference` holds the bank's transfer reference, and `method_snapshot` holds
the full account details the transfer was actually sent to — frozen at request time, so it
is still correct even if they have since changed their bank details.

### A payout request is stuck

`PayoutRequest` in `requested` means the customer's commissions are claimed (`paid`) and
their balance reads ₦0 while no money has moved. Because processing is monthly and
manual, a forgotten request strands a real balance indefinitely — **the admin queue needs
an aging alert on `status='requested'` older than N days.** Not built; noted here so it is
not discovered by a customer.

`Commission.payout` and `ReferralAdjustment.settled_by` are `PROTECT`, so a PayoutRequest
holding commissions cannot be deleted. Cancel it with `reject_payout`, which releases the
commissions properly and recomputes them.

**There is no un-pay.** Once a payout is `paid`, fraud discovered afterwards is handled by
writing a negative `ReferralAdjustment` by hand (kind `correction`, with a reason). An
admin control for that belongs with the admin phase.

### Suspected abuse

`ReferralProfile.is_blocked = True` stops new commissions accruing and stops payout
requests. It deliberately does **not** touch money already earned; taking that back is a
`ReferralAdjustment` with a reason, which needs a human.

`services.fraud_flags(payout_request)` returns the signals a reviewer should see
(orders shipped to the referrer's own address, a single buyer behind every order, shared
email domain, a very new account). It is not a score and it blocks nothing — **manual
monthly review is this programme's main fraud control.**

---

## Backfilling codes

Codes are minted lazily the first time a customer opens their referral page. To mint them
ahead of time (so a code exists before support has to read one out):

```bash
manage.py backfill_referral_codes --dry-run
manage.py backfill_referral_codes
```

Skips staff accounts and accounts that already have a profile. Safe to re-run after any
customer import.

---

## Security notes

**Bank account numbers are stored in the clear.** That is a decision, not an oversight:
a Nigerian NUBAN is semi-public (people publish them to take payment), so confidentiality
buys little, while another encryption key to manage and lose buys real operational risk.
The threat that costs money is **modification** — account takeover, swap the payout
account, withdraw — so the controls point there:

- The API never returns a full account number; only `•••• 6789`.
- Every change emails the account holder (`referral_payout_method_changed`).
- Every payout request snapshots the details it was made against.

**Not built, and honestly not claimed:** live account-name resolution against
Paystack/Flutterwave, which would catch a number that does not belong to the name given.
`PayoutMethod.bank_code` exists so that is a service change rather than a migration.

**Account deletion scrubs payout details.** `accounts.tasks._scrub_payout_details`, called
from the anonymisation sweep, deletes the `PayoutMethod` (a standing instruction for a
payout that will never come) and reduces every `PayoutRequest.method_snapshot` to the bank
name plus the last four digits. The financial record survives — "₦31,000 to GTBank
••••6789, reference GTB/2026/0042" — without holding a deleted customer's account number.
**Any future table that stores customer PII has to be added there too**; the sweep does
not discover them.

**A referrer with a payout cannot be hard-deleted.** `Commission.payout` is `PROTECT`, so
`User.delete()` in a shell raises `ProtectedError`. That is intentional and does not
affect the product: account deletion anonymises rather than deletes.

**The referral code in a checkout comes from an httpOnly cookie, never the request body.**
A `referral_code` supplied by the browser is destructured out and discarded in
`storefront/src/app/api/checkout/route.ts`. Without that, any logged-in customer could
credit an arbitrary referrer — or themselves via a second account — from devtools.
Pinned by `place.test.ts::IGNORES a referral code supplied in the request body`.

---

## What is NOT built yet

The customer experience is complete. The staff side is not:

- **No admin payout queue.** `services.approve_payout`, `reject_payout` and
  `mark_payout_paid` exist and are tested, but nothing calls them over HTTP. Until the
  admin app catches up, a payout can only be completed from a Django shell.
- **No admin UI for blocking a referrer or writing an adjustment.**
- **No `referrals.*` RBAC scopes** in `accounts/rbac.py` — they belong with the admin
  endpoints that will need them.
- **No commission-earned emails.** Only the two payout emails exist. A per-sale email
  would be a spam cannon from a domain whose deliverability is already fragile; a weekly
  digest is the right shape and belongs with the admin phase.
- **No cookie-consent gate for UK visitors.** An affiliate cookie is not "strictly
  necessary" under PECR. Accepted for v1 given where the volume is; revisit if UK traffic
  grows.
- **Withholding tax.** A business paying commissions to individuals in Nigeria may have
  WHT obligations. Verify with an accountant **before the first payout run**, not after.
  `PayoutRequest` can carry a deduction line when that is decided.
