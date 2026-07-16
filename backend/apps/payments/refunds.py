"""Refunds — staff-initiated, gateway-executed, race-safe.

Two phases, mirroring confirm_payment's discipline (never hold a row lock across a
network call):

  Phase 1 (locked): re-read the Payment FOR UPDATE, compute the remaining refundable
     amount from a DB aggregate of succeeded + pending refunds, and write a `pending`
     Refund row. That row RESERVES the amount — a concurrent staff refund's aggregate
     immediately sees it, so two admins can't both pass an `amount <= remaining` check.
  Phase 2 (unlocked): call the gateway, then record the outcome. A failed refund frees
     its amount automatically because the aggregate only counts succeeded + pending.

Restock is deliberately restricted to FULL refunds: the fulfillment_warehouses snapshot
tells us where each line shipped from, but not which lines a partial refund covers.
Per-item restock belongs with the Plan-19 admin UI that can actually ask.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from functools import partial

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import StockItem
from apps.inventory.services import adjust
from apps.orders.emails import enqueue_refund_processed
from apps.orders.models import Order
from apps.orders.state import transition
from apps.payments.gateways.base import GatewayError
from apps.payments.gateways.registry import get_gateway
from apps.payments.models import Payment, Refund
from apps.payments.money import format_money

logger = logging.getLogger(__name__)

# A refund can only be taken against money we actually collected.
_REFUNDABLE_PAYMENT_STATES = frozenset({"succeeded", "partially_refunded"})
# Refunds that still hold a claim on the payment's balance.
_LIVE_REFUND_STATES = ["succeeded", "pending"]


class RefundError(Exception):
    def __init__(self, code: str, detail: str, http: int = 400, extra: dict | None = None):
        self.code = code
        self.detail = detail
        self.http = http
        self.extra = extra or {}
        super().__init__(detail)


def refundable_amount(payment) -> Decimal:
    """What's left to refund: the payment total minus everything already refunded or
    in-flight. Computed from the DB, never from a cached field."""
    used = payment.refunds.filter(status__in=_LIVE_REFUND_STATES).aggregate(
        s=Sum("amount")
    )["s"] or Decimal("0")
    return payment.amount - used


def create_refund(*, payment, amount: Decimal, reason: str = "", user=None,
                  restock: bool = False) -> Refund:
    amount = Decimal(str(amount))
    if amount <= 0:
        raise RefundError("invalid_amount", "Refund amount must be positive.")

    # --- Phase 1: reserve the amount under the payment lock ---
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.status not in _REFUNDABLE_PAYMENT_STATES:
            raise RefundError(
                "payment_not_refundable",
                f"Payment is {locked.status}; only a collected payment can be refunded.",
            )
        remaining = refundable_amount(locked)
        if amount > remaining:
            raise RefundError(
                "amount_exceeds_remaining",
                f"Refund of {amount} exceeds the remaining {remaining}.",
                extra={"remaining": str(remaining)},
            )
        if restock and amount != locked.amount:
            raise RefundError(
                "restock_requires_full_refund",
                "Restock is only supported on a full refund; refund without restock and "
                "adjust stock manually for partial returns.",
            )
        refund = Refund.objects.create(
            payment=locked, amount=amount, reason=reason, status="pending", created_by=user
        )

    # --- Phase 2: gateway call, OUTSIDE the lock ---
    try:
        result = get_gateway(payment.gateway).refund(payment, amount, reason)
    except GatewayError as exc:
        refund.status = "failed"
        refund.raw_response = {"error": str(exc)}
        refund.save(update_fields=["status", "raw_response", "updated_at"])
        logger.warning("Refund %s failed at gateway: %s", refund.pk, exc)
        raise

    refund.status = result.status
    refund.gateway_reference = result.gateway_reference
    refund.raw_response = result.raw
    refund.save(update_fields=["status", "gateway_reference", "raw_response", "updated_at"])

    if refund.status == "succeeded":
        apply_succeeded_refund(refund, restock=restock, user=user)
    return refund


def apply_succeeded_refund(refund, *, restock: bool = False, user=None) -> None:
    """Roll a succeeded refund up onto the Payment and Order. Also the entry point for a
    refund-completion webhook advancing an async (pending) refund."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
        succeeded = payment.refunds.filter(status="succeeded").aggregate(
            s=Sum("amount")
        )["s"] or Decimal("0")
        fully = succeeded >= payment.amount
        payment.status = "refunded" if fully else "partially_refunded"
        payment.save(update_fields=["status", "updated_at"])

        # Refund progress is a payment-ledger fact, carried by payment.status and the
        # Refund rows. Only a FULL refund is a lifecycle move (the order is commercially
        # dead). A partial refund must leave the lifecycle alone: stomping a `shipped`
        # order to `partially_refunded` drops it out of the packing/delivery pipeline
        # while the customer is still owed the rest of the parcel.
        # Enqueued explicitly rather than via transition()'s effect table: a PARTIAL
        # refund has no transition to hang an effect off (the lifecycle is deliberately
        # untouched), and the amount refunded isn't derivable from a destination status.
        # on_commit for the usual reason — the worker must not read pre-commit state.
        transaction.on_commit(
            partial(enqueue_refund_processed, payment.order_id, format_money(refund.amount, payment.currency))
        )

        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if fully and order.status != "refunded":
            # Guarded rather than unconditional: this is also the async refund-completion
            # webhook's entry point, and gateways redeliver. A replay must be a no-op, not
            # an IllegalTransition (refunded -> refunded) or a duplicate timeline entry.
            transition(
                order,
                "refunded",
                actor=user,
                message=f"refund {refund.pk} settled at {payment.gateway}",
            )

        if restock:
            _restock(order, user)


# Event-type fragments that mean "this refund settled successfully" / "it failed".
# Kept here (not in the adapters) because it's a policy question, not a protocol one.
_REFUND_SUCCESS_HINTS = ("processed", "completed", "succeeded", "refunded")
_REFUND_FAILURE_HINTS = ("failed", "declined", "reversed")


def advance_refund_from_event(payment, *, event_type: str, refund_reference: str = "") -> str:
    """Settle an async (pending) refund when its completion webhook lands.

    Flutterwave, PayPal and Paystack all report refunds as `pending` on initiate and
    finish them out-of-band, so without this a refunded order would sit in
    partially_refunded forever. Matches by the gateway's refund id when the event carries
    one, else falls back to this payment's pending refunds (the common single-refund case).
    """
    lowered = event_type.lower()
    if any(hint in lowered for hint in _REFUND_FAILURE_HINTS):
        new_status = "failed"
    elif any(hint in lowered for hint in _REFUND_SUCCESS_HINTS):
        new_status = "succeeded"
    else:
        return "refund_event_ignored"

    pending = payment.refunds.filter(status="pending")
    if refund_reference:
        matched = pending.filter(gateway_reference=refund_reference)
        pending = matched if matched.exists() else pending

    refund = pending.order_by("created_at").first()
    if refund is None:
        logger.info("Refund event %s for payment %s matched no pending refund",
                    event_type, payment.pk)
        return "no_pending_refund"

    refund.status = new_status
    refund.save(update_fields=["status", "updated_at"])
    if new_status == "succeeded":
        # restock=False: a webhook can't know the operator's restock intent; the original
        # staff request already restocked if it was asked to and settled synchronously.
        apply_succeeded_refund(refund, restock=False)
    return f"refund_{new_status}"


def _restock(order, user) -> None:
    """Put the goods back where they came from, using the fulfillment_warehouses snapshot
    written at fulfilment — never a guess about which warehouse shipped what."""
    for item in order.items.select_related("variant"):
        if item.variant_id is None:
            continue  # variant deleted since; nothing to restock against
        for warehouse_name, qty in (item.fulfillment_warehouses or {}).items():
            stock_item = (
                StockItem.objects.select_for_update()
                .filter(variant=item.variant, warehouse__name=warehouse_name)
                .first()
            )
            if stock_item is None:
                logger.warning(
                    "Restock skipped: no stock row for %s at %s", item.sku, warehouse_name
                )
                continue
            # Read the quantity under the lock we just took, so the absolute set can't
            # clobber a concurrent change.
            adjust(stock_item, stock_item.quantity + qty, reason="returned",
                   note=f"refund of {order.number}", user=user)
