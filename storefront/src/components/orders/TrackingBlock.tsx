/** The order's tracking section, shared by the account order-detail page (owner view) and
 * the guest tracking page (redacted view). Pure presentation — the caller fetches.
 *
 * Extracted at its SECOND consumer rather than copied: the PRE_SHIP membership below is a
 * ruling about what we promise a customer, and two copies would drift apart silently. The
 * account detail page's rendered output is unchanged by the move and its tests prove it.
 *
 * Renders nothing at all when there is neither tracking nor a promise to make — silence
 * beats an empty section. */

/** Only the three fields the block reads, so both `OrderDetail` and `OrderTracking`
 * satisfy it structurally without this component importing either page's shape.
 * Exported so tests build fixtures against the real contract rather than restating it. */
export type Trackable = { status: string; tracking_carrier: string; tracking_number: string };

/** Statuses where "no tracking yet" is a fact about TIME — the order is on its way to
 * being shipped and simply has not got there. Everything else gets no tracking section
 * at all, because the hint would be a promise we have not made:
 *
 *  - cancelled/refunded are terminal; expired and on_hold can revive
 *    (`expired -> processing` is the late-payment path), but nothing is reserved or paid
 *    while they sit there, so no shipment is owed and none should be implied.
 *  - on_hold is a fact about the ORDER, not about time: it is the triage state for
 *    migrated legacy orders AND for the Plan-14a freight-declined cohort
 *    (backend/apps/orders/services.py:59), i.e. customers we OWE A REFUND. Telling one of
 *    them tracking is coming is a false promise about the wrong direction of money.
 *  - delivered/completed are already there; shipped-without-tracking has nothing to add.
 *
 * `backend/apps/orders/state.py` ALLOWED_TRANSITIONS is the authoritative status
 * vocabulary — diff this set against its keys when the backend adds a state (same
 * discipline as StatusChip). */
const PRE_SHIP = new Set(["pending_payment", "processing"]);

export function TrackingBlock({ order }: { order: Trackable }) {
  // Blank halves filtered before the join, so a carrier recorded without a consignment
  // number (or the reverse) never renders a dangling " · ".
  const trackingLine = [order.tracking_carrier, order.tracking_number]
    .filter((v) => v && v.trim())
    .join(" · ");

  if (!trackingLine && !PRE_SHIP.has(order.status)) return null;

  return (
    <div className="mt-6">
      <h2 className="font-display text-lg">Tracking</h2>
      <p className="mt-2 text-sm text-muted">
        {trackingLine || "You'll get tracking details when your order ships."}
      </p>
    </div>
  );
}
