"""mark_paid — the single 'money confirmed' entry point. Plan-09 wraps this with
gateway.verify() + an amount/currency equality check before calling it; the signature
is the seam. Order-row lock + status re-check makes it idempotent and race-safe vs the
expiry task."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import StockMovement
from apps.inventory.services import commit_sale
from apps.orders.models import Order


def _fulfillment_by_warehouse(reference: str) -> dict:
    """From the reservation ledger: {warehouse_name: qty} for this reference."""
    rows = (
        StockMovement.objects.filter(reference=reference, reason="reservation")
        .values("stock_item__warehouse__name")
        .annotate(qty=Sum("delta_reserved"))
    )
    return {r["stock_item__warehouse__name"]: r["qty"] for r in rows}


@transaction.atomic
def mark_paid(payment) -> None:
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    if order.status != "pending_payment":
        return  # already processed / expired — idempotent no-op

    commit_sale(reference=order.reservation_reference)

    fulfil = _fulfillment_by_warehouse(order.reservation_reference)
    if fulfil:
        for item in order.items.all():
            item.fulfillment_warehouses = fulfil
            item.save(update_fields=["fulfillment_warehouses"])

    if order.coupon_id:
        from apps.checkout.models import CouponRedemption

        CouponRedemption.objects.get_or_create(
            coupon_id=order.coupon_id, order_number=order.number,
            defaults={"user": order.user, "email": order.email},
        )

    payment.status = "succeeded"
    payment.save(update_fields=["status", "updated_at"])
    order.status = "processing"
    order.reservation_expires_at = None
    order.save(update_fields=["status", "reservation_expires_at", "updated_at"])
