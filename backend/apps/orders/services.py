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
