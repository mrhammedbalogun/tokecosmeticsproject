"""Order operations that are more than a bare status move."""
from __future__ import annotations

from django.db import transaction

from apps.inventory.services import release
from apps.orders.models import Order
from apps.orders.state import transition


def cancel_order(order_id: int, *, actor=None, message: str = ""):
    """Cancel an unpaid order and free the stock it was holding.

    The release is deliberately INSIDE the lock and NOT an on_commit effect: freeing the
    stock must be atomic with the status flip. If the flip rolled back after a deferred
    release had already run, the order would be live again with no reservation behind it.

    Only reachable for unpaid orders — `cancelled` means no money was ever captured, and
    ALLOWED_TRANSITIONS enforces it. That ordering matters here: transition() validates
    BEFORE release() runs, so a refused cancel on a paid order cannot free stock that has
    already been sold, which would let the same unit be sold twice.

    This is the only path that frees a cancelled order's stock. expire_pending_orders
    sweeps `pending_payment` only, so an order cancelled without a release would hold that
    stock away from real buyers forever, with nothing left in the system to reclaim it.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        event = transition(order, "cancelled", actor=actor, message=message)
        if order.reservation_reference:
            release(reference=order.reservation_reference)  # ledger-idempotent
        order.reservation_expires_at = None
        order.save(update_fields=["reservation_expires_at", "updated_at"])
        return event


def orders_owed_a_refund():
    """The 'refunds owed' worklist: orders where a paid customer is still owed a manual
    goods refund because their freight quote was cancelled.

    cancel_quote (apps/shipping/services.py) parks a PAID order at `on_hold` and does not
    move any money — a human records the goods refund later via record_manual_refund. This
    debt is otherwise invisible, and a solo operator forgets it, so this is the queue that
    surfaces it. See docs/architecture.md § "Rest-of-World freight quotes (Plan-14a)".

    The predicate is on the QUOTE, not a new Order status: `on_hold` alone is ambiguous
    (the model also uses it for migrated orders), so `shipping_quote.status == "cancelled"`
    is what identifies the freight-decline flow specifically.

    Why `on_hold` needs no explicit "not yet refunded" clause: a FULL manual refund
    transitions the order off `on_hold` to `refunded` (apply_succeeded_refund), so any
    order still sitting at `on_hold` here is by definition not fully refunded — the debt is
    live. A PARTIAL refund leaves the order at `on_hold`, so it correctly STAYS on the
    queue (money is still owed); the outstanding figure is computed for display, not used
    to gate membership. Filtering out "any order with a succeeded refund" would instead
    hide a half-paid debt, which is the opposite of safe.
    """
    return (
        Order.objects.filter(status="on_hold", shipping_quote__status="cancelled")
        .order_by("placed_at", "pk")
    )
