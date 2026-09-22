/**
 * Has this order's money actually landed? (Plan-44, 2026-09-22.)
 *
 * ── THE BUG THIS EXISTS TO CLOSE ────────────────────────────────────────────────────
 *
 * `PurchaseTracker` used to fire on mount with no status check at all, and the
 * confirmation page is reached IMMEDIATELY AFTER PLACEMENT — `ReviewStep` pushes to it
 * so a bank-transfer customer can read the account details. So the page said "Your order
 * is reserved. Complete your bank transfer using the details below" while the pixel
 * beside it reported a completed Purchase to five platforms.
 *
 * ── HOW MUCH THIS WAS ACTUALLY COSTING, MEASURED ────────────────────────────────────
 *
 * Less than the raw numbers suggest, and the distinction is worth keeping because it is
 * easy to get wrong twice. In the 30 days to 2026-09-22 production placed 243 orders
 * that reached `processing` and 191 that expired unpaid — but 191 of 191 expired orders
 * were Paystack/Flutterwave, and an abandoned gateway payment never returns to this
 * page at all: `PaymentLauncher` routes here only after a VERIFIED `succeeded`, and
 * `CheckoutReturn` only on `succeeded`.
 *
 * The orders that really did reach it unpaid are the bank-transfer placements (6 in the
 * same window), plus whoever followed the "try another payment method" link or a
 * `PayAgain` redirect back here. Low volume, then — but every one of them reported a
 * sale that had not happened, and reporting a non-payer teaches Smart Bidding to go and
 * find more of them. The gate is about being right, not about the count.
 *
 * The server half never had this bug — it fires from the `processing` transition
 * (`orders/state.py::_effects_for`), which is the authority on "paid". This is the
 * browser's copy of that judgement, and it must not drift from it.
 *
 * ── AN ALLOWLIST, DELIBERATELY ──────────────────────────────────────────────────────
 *
 * A denylist would mean a status added to the backend tomorrow starts reporting sales by
 * default. An allowlist means it reports nothing until someone decides it should — and
 * the server half is already covering every consenting paid order through Data Manager,
 * so the cost of being wrong in this direction is signal quality, not a missing sale.
 *
 * `on_hold` is included because it is only reachable FROM `processing`
 * (state.py ALLOWED_TRANSITIONS), so the money is already in. `refunded` is excluded
 * because it was given back — the same call `replay_conversions.UNDONE_STATUSES` makes.
 */

const PAID_STATUSES = new Set([
  "processing",
  "on_hold",
  "shipped",
  "delivered",
  "completed",
]);

export function isPaidStatus(status: string): boolean {
  return PAID_STATUSES.has(status);
}
