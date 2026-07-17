# Rest-of-World delivery: quote-after-payment — design

**Date:** 2026-07-16
**Status:** approved (shape signed off by Hammed; spec pending review)
**Depends on:** Plan-08 (cart/checkout), Plan-09b (manual payments), Plan-10 (orders) — all merged to `main`
**Owns:** the Plan-09b open question "a real Rest-of-World customer may not be able to check out at all"

## Problem

Two independent problems, discovered together, that must be solved in one change because
fixing the first activates the second.

**1. A Rest-of-World customer cannot check out at all.**
`delivery/services.options_for_address()` matches delivery options on the *raw*
`address.country_code`. `core.Country` rows exist only for NG, GB, US, CA and ZZ. A customer
in Germany has `country_code="DE"`, which matches no `Country` row and no `Region` ⇒ zero
delivery options ⇒ checkout fails with `delivery_option_invalid`.

The existing tests do not catch this because they give the ZZ test address
`country_code="ZZ"`, which is not a real ISO country code and is not what a real address
carries. `accounts.Address.country_code` is `CharField(max_length=2)` with no choices
constraint ("any ISO country (worldwide shipping)") and has free-text `city_text` /
`state_text` / `postcode` fallbacks, so the address layer stores `DE` correctly. The failure
is precisely and only at delivery matching.

**2. Freight cost to Rest-of-World is unknown at checkout.**
The owner does not know the shipping cost when the order is placed. It depends on weight and
destination and comes from a forwarder (e.g. Adex International) after the fact. Meanwhile
the site launches on **bank transfer only** — every payment is a human reading a bank
statement and pressing a confirm button.

## Decisions made by the owner (do not relitigate)

1. **Pay-first.** The RoW customer pays for goods immediately and the order proceeds. The
   freight cost is quoted afterwards. The alternative (quote before payment, one exact
   transfer, no off-books cash) was proposed and **rejected**: a customer who must wait on a
   WhatsApp exchange before they can pay is a customer who never pays. This trades refund
   risk for conversion. It is a legitimate business call and it is the owner's to make.
2. **The freight cost is recorded on the system**, not settled off the books. The customer
   sends a **second bank transfer to the same account** used for order reconciliation, so
   unrecorded freight would mean the books permanently undershoot the bank statement by a
   recurring, unexplained amount.
3. **A declined or ignored quote cancels the order**, releases stock, and the goods money is
   refunded by hand. Silence and refusal are handled identically.

## The constraint that shapes everything else

**Every Rest-of-World bank transfer arrives short.** Under SHA charge terms — the default for
most retail cross-border transfers — the beneficiary absorbs correspondent and receiving-bank
fees, deducted from the wire in flight. The customer sends $50; $32 lands.

This is not a new discovery. `payments/services.py:343` already documents it:

> shortfall then fulfils and records who accepted it (intl wires legitimately lose a slice to
> intermediary banks)

The consequence must be stated plainly because it survives every design choice below:
**`confirm_manual_receipt` refuses any nonzero delta unless staff pass
`accept_discrepancy=True` with a mandatory written reason, so every RoW goods payment routes
through that override from order one.** Per Plan-09b that reason string *is* the authorisation
a human needs to wire real money out. An override that fires on every routine instance of a
category stops being a control and becomes a keystroke — the failure mode this codebase has
already demonstrated with `payments.W001`.

This design does **not** fix the amount-matching policy. It is out of scope and changing it
would weaken the control that guards the goods leg, which carries most of the money. What
this design does:

- **Mitigate:** the bank-details email for non-NG markets instructs the customer to send with
  **OUR charges** (sender pays all fees, full amount lands). A template string, not code. It
  will not work every time.
- **Record:** the expectation is written down here so the next person does not mistake a
  routine RoW shortfall for a fraud signal, and does not "fix" it by widening the tolerance.

## Design

### A. Rest-of-World matching fix

`options_for_address()` resolves the address's country through the **same
`core.country_context.resolve_country()`** already used for pricing/currency context, rather
than matching the raw code. One resolution function means delivery and currency context can
never disagree.

- Unknown / inactive ISO code (`DE`) → the `is_rest_of_world=True` Country row (ZZ).
- **Known, active country with zero options → `delivery_option_invalid`, unchanged.** The
  fallback trigger is *unknown country code*, never *zero options found*. A naive
  "no options ⇒ use ZZ" means that deactivating every GB option someday would silently serve
  British customers international pricing instead of blocking checkout.
- **The address is never rewritten.** It keeps `country_code="DE"` — the real destination is
  needed to ship the parcel. ZZ is a resolution-time context only, never stored.
- Region matching is guarded so a DE address can never match an NG region option
  (e.g. "Isolo area ₦1000").

**This change activates the delivery-currency risk left open by Plan-08**, and the exact line
is now identified. `checkout.py:123` calls
`compute_totals(lines, country, delivery_amount=Decimal(chosen["price"]))` — it takes the
option's **price** and ignores its **currency**. The order currency comes from the *browsing
context* (`X-Country` header → `resolve_country`), while the delivery option comes from the
*shipping address*, and those can differ. A customer browsing the NG storefront in ₦ who ships
to Germany resolves to the ZZ option priced **$25**, and `25` is added to an NGN order as
**₦25** — freight to Germany charged at roughly three pence.

This is unreachable today only because a DE address matches no option at all. Fixing the match
makes it live, which is why the two cannot be separated.

**Owner's decision: block it.** `options_for_address()` takes the order's `country` and returns
only options whose `currency` matches `country.currency_id`. A ₦-context customer shipping to
Germany gets no option and `delivery_option_invalid`, with a message telling them to switch to
the international storefront. Rejected alternatives: converting freight via an FX rate
(introduces FX into the totals maths — new rate source, new staleness bug, new class of money
error, for a rare case) and making order currency follow the shipping address (re-prices the
whole cart mid-checkout; touches pricing; far larger change). This follows the precedent
Plan-09b set with `GatewayNotConfigured`: losing a rare sale is recoverable, silently
mispricing money is not.

### B. `quote_required` on `DeliveryOption`

Two new fields:

- `quote_required = BooleanField(default=False)`
- `disclaimer = CharField(blank=True)` — customer-visible text shown instead of a price.

When `quote_required` is true the option **never renders a price and never renders "Free"**,
and is excluded from `free_over`, from Free badging, and from any price-based sorting.

**Scope boundary — who enforces this.** `storefront/` is currently a bare Next.js scaffold with
no checkout UI, so "never renders Free" cannot be implemented there yet. The split:

- **This plan (backend, enforceable now):** `options_for_address()` emits `price: None` for a
  `quote_required` option — there is no number for any client to render as "Free" — plus
  `quote_required: true` and `disclaimer`. `free_over` never applies. Checkout coerces a
  `quote_required` option's delivery amount to `0.00` for the goods total.
- **Plan-14 (storefront checkout) inherits a contract:** when `quote_required` is true, render
  `disclaimer` in place of any price, and never the word "Free". A `price: None` that a UI
  renders as "Free" or "—" would reintroduce the exact false promise this field exists to stop.
  Plan-14 must carry a test for it.

Emitting `None` rather than `0.00` is the load-bearing part: it makes the frontend contract
*fail loudly* (a template doing arithmetic on null breaks visibly) instead of silently
rendering a zero that reads as a promise.

The problem being solved: `price=0` renders identically whether it means *"I promise this
costs nothing"* or *"I have no idea what this costs"*. Those are opposite meanings and the
customer only sees the number. The bank-details email is the closest thing this flow has to a
contract; if it quotes a goods-only total with no disclaimer, a customer who is later asked
for €40 more has been misled by the number regardless of what the option name said.

**The disclaimer must carry an indicative range** — "Shipping quoted after you order —
typically $35–70 to Europe." One admin-editable string. It costs nothing, does not slow
checkout, does not require an up-front quote, and is the single biggest lever on the decline
rate, which is the exact risk pay-first buys. This is a requirement, not a nice-to-have.

### C. The obligation / cash split

The boundary is **promise vs money**, not goods vs freight. This is the load-bearing choice
in the design.

**`ShippingQuote`** — the negotiated obligation. Nothing has moved.

| field | meaning |
|---|---|
| `order` | one per order |
| `amount`, `currency` | what was **quoted** |
| `status` | `awaiting_quote` → `quoted` → `paid` \| `waived` \| `cancelled` |
| `quoted_at`, `received_at` | timestamps |
| `note` | append-only trail |

**The freight cash** is an ordinary `Payment` row with `purpose="freight"`, created by the
"record freight receipt" admin action — which does **not** call `confirm_manual_receipt`.

`Payment.purpose` is a new field, `choices=["goods", "freight"]`, **`default="goods"`**, with a
migration backfilling every existing row to `"goods"`. The default must be `"goods"` and not
null: any `.payments` read that this design missed then keeps its current meaning by default,
which fails safe. The freight `Payment` links to its order by the existing `Payment.order` FK;
`ShippingQuote` is reached via the order, and the two are **not** FK-linked to each other —
one order has at most one quote, and a quote-to-payment FK would imply a lifecycle
(re-quote, waive-then-pay) the launch scope does not model.

Why this split rather than a self-contained `ShippingCharge` table holding both quote and
cash:

- **Cash-in stays one question against one table, forever.** `sum(Payment)` grouped by
  currency. The alternative permanently forks the money model: five years of accounting,
  refunds, analytics, tax and customer-facing payment history where every query must remember
  to read a second table — written incrementally, from partial context, for an owner who
  cannot review the SQL. That is not a risk, it is a schedule.
- **It models the quote/receipt gap structurally instead of by memory.** The quote says €40;
  €32 lands. A single-`amount` design has nowhere to put that, and would rebuild the exact
  books-vs-bank gap this work exists to close — smaller, and harder to spot, because the
  numbers would look right and be quietly wrong. Here `ShippingQuote.amount` is what was
  asked for and `Payment.amount` is, by definition, cash that arrived.
- **A `quoted` state has no business in `Payment.status`.** When the four networked gateways
  reactivate, `Payment.status` becomes gateway-shaped (initiated/succeeded/failed). A row
  meaning "quoted, no money has moved" would pollute that enum permanently.
- **Isolation comes from the code path, not the table.** The amount-match, `accept_discrepancy`
  and duplicate-reference controls live in the `confirm_manual_receipt` *service*, not in the
  `Payment` model. A freight row created by an admin action that never calls that service
  touches none of them.

**The row is created at order placement**, with status `awaiting_quote`, whenever the chosen
option is `quote_required` — not when someone gets around to quoting. Otherwise "orders
awaiting a freight quote" is a `NOT EXISTS` query — an *absence*, which no admin screen
surfaces and nobody notices, while a paid order sits silent and the customer waits. A row that
exists is a work queue, and forgetting becomes visible.

**Re-quoting** ("can you try someone cheaper?") is expected. One row per order means the quote
action overwrites `amount`. That is accepted at launch — but the action **appends** to `note`
rather than overwriting, so the trail survives. No quote history table.

### D. Known blast radius (audited, not guessed)

Tagging freight as a `Payment` is not free. Every read of `order.payments` was audited:

| site | breakage |
|---|---|
| `payments/views.py:196` (`ConfirmManualReceiptView`) | picks `filter(gateway="bank_transfer").order_by("-id").first()` — the **newest**. A freight row would **shadow the goods payment** and staff confirming a payment would confirm the wrong row. |
| `payments/views.py:172` (`ManualRefundView._pick_payment`) | `filter(status__in=["succeeded", "partially_refunded"]).first()` — could pick the freight row for a goods refund. |
| `payments/views.py:119` (`OrderRefundView._pick_payment`) | same shape. |
| `checkout/tasks.py:52` (expiry sweep) | reads `order.payments.all()` but only for orders in `pending_payment`; a freight row only ever exists on a paid order, so it is **unreachable**. No change needed. |

**Fix:** scope the three refund/confirm call sites to `purpose="goods"`. Bounded and known.

### E. Shippability

**No new `Order.status` value.** A derived `Order.is_shippable` — false while a `ShippingQuote`
exists in `awaiting_quote` or `quoted` — which the ship queue filters on.

A new status would touch every transition table, serializer, admin filter, customer-facing
label and every test that asserts on status: the largest blast radius in the design. The
derived gate gives identical safety for a fraction of the surface. The accepted tradeoff: a
derived gate is less self-documenting, and a queue written later could forget it. The status
costs more than that risk.

### F. Customer-facing status label

An order awaiting a freight quote must **not** display as "Processing". It reads
**"Awaiting shipping cost"**.

"Processing" reads as "it shipped". The customer emails for tracking within 48 hours — every
one of those is the owner's time and a small trust debit at precisely the moment he is about
to ask them for more money.

### G. Waiving

`waived` stays. The alternative is the owner marking freight `paid` with a note saying
"absorbed", which is a lie in the cash ledger, and lies in the cash ledger are what this
exists to stop.

Insider fraud is a thin threat model at one admin who is also the owner. The real failure is
the pattern this codebase has already run twice (`accept_discrepancy`, `W001`): **every escape
hatch gets worn smooth.** Two mitigations, both required:

1. **Waiving requires a prior quote.** Waiving a charge with no amount records *nothing* —
   that is literally the off-books hole this design closes, re-entered through the front door.
   Quote-then-waive forces the artifact to read "₦18,400 of freight forgiven".
2. **Waived is loud in reporting, never equivalent to paid.** A reconciliation line — "freight
   waived: 6 orders, $340 of quoted value" — makes waiving a legitimate, visible business
   action (goodwill, consolidated shipment, eating cost to save a customer). Silent waiving is
   a hole. The mandatory reason is table stakes; the *report line* is what makes it safe.

### H. Money reporting

**Any cash-in aggregate groups by currency, always. There is no default single-sum path.**
NGN goods and USD freight added into one scalar produces a confident, wrong number, and it is
the number the owner would look at.

### I. Freight reference

The freight transfer needs its own human-transcribable reference (`TOKE-1234-F`), distinct
from the goods reference, with a **real DB unique constraint on a real column** — deliberately
not the `raw_response.manual_receipt` JSON key that gave Plan-09b its TOCTOU race.

Be honest about what this buys: SWIFT narration is routinely truncated and mangled by
intermediaries, so in practice matching is often by amount + date + name, not reference. The
constraint is a **dedup** control, not an identification mechanism. Identification is still the
owner's eyes on a bank statement. The constraint's existence must not create false confidence.

> Note: the Plan-09b TOCTOU race on the **goods** leg's duplicate-reference check remains open
> and is not this design's job. It carries most of the money. Recorded here so it is not lost.

### J. The decline path

Customer declines the quote, or never replies. Silence is the modal case; both collapse to one
terminal `cancelled` state distinguished by note text. Two enum values with identical
operational handling are a liability when the operator is one non-developer.

**Build the record, not a refund flow.** Both halves already exist: `cancel_order` and
`ManualRefundView` / `record_manual_refund`. The path is:

1. `ShippingQuote.status = cancelled`, reason appended to `note`.
2. Order cancels; **stock releases back to sellable** — cosmetics have shelf life and trend
   risk, so freeing the units is the part that actually recovers value.
3. The goods money is refunded by hand through the existing manual-refund endpoint.

**Authorisation gap, recorded deliberately:** unlike the discrepancy case, a customer who paid
the goods total exactly produces no delta, so no `accept_discrepancy` reason string exists to
authorise the wire-out. The `ShippingQuote.note` plus the `Refund` row are the artifact. (A
free-text reason as the sole authorisation for money leaving the bank is a weak control
independent of this design; noted, not fixed here.)

### K. Stock held during negotiation

A paid RoW order holds committed stock while freight is negotiated, possibly for days.

- **Verified safe:** `checkout/tasks.py:35` filters `status="pending_payment"`, so the expiry
  sweep cannot touch a paid order awaiting a quote. Nothing auto-releases stock out from under
  an order that has the customer's money against it.
- **Invariant: never auto-cancel or auto-release an order with real money against it.** No
  exceptions. No TTL on the freight wait.
- **No stale-freight TTL and no stale-freight report.** The `awaiting_quote` queue *is* the
  report. At RoW volume a few frozen units are immaterial.
- **Plan-20's reserved-vs-sold split:** an order awaiting freight is **sold**, not reserved —
  paid, committed, not yet shipped. Get this right once in the digest definition or restock
  decisions will read spoken-for inventory as available. One line in Plan-20, not here.

## Explicitly not building

Quote history; a waive approval workflow; a new refund model; a stale-freight TTL; a new order
status; multi-payment/balance-due machinery; a second gating confirmation; carrier APIs;
delivery-cost analytics; `quoted_by` / `confirmed_by` audit FKs (audit theatre at N=1 — if
kept because they are nearly free, they appear in no UI).

## Unchanged and confirmed correct

The general principle the owner asked for — *an admin can create a delivery method by giving
it a name and an amount, which may be zero* ("Free Delivery ₦0", "Isolo area delivery ₦1000")
— **is already fully supported** by `DeliveryOption.name` + `price` + `currency`. Zero code.
Nothing in this design constrains a genuine ₦0 free-delivery option. `quote_required` exists
solely to stop *unknown* cost from masquerading as *zero* cost.

## Testing

The existing tests missed the RoW gap by giving the test address `country_code="ZZ"`. That
must not recur.

- **A real ISO code, always.** The RoW address fixture uses `country_code="DE"`. Assert the
  returned option set is *precisely* the ZZ options — no NG region option, correct currency.
- Known active country with zero options still yields `delivery_option_invalid` (the fallback
  must not swallow it).
- The stored address still reads `DE` after checkout.
- A `quote_required` option renders neither a price nor "Free" at cart, checkout, and in the
  order-received email.
- `ShippingQuote` exists in `awaiting_quote` immediately after placing a RoW order.
- A freight `Payment` does not shadow the goods payment in `ConfirmManualReceiptView`, nor get
  picked by either refund view.
- `is_shippable` is false while a quote is `awaiting_quote` or `quoted`; true once `paid` or
  `waived`.
- Waive with no prior quote is refused.
- Cash-in aggregates group by currency (assert NGN and USD never sum).
- The expiry sweep leaves a paid, awaiting-freight order untouched.
- Per Plan-09b's hardest-won lesson: **mutation-verify each test.** A branch invertible with a
  green suite is a test that does not exist.

## Risks accepted

| risk | why accepted |
|---|---|
| Every RoW goods confirm uses `accept_discrepancy` | Out of scope; mitigated by the OUR-charges instruction; documented so it is not misread as fraud |
| Declined quote ⇒ lossy manual international refund | The owner's explicit trade for conversion |
| One-row quote loses re-quote history | `note` append preserves the trail; history table is gold-plating at this volume |
| `is_shippable` derived, not a status | Blast radius of a new status exceeds the risk |
| Freight reference dedup, not identification | SWIFT narration is unreliable regardless; the owner's eyes are the real control |
| Goods-leg TOCTOU race still open | Pre-existing, larger than this change, recorded not fixed |
