"""The order state machine — the ONLY thing in the codebase that writes `order.status`.

Two rules make this work, and both are load-bearing:

1. **Every caller holds the row lock.** `transition()` asserts it is inside a transaction
   and assumes the caller has already `select_for_update()`-ed the order. Without that,
   an admin marking an order shipped can race the expiry task or a payment webhook and
   validate against a status that is already stale. `transition_by_id()` is the wrapper
   for callers that don't hold the lock yet (admin views); code already inside a locked
   block (payments, the expiry task) calls `transition()` directly.

2. **Deferred side-effects run after commit, never inside the lock.** Registering an
   on_commit callback is a pure in-memory append, so it is safe under the lock — which is
   what lets `_fulfil_locked` route through here without smuggling a Redis round-trip into
   a `select_for_update`. The callback itself (enqueuing a Celery task) runs after the
   outermost atomic block commits, so the worker can never read pre-commit state.

There is deliberately no "fast path" that skips validation for machine-driven writes.
That is precisely how "nothing sets status directly" stops being true.
"""
from __future__ import annotations

from functools import partial

from django.db import transaction

from apps.orders.models import Order, OrderEvent

# `cancelled` means no money was ever captured; a paid order exits via `refunded`. That
# invariant is why `processing -> cancelled` is absent: it removes the "admin cancelled a
# paid order, where did the money go?" ambiguity, and means cancel never owes a refund.
#
# Not present as statuses, by design: `needs_review` (orthogonal — Order.review_reason)
# and `partially_refunded` (a payment-ledger fact — payment.status + the Refund rows).
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending_payment": {"processing", "expired", "cancelled"},
    "expired": {"processing", "cancelled"},  # processing = the late-payment re-reserve path
    "processing": {"shipped", "on_hold", "refunded"},
    "shipped": {"delivered", "on_hold", "refunded"},  # lost parcel -> full refund
    "delivered": {"completed", "refunded"},  # completed by staff or the 14-day beat task
    "completed": {"refunded"},  # post-completion return
    # Triage state for migrated legacy orders whose true state is unknown. Broad on
    # purpose. Legacy orders with a KNOWN terminal status migrate straight to it.
    "on_hold": {"processing", "shipped", "delivered", "completed", "cancelled", "refunded"},
    "cancelled": set(),  # terminal
    "refunded": set(),  # terminal
}

STATUSES = frozenset(ALLOWED_TRANSITIONS)


class IllegalTransition(Exception):
    """Refused: this order cannot move from where it is to where you asked."""

    def __init__(self, from_status: str, to_status: str):
        self.from_status, self.to_status = from_status, to_status
        allowed = ", ".join(sorted(ALLOWED_TRANSITIONS.get(from_status, ()))) or "nothing"
        super().__init__(f"{from_status} -> {to_status} is not allowed (can go to: {allowed})")


def record_event(order, type: str, *, actor=None, message: str = "") -> OrderEvent:
    """Write a timeline entry without moving the order. For things that happen TO an
    order but aren't lifecycle moves: placement, notes, tracking, resolving a flag."""
    return OrderEvent.objects.create(order=order, type=type, actor=actor, message=message)


def transition(order, to_status: str, *, actor=None, message: str = "", effects=None):
    """Move `order` to `to_status`, writing the audit event and scheduling side-effects.

    The caller MUST already hold the order's row lock inside an atomic block.

    `effects` are callables invoked with the order's pk AFTER the outermost transaction
    commits — that is where emails belong. Effects that must be atomic with the status
    flip (releasing a stock reservation on cancel, say) are the caller's job and belong
    inside the caller's locked block, not here.

    Note what this does NOT do: it never touches `review_reason`. Clearing that is an
    explicit admin act (`resolve_review`), because auto-clearing here would silently
    erase an unresolved double-payment flag the moment staff marked the order shipped.
    """
    assert transaction.get_connection().in_atomic_block, (
        "transition() must be called inside a transaction, with the order row locked"
    )
    if to_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise IllegalTransition(order.status, to_status)

    order.status = to_status
    order.save(update_fields=["status", "updated_at"])
    event = record_event(order, f"status:{to_status}", actor=actor, message=message)

    for effect in effects or ():
        transaction.on_commit(partial(effect, order.pk))
    return event


def transition_by_id(order_id: int, to_status: str, **kwargs):
    """Lock-acquiring wrapper for callers that aren't already inside a locked block —
    i.e. admin views. Validates against the LOCKED row, not a stale read."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        return transition(order, to_status, **kwargs)


def resolve_review(order_id: int, *, actor=None, message: str = ""):
    """Clear the needs-attention flag. The ONLY thing that clears `review_reason`, and it
    leaves an event behind saying who decided it was resolved."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        was = order.review_reason
        order.review_reason = ""
        order.save(update_fields=["review_reason", "updated_at"])
        return record_event(
            order, "review_resolved", actor=actor, message=message or f"resolved: {was}"
        )
