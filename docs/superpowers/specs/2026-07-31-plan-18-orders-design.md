# Plan-18 — order operations and customer management: design

**Status:** design spec, awaiting Hammed. Grounded against production 2026-07-31.
Master spec: `master-tokerebuild.md` § Plan-18-admin-orders-customers.

---

## 1. A correction before anything else

The master spec carries a long boxed note added by Plan-10, headed **"BANK TRANSFER IS
UNFINISHED AND THIS IS ITS OWNER"**, listing three things Plan-18 must build: a
confirm-receipt action, a per-gateway reservation TTL, and an email when a manual order
expires.

**All three are already built.** Verified in the tree:

| the note's item | reality |
|---|---|
| confirm-receipt action | `payments/views.py:228` — `ConfirmManualReceiptView`, `POST /admin/orders/{number}/confirm-payment/`, scope `orders.manage`, with guards on amount discrepancy and duplicate bank reference |
| per-gateway reservation TTL | `payments/gateways/base.py:124` exposes `reservation_ttl_minutes`; `bank_transfer.py:32` sets **1440** (24h), consumed at `checkout.py:146,253` |
| expiry email for manual orders | commit `d418cbf`, *"tell the customer when a bank-transfer order expires"* |

**So the master spec's note is stale, and so was I.** I have written in several places this
session — including `docs/gigimplementationresearch.md` and two merge commits — that bank
transfer is "unfinished" and an NG order "can be paid and never fulfilled". The accurate
statement is narrower and still worth acting on:

> The backend can confirm a bank transfer. **There is no admin screen that calls it.** A
> staff member would have to hand-craft an authenticated POST, which nobody will do.

Practically the store still cannot fulfil an order. But this is **UI-only work**, not the
backend build the note describes — which makes Plan-18a considerably smaller than advertised.

---

## 2. What production actually contains

| | |
|---|---|
| orders | **1** (`TC-100001`, `processing`) |
| orders with `review_reason` set | 0 |
| reviews | **0** |
| customers (non-staff users) | **1** |

Plan-22 imports the legacy customers and Plan-23 imports **879 legacy NG orders**. Neither
has run.

---

## 2b. A LIVE DEFECT, found reviewing this spec

**A Support user can mark an order `refunded` without any refund happening.**

`AdminOrderTransitionView` elevates exactly one destination
(`orders/views.py:234` — `ELEVATED_STATUSES = {"cancelled": "orders.manage"}`) and
dispatches exactly one to a service (`mover = cancel_order if to_status == "cancelled"`).
Everything else falls through to `transition_by_id`, a bare status flip.

But `refunded` is reachable from `processing`, `shipped`, `delivered` and `completed`
(`orders/state.py:38-41`), and it is supposed to be entered only by the refund machinery
(`payments/refunds.py:186-196`, on a full refund). So today:

```
POST /admin/orders/TC-100001/transition/  {"to_status": "refunded"}
  as a user holding only orders.operate  →  200
```

No `Refund` row. No money moved. No restock. The order lands in a terminal status and drops
out of the pipeline. It is audited, so there is a trail — but the trail records a refund that
never happened.

**The view's own comment states the rule it breaks:** *"Any status with a mandatory
side-effect belongs in this dispatch."* `refunded` has one and is not there.

**Currently theoretical** — production has one staff user, the Owner, who already holds
`orders.manage`. It stops being theoretical the moment a Support account exists. And 18a
would make it a *button*, which is how a footgun becomes an accident.

**Fix, and it belongs before the UI:** block `refunded` on the transition endpoint outright
(it is not a manual move), or elevate it to `orders.manage` and route it through the refund
service. Blocking is the honest one — there is no legitimate manual path to that status.

---

## 3. Proposed slice: 18a / 18b / 18c

The master spec's Plan-18 is three subsystems — orders, customers, reviews. Their backends
are in completely different states, and so is the data:

| subsystem | backend today | production data | verdict |
|---|---|---|---|
| **orders** | ~~complete~~ **write path complete, read path has holes** — see §3b | 1 order | **18a, now.** Nearly all UI, and it is the only thing standing between a paid order and a shipped one. |
| **customers** | **nothing.** `accounts/admin_urls.py` has staff endpoints only | 1 customer | **18b, after Plan-22.** Backend + UI, built against 1 row, is building blind. |
| **reviews** | **nothing.** no `reviews/admin_urls.py` at all | 0 reviews | **18c, after there are reviews.** A moderation queue for an empty queue. |

**18a is the whole point.** Customers and reviews need new backends *and* have no data to
design against; both become worth building the moment Plan-22/23 land, and not before.

---

## 3b. "Backend complete" was wrong — I counted endpoints instead of mapping screens

I asserted the orders backend was complete on the strength of *"14 admin endpoints"*. That
counts write routes and never asks what the screens need to READ. Three gaps, and the first
is in the screen I called the reason 18a exists:

**1. The payment panel has nothing to read.** `AdminOrderSerializer`
(`orders/serializers.py:119-126`) exposes no payments, no refunds, no gateway, no receipts,
no refundable remainder. All three payments admin routes are **POST-only**
(`payments/admin_urls.py`) and there is no payments read serializer at all. So the panel
cannot show which gateway was used, whether payment landed, or how much is left to refund —
and the refund modal cannot preflight an amount; it learns `remaining` only *after* refunding
(`payments/views.py:127`).

Telling detail: I proposed adding `allowed_transitions` to this exact serializer and did not
notice the payments gap sitting next to it.

**2. No CSV export.** §4.1 promises one; `orders/admin_urls.py` has seven routes and none
of them export.

**3. The invoice route is customer-scoped** (`orders/urls.py:8`, owner's own order). "Reuse
the existing plumbing" needs an admin route.

So 18a carries a small backend task: a payments/refunds block on the admin order serializer,
an orders CSV export, an admin invoice route — plus §2b's fix and §5's transition field.

## 4. What 18a builds

1. **`/orders`** — table with status tabs, date/gateway/country filters, CSV export.
2. **A needs-attention queue.** The filter is `review_reason != ''`, and `needs_review` is
   **not a status** — Plan-10 is explicit about that and the UI must not invent one.
3. **`/orders/[number]`** — items, totals, the event timeline, admin notes.
4. **The payment panel**, including **confirm-receipt for bank transfer**. This is the
   screen that lets a paid NG order be fulfilled, and it is the reason 18a exists.
5. **Status transitions** — only the legal ones (see §5).
6. **Tracking form** — carrier + number, which sends the customer an email.
7. **Refund modal** — amount, reason, restock toggle; gateway and manual refunds are
   separate endpoints and must stay visibly separate.
8. **Print invoice**, reusing the existing invoice plumbing.

---

## 5. Design decisions

### The API must publish the legal transitions, and today it does not

`ALLOWED_TRANSITIONS` lives in `orders/state.py:35` and **no serializer exposes it**. The
master spec asks for "status transition buttons (only legal ones shown)", so as things stand
the admin would have to encode the state machine a second time — nine statuses and their
edges, in TypeScript, drifting from the Python the moment either changes.

**Add `allowed_transitions` to `AdminOrderSerializer`** — but **NOT** a naive
`ALLOWED_TRANSITIONS[order.status]`, which would be worse than nothing here. The state
machine is a superset of what the endpoint will actually accept from a person:

- `refunded` is in the machine and must never be a button (§2b);
- `expired` is the sweep's move, not an operator's;
- `cancelled` needs `orders.manage`, checked in the view rather than the machine
  (`orders/views.py:234`), so Support would get a button that 403s.

So the field publishes **the endpoint's** legal set, not the state machine's — machine-only
destinations excluded — and each entry carries the scope it needs:

```json
"allowed_transitions": [
  {"status": "shipped",   "requires_scope": null},
  {"status": "on_hold",   "requires_scope": null},
  {"status": "cancelled", "requires_scope": "orders.manage"}
]
```

That lets the UI grey out Cancel honestly instead of hiding it or rendering a 403. This is
17a's lesson about client-side rules that can disagree with the backend, in a more dangerous
place — but the fix is to publish the *real* rule, not the nearest constant to hand.

### Confirm-receipt is not a payment verification, and the UI must not imply it is

`ConfirmManualReceiptView` exists precisely because `gateway.verify()` raises
`ManualVerificationOnly` for bank transfer — there is nothing to ask. **The staff member
reading the bank statement IS the verification.** The panel should say so plainly, and the
button should not sit next to a "verify again" control that means something entirely
different for Paystack.

It can also override an amount discrepancy and a duplicate bank reference — the two guards
that stop goods shipping twice against one transfer. Those overrides need to look like
overrides, and "look like" needs specifying rather than gesturing:

- **A discrepancy returns the expected and received amounts** (`payments/services.py:263-267`).
  Show **both numbers and the delta**, and require the reason inline — the backend already
  forces one (`services.py:374`). A bare "override?" checkbox hides the very number the
  person is deciding about.
- **The duplicate-reference guard is an exact match** (`services.py:318`). So `"REF 123"`,
  `"ref123"` and `" REF123 "` are three different references to it, and the cheapest fraud
  control in the system is bypassed by a space. **The UI must normalise the input** — trim
  and case-fold — before sending it.

### Reviews are already being collected, and nothing can approve them

Deferring 18c is right, but not on the grounds that there is nothing there. Review
submission is **live and deployed** (`reviews/views.py:41`, gated to verified purchasers,
defaulting to `status="pending"` at `models.py:31`). There is no surface anywhere that
approves one. Today that is harmless — zero reviews — but every review submitted after
launch lands in a queue nobody can see.

So 18c's trigger is **"the first pending review exists"**, not "after Plan-23". Worth a
check on the day the store opens.

### Cancelling is not an ordinary transition

Per `ADMIN_SURFACE`, `AdminOrderTransitionView` declares `orders.operate` as its floor, but
cancelling additionally requires `orders.manage`, checked inside the view. So Support can
ship and track, and cannot cancel. The UI must reflect that or Support gets a button that
403s.

---

## 6. Open questions for Hammed

1. **Is 18a-only right?** It leaves customers and reviews unbuilt until Plan-22/23. My read
   is that building either against 1 customer and 0 reviews is guesswork.
2. **What does the needs-attention queue mean operationally?** `review_reason` is free text
   set by the payment paths. Zero orders carry one today, so I cannot see the real values —
   I would rather ask than design a queue around strings I have not observed.
3. **Should 18a wait for the 17a/17b checkpoints?** It is the first admin work that touches
   money, and it will be built on the same unwalked shell.

   **Revised after review: no, but 18a gets its own hard exit gate.** The master spec's
   verification — *place a bank_transfer order, confirm receipt as staff, see it fulfil and
   the customer emailed* — has never been run by a human, and this is the first surface that
   moves money. That walk becomes a gate on 18a rather than an open question at the end of
   a spec. The first amount-discrepancy override must not be discovered on a real customer's
   money.
