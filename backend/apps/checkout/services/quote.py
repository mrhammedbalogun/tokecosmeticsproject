"""Read-only pricing preview for the storefront (Plan-14). Reuses compute_totals +
validate_coupon (+ optional delivery). Places nothing, mutates nothing."""
from __future__ import annotations

from decimal import Decimal

from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals


def _lines(cart):
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


def quote(cart, country, *, user=None, coupon_code="", delivery_amount=Decimal("0.00")):
    """Return {"totals": {...string money...}, "coupon": {"ok": bool, "error_code"?: str}}."""
    lines = _lines(cart)
    # Subtotal first — validate_coupon's min-spend (min_not_met) check needs it.
    base = compute_totals(lines, country)  # no coupon, no delivery
    coupon = None
    coupon_result = {"ok": True}
    if coupon_code:
        # Mirrors apps/checkout/services/checkout.py's place_order call: same kwargs
        # (item_product_ids from the cart lines, email from the user) so a quote and
        # the real checkout never disagree about whether a coupon applies.
        product_ids = {v.product_id for v, _ in lines}
        email = user.email if user is not None else ""
        v = validate_coupon(
            coupon_code, base.subtotal, country, user=user, email=email, item_product_ids=product_ids
        )
        if v.ok:
            coupon = v.coupon
        else:
            coupon_result = {"ok": False, "error_code": v.error_code}
    totals = compute_totals(lines, country, delivery_amount=delivery_amount, coupon=coupon)
    return {
        "totals": {
            "subtotal": str(totals.subtotal),
            "discount": str(totals.discount),
            "delivery": str(totals.delivery),
            "tax": str(totals.tax),
            "grand_total": str(totals.grand_total),
            "currency": totals.currency,
        },
        "coupon": coupon_result,
    }
