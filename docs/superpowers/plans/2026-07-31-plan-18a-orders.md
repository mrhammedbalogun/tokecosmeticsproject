# Plan-18a — order operations (admin UI)

Design spec: `docs/superpowers/specs/2026-07-31-plan-18-orders-design.md`. Branch
`plan-18a-orders` off `main` (`4ce9d79`).

18b (customers) and 18c (reviews) are deferred — their backends do not exist and production
holds 1 customer and 0 reviews. See the spec §3.

---

## Grounding (verified 2026-07-31, do not re-derive)

**Already true, and it shapes everything below:**

- The bank-transfer backend is **complete** — `ConfirmManualReceiptView`, per-gateway TTL
  (`bank_transfer.reservation_ttl_minutes = 1440`), the expiry email, and the shared verdict
  block (`_react_to_verdict`, `payments/services.py:227`, called from both confirm paths).
  The master spec's "BANK TRANSFER IS UNFINISHED" note is stale.
- **The `refunded` transition hole is fixed and deployed** (`backend-v0.5.2`). `refunded`
  now requires `orders.manage` *and* is refused while the order holds a `succeeded` or
  `partially_refunded` payment.
- Production: **1 order** (`TC-100001`, `processing`, ₦2,000 captured), 0 flagged for review.

**The five `review_reason` values, read out of `payments/services.py`** — this answers the
spec's open question without needing to guess:

```
payment {pk} received on a cancelled order — refund it
possible double payment — order already processing; refund payment {pk}
payment {pk}: gateway reported {X} {ccy}, order total is {Y} {ccy} — not fulfilling
overpaid by {X} {ccy} (received {A} against {B}) — refund the difference
shortfall of {X} {ccy} accepted by {staff}: {note} (received {A} against {B})
```

Three things follow, and they are design constraints rather than trivia:

1. **Every one is a money discrepancy, and four of five say "refund".** The needs-attention
   queue is not a general inbox — it is a refund worklist. Each row should reach the refund
   action in one click.
2. **They accumulate, joined by `"; "`** (`_add_review_reason`, `services.py:132-136`). The
   UI splits on that separator and renders a list. One order can carry several.
3. **They are human sentences with amounts baked in.** The UI must never parse them for
   meaning — display only. `AdminResolveReviewView` is the only thing that clears them, and
   it moves no money.

**Backend gaps 18a must close** (the spec's §3b — I had wrongly called the backend complete):

- `AdminOrderSerializer` exposes no payments, no refunds, no gateway, no refundable
  remainder. All three payments admin routes are POST-only. **The payment panel has nothing
  to read.**
- No orders CSV export.
- The invoice route is customer-scoped (`orders/urls.py:8`).

---

## Design rulings

### 1. `allowed_transitions` publishes the ENDPOINT's rule, not the state machine's

`ALLOWED_TRANSITIONS` is a superset of what a person may do. Publishing it raw would render
a `Refunded` button that now 400s, an `expired` button that belongs to the sweep, and a
`Cancel` button that 403s for Support. So the serializer field carries the endpoint's answer,
with the scope each destination needs:

```json
"allowed_transitions": [
  {"status": "shipped",   "requires_scope": null},
  {"status": "cancelled", "requires_scope": "orders.manage"}
]
```

`refunded` and `expired` are excluded as machine-owned. The UI greys out what the operator
lacks the scope for rather than hiding it — a hidden button is indistinguishable from a
missing feature, and Support asking "why can't I cancel" is a better outcome than Support
concluding the admin is broken.

### 2. Confirm-receipt is not a verification, and must not look like one

`gateway.verify()` raises `ManualVerificationOnly` for bank transfer — there is nothing to
ask. **The staff member reading the bank statement is the verification.** The panel says so
in those words, and the confirm control never sits beside a "verify again" button, which
means something entirely different for Paystack.

### 3. The two overrides must show the numbers they are overriding

- **Amount discrepancy.** The backend returns expected and received
  (`payments/services.py:263-267`) and forces a reason (`:374`). The UI shows **both amounts
  and the delta**, and takes the reason inline. A bare "override?" checkbox hides the one
  number the decision is about.
- **Duplicate bank reference.** The guard is an exact match (`services.py:318`), so
  `"REF 123"`, `"ref123"` and `" REF123 "` are three different references to it — a space
  defeats the cheapest fraud control in the system. **The UI trims and case-folds before
  sending.** This is a client-side normalisation, not a client-side rule: it changes what is
  submitted, never whether the backend accepts it.

### 4. Refunds: gateway and manual are different acts and stay visibly apart

`OrderRefundView` takes `{amount, reason?, restock?, payment_id?}` and moves money through
the gateway. `ManualRefundView` records a refund somebody made by bank transfer. Collapsing
them into one "Refund" button would let an operator think money moved when it did not. Two
controls, labelled for what they do.

`restock` is a toggle with a real consequence and gets a stated default: **on**, because the
goods usually come back, and an operator who forgets is more likely to want stock returned
than not.

---

## Tasks

1. **Backend: the payment panel's data.** A read-only payments/refunds block on
   `AdminOrderSerializer` — per payment: gateway, purpose, amount, status, reference,
   created; per refund: amount, status, reason, created; plus a computed refundable
   remainder. Also `allowed_transitions` per ruling 1. TDD; no new endpoint, so no new guard
   declarations, but the audit guard will want checking.
2. **Backend: orders CSV export + admin invoice route.** Export mirrors the products/stock
   exports, including their read-audit decision. The invoice route is an admin-scoped
   sibling of the customer one.
3. **Admin `/orders`** — table, status tabs, date/gateway/country filters, CSV export,
   pagination. Reuses `lib/pagination.ts` and the `Pagination` component from 17a.
4. **The needs-attention queue** — `?needs_review=1` (the endpoint already filters on
   `review_reason != ""`, `orders/views.py:149`). Rendered as a refund worklist per the
   grounding, splitting on `"; "`.
5. **Admin `/orders/[number]`** — items, totals, addresses, the event timeline, admin notes.
6. **The payment panel**, including **confirm-receipt with both overrides** (ruling 3). This
   is the screen that makes a paid NG order fulfillable and the reason 18a exists.
7. **Transitions, tracking, refunds** — legal-only buttons (ruling 1), the tracking form that
   triggers the customer email, and the two refund controls (ruling 4).
8. **Live walkthrough, then the EXIT GATE below.**

## The exit gate

Not a checkpoint at the end — a gate. The master spec's own verification has never been run
by a human:

> place a `bank_transfer` order, confirm receipt as staff, see it fulfil and the customer
> emailed.

**18a is not done until that walk passes**, including one deliberate amount discrepancy and
one duplicate-reference attempt. This is the first admin surface that moves money, built on
a shell nobody has walked; the first discrepancy override must not happen on a real
customer's money.

## Risks

- **Built on an unwalked shell.** Plans 17a and 17b are deployed and never opened in a
  browser. 18a inherits their session handling, their tab patterns and their error rendering.
- **One order, one status.** Production holds a single `processing` order, so the status
  tabs, the filters and the needs-attention queue will all be exercised against fixtures
  until Plan-23 imports 879 legacy orders. Expect the queue's real shape to surprise us then.
- **`review_reason` is free text.** Anything that parses it will break the first time a
  reason is reworded. Display only.

---

## Task 8 — live walkthrough and EXIT GATE (2026-07-31)

Real Django + Postgres + both Next apps, nothing mocked. **The gate's own sentence, run
end to end for the first time:** an order placed as a customer through the storefront,
confirmed as staff in the admin, fulfilled, and the customer emailed — including the
deliberate amount discrepancy and the duplicate-reference attempt the gate demands.

**Environment note, and it matters.** Local `.env` had `EMAIL_BACKEND` pointing at
**Resend with real delivery on** (Hammed's 2026-07-15 choice), so the walk would have sent
genuine mail to an invented customer address. It ran on the console backend and the
setting has been restored. Turnstile ran on Cloudflare's documented test keys for both
apps; the real pair is backed up beside each `.env`.

### The walk

**Placed as a customer** (`walk-customer@…`, storefront): PDP → cart → checkout, real
NGN pricing, a real Lagos address with the state→LGA dependency, delivery quoted live
(Lagos ₦1,500 / Nationwide ₦3,500), bank transfer chosen. **TC-100044**, ₦20,000, and the
thank-you page showed the GTBank account with the order number as the reference. The
"payment instructions" email arrived. A second order, **TC-100045**, was placed for the
duplicate test.

**The order desk**: 14 orders, status tabs, country/gateway/date filters, and the
needs-attention queue rendering two genuinely flagged orders with their `review_reason`
sentences split and listed — the refund worklist the grounding described.

**The money screen, which is why 18a exists:**

1. **Deliberate discrepancy.** ₦19,000 confirmed against a ₦20,000 order. Refused, and the
   panel showed exactly what ruling 3 demands — order total, received, and the −1,000.00
   delta — with "Accept the difference and fulfil" **disabled until a reason was written**.
2. **Accepted with a reason** → order `pending_payment` → **`processing`**, payment
   `succeeded`, the shortfall recorded as a review flag naming the staff member, and the
   "Clear the flag" control saying honestly that clearing moves no money.
3. **The customer was emailed** — "Your Toke Cosmetics order TC-100044 is confirmed", with
   a signed tracking link.
4. **Tracking + Shipped** → "your order is on its way", carrying GIG Logistics /
   GIG-WALK-0044.
5. **Duplicate reference.** TC-100045 confirmed against `gtb/TC-100044/aug1` — typed in a
   DIFFERENT CASE on purpose. The guard caught it, which proves ruling 3's client-side
   normalisation (trim → collapse → uppercase, `actions.ts:181`) is doing its job: the
   cheapest fraud control in the system is not defeated by a shift key. The override is
   gated behind a written note, and **was not used** — refusal is the correct outcome.

**The audit row** for the confirm carries the actor, the normalised reference, the amount,
the note and both override flags (`accept_discrepancy: True`,
`allow_duplicate_reference: False`). `ALLOWED_TRANSITIONS` recomputed correctly across the
walk (Cancelled/Processing → On hold/Shipped).

**Backend: zero 5xx across the entire session.**

### Two real defects, both found here and both fixed

1. **Task 2 shipped two endpoints that were unreachable from a browser.** The BFF appended
   a trailing slash to every upstream path on the stated ground that "Django's URLconf ends
   every endpoint in a slash" — which Task 2 itself made false, registering
   `orders/export.csv` and `orders/<number>/invoice.pdf` *without* one precisely so
   `orders/<str:number>/` could not swallow them. So the proxy turned the export into
   `orders/export.csv/`, which matched the detail route as an order literally numbered
   "export.csv": **the Export CSV button and the Invoice link both 404'd**, with the exact
   error the URLconf's own comment set out to prevent. Every unit test passed throughout —
   they mock `fetch`, so none traverses that function. Fixed in the BFF (a filename final
   segment is sent as-is) and pinned by tests. Both now return `text/csv` and
   `application/pdf`.
2. **A refused duplicate reference left no trace anywhere.** The amount-discrepancy path
   records a `manual_receipt_refused` event before raising; the duplicate path raised with
   no event, and `AdminAuditMixin` audits successful writes only — so the single moment
   this system catches goods being released against money already spent was invisible on
   both orders and in the audit log. Reference-probing left no record. Now recorded
   symmetrically, naming the reference and the order it already paid for; verified live.

### Smaller findings, not fixed

- **The order emails print an incomplete address.** Both the confirmation and dispatch mails
  render "Delivering to:" as the street line and a blank line — no recipient name, city,
  state or phone, all of which the admin panel shows correctly. A courier reading that
  email could not deliver from it.
- The 17a walkthrough's open items still stand: the audit allowlist omits the product copy
  fields, six sidebar links 404, and dev-only image breakage.

### Gate

**The exit gate PASSES.** A bank-transfer order was placed, confirmed by a human against a
discrepancy, fulfilled, and the customer emailed twice; the duplicate-reference guard held
under a case-variation attempt. The first discrepancy override did not happen on a real
customer's money, which was the point.

Local fixtures left in place: **TC-100044** (shipped) and **TC-100045** (pending payment,
carrying the refused-duplicate event).
