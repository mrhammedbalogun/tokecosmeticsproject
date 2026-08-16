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
- **`referrals.*` RBAC scopes ARE now defined** (2026-08-15, `accounts/rbac.py`):
  `referrals.view` (Owner/Manager/Support), `referrals.manage` (Owner/Manager),
  `referrals.pay` (Owner only — marking a payout paid asserts cash left the company
  account and nothing downstream re-checks it). The endpoints that use them are next.

---

## Questions for the lawyer, and questions for the accountant

Two different professionals, two different lists. Raised 2026-08-15 while designing the
single-balance proposal (master plan Plan-29 Amendment 2) and sharpened the same day
against the primary tax texts. **Nobody who wrote this is a lawyer or an accountant.**
Send them close to verbatim; the citations are there so the professional can start from
the same page rather than from scratch.

### For a Nigerian fintech lawyer — the CBN / e-money question

The design intent being tested: customers never deposit money with us. A balance only
ever arises from (a) affiliate commission we owe under the published terms, payable
monthly to a Nigerian bank account above ₦20,000, and (b) promotional loyalty points
redeemable only as a discount on our own products, never for cash, never transferable.

1. Does either (a) or (b) fall within the CBN definition of electronic money, or any
   licensable payment-service category (MMO, PSSP, super-agent)?
2. Is paying affiliate commission by direct transfer from our corporate account an
   ordinary trade payable, or does it need a licence or registration? Does the answer
   change if the affiliate may instead apply the commission against a purchase at our
   own checkout?
3. Is there a scale threshold (users, value outstanding, transaction volume) at which
   this attracts CBN/NDIC attention even if it is not e-money?
4. Does Nigeria recognise a closed-loop / limited-network carve-out for single-merchant
   store credit and loyalty points, and are there constraints on issuing, expiring or
   converting points into store credit, provided they are never cash-redeemable?
5. What FCCPA consumer-protection terms must a points / store-credit policy carry,
   particularly on expiry and forfeiture?
6. Before making bank payouts to affiliates, is there any KYC/BVN verification or
   reporting obligation beyond normal supplier-payment records?

### ANSWERED — Hammed's rulings, 2026-08-15

He ruled directly rather than waiting for the consult. What is implemented:

| Decision | Implementation |
|---|---|
| **No WHT deducted, from anyone** — residents and non-residents alike get the full amount | `REFERRAL_WHT_PERCENT = "0.00"`, snapshot per request as `wht_rate_percent` / `wht_amount` / `net_amount` |
| Tax rules must stay **configurable** without a rewrite | One env var changes it; the arithmetic and the fields already exist |
| **Commission cannot be spent at checkout** — payout only, never store credit, a tender, a discount or points | Nothing built; the spend-at-checkout slice is cancelled (master plan Amendment 3b) |
| Record-keeping | Already satisfied — see the field map in Amendment 3(c) |
| Paid commission reported separately as **"Referrer Commission Paid"** | `referrer_commission` report in `apps/analytics`, keyed off `PayoutRequest.paid_at` |

**The questions below are therefore NOT blocking anything.** They are worth putting to an
accountant at the next opportunity — the small-payer exemption question in particular, so
that "we do not deduct" is a position somebody qualified has confirmed rather than a
default. If the answer ever comes back "you must deduct", the change is
`REFERRAL_WHT_PERCENT` plus actually remitting; the schema is already there.

Two of them are now moot and struck through: there is no set-off and no credit tender.

### For the accountant — withholding tax and treatment

**Questions 1 and 2 block the first payout run.** The rest can follow.

1. **Our turnover is ₦___.** Are we exempt from the duty to deduct at source as a small
   company — the 2024 Regulations tie the exemption to a ₦25m gross-turnover test plus a
   valid supplier TIN and ≤ ₦2m to that supplier in the calendar month, while the Nigeria
   Tax Act 2025 (from 1 Jan 2026) redefines a small company as turnover ≤ ₦100m and fixed
   assets ≤ ₦250m. Which reading governs now? If we DO have to deduct: confirm 5% for
   resident individuals, doubled where the affiliate has no TIN, and that remittance goes
   to **each affiliate's State IRS** rather than FIRS — by which day, on which platform,
   and will you file the monthly return? (Sources conflict on the state deadline: the
   Regulations say the 30th for non-PAYE deductions, NTAA 2025 s.107 penalises anything
   unremitted after the 21st. We will work to the 21st unless you say otherwise.)
2. Per deduction, what exactly must we hand the affiliate and the tax authority — the
   receipt/statement under reg. 6, the monthly return schedule — and what records do you
   want out of our system to produce them?
3. ~~WHT on set-off when commission is applied against a purchase~~ — **MOOT.**
   Commission cannot be spent at checkout (Hammed, 2026-08-15), so no settlement other
   than a bank transfer exists.
4. UK/US-resident affiliates paid in GBP/USD into foreign accounts: 10% final WHT on the
   gross? Remitted in which currency? Any UK-treaty relief worth pursuing at these
   volumes (under about £100/month)? And must we self-account 7.5% VAT on their
   commission as an imported service under NTA 2025 s.150(2)?
5. VAT: (a) confirm our affiliates — resident individuals far below the small-business
   line — charge no VAT and that we have no reverse-charge obligation for them; ~~(b) VAT when commission credit part-pays an order~~ — **MOOT**, same reason.
   (Keep the reasoning for whenever loyalty points are built: points are a real discount
   and reduce the taxable amount; commission would not have.)
6. Confirm the accounting: commission expensed at accrual (when the referred order is
   confirmed) as a distinct marketing service under IFRS 15.70–72 rather than as a
   reduction of revenue; deductible for CIT on accrual; and tell us which year-end
   schedules you want (pending/available/paid cut-off, clawback receivables, and
   retranslation of the foreign-currency commission payables).

### What the tax research already settled, pending sign-off

Read against the primary texts on 2026-08-15 — the Nigeria Tax Administration Act 2025,
the Nigeria Tax Act 2025, the Deduction at Source (Withholding) Regulations 2024 via two
law-firm reviews, and PwC's Nigeria WHT summary (reviewed 29 May 2026). Two claims were
independently re-checked against source before being written here: the 5%/10% commission
rates, and the ₦25m/₦2m/TIN shape of the small-payer exemption.

- **There is no general de-minimis.** The only relief from deducting is the small-PAYER
  exemption above. If Toke qualifies, most payouts need no deduction at all — which is
  why question 1 comes first.
- **5% to resident individuals, 10% to non-residents** (final tax for non-residents
  absent a Nigerian permanent establishment). **Doubled where the affiliate has no TIN**,
  so a TIN is worth collecting either way — the exemption needs one too.
- **Individuals' WHT is remitted to the affiliate's State IRS**, not FIRS. At scale that
  means remitting to many different states, so we need each affiliate's state of
  residence, not just their bank details.
- **WHT attaches at SETTLEMENT, not at bank transfer** — "payment is made or otherwise
  settled". A future checkout set-off is a settlement.
- **VAT stays on the full price when commission credit part-pays an order.** Concrete code
  rule that follows: `apps/checkout/services/totals.py` computes
  `taxable = subtotal - discount`, so commission credit must be applied as a TENDER after
  tax, never through `discount`. Points, being a real discount, may use `discount`.
- Unverified, ask: the remittance currency for GBP/USD commissions.

**Design rules adopted pending those answers** (they are what keep this arrangement
ordinary store credit plus an ordinary payable, rather than stored value):

- **No customer top-up, ever.** No money the customer handed over is held. This is the
  single feature doing most of the work — e-money is defined as value issued *against
  funds received from the holder*.
- **Nothing but commission is ever withdrawable.** Points and store credit never convert
  into anything that can leave as cash.
- **No fungible balance table.** Payouts keep claiming specific `Commission` rows, as
  today. Merging ledgers into one balance and debiting *that* on withdrawal would make
  points cash-redeemable pro rata — manufacturing stored value in substance, whatever it
  is called.
- **No transfers between customers**, and redemption only at tokecosmetics.com.
- **One page, two figures — never one merged number.** "Affiliate earnings (withdrawable)"
  and "Store credit / points (spend at checkout)" shown separately.
- **Vocabulary:** the page is **Rewards**. Say "request a payout of your commission" and
  "store credit". Avoid *wallet, e-wallet, cash balance, funds, top up, withdraw funds* —
  not because the word is decisive (behaviour governs) but because it is the term every
  CBN circular and PSP compliance screen pattern-matches on, and it buys nothing.
- Terms copy must state that points and credit have **no cash value**, are
  **non-transferable**, are redeemable **only at tokecosmetics.com**, and that commissions
  are payments under the affiliate agreement — **not deposits, no interest**.
