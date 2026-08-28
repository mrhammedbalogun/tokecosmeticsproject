"""Read-only pricing preview for the storefront (Plan-14). Reuses compute_totals +
validate_coupon (+ optional delivery). Places nothing, mutates nothing."""
from __future__ import annotations

from decimal import Decimal

from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals
from apps.referrals.services import attribution_code_for_order, customer_discount_percent


def _lines(cart):
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


def quote(cart, country, *, user=None, email="", coupon_code="", delivery_amount=Decimal("0.00"),
          referral_code=""):
    """Return {"totals": {...string money...}, "coupon": {"ok": bool, "error_code"?: str}}.

    ``email`` (Plan-38): the guest's submitted email, so the per-email coupon limits
    the preview checks are the ones place_order will enforce. Ignored when a user is
    present — the user's own email wins, exactly as in place_order.

    ``referral_code`` (2026-08-27): the attribution cookie, so the cart can SHOW the
    referred customer's 5% before they commit. It is put through exactly the same
    `attribution_code_for_order` + `customer_discount_percent` pair `place_order` uses, on
    purpose — a preview that applies a discount the real checkout then refuses is a
    `cart_changed` error at the worst possible moment.

    It is not a security surface, though the storefront strips it from the request body
    and injects the cookie anyway. A browser that lies here changes only its own preview:
    placement reads the cookie, and the `expected_total` guard turns any disagreement into
    a refusal rather than a cheap order."""
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
        email = user.email if user is not None else email
        v = validate_coupon(
            coupon_code, base.subtotal, country, user=user, email=email, item_product_ids=product_ids
        )
        if v.ok:
            coupon = v.coupon
        else:
            coupon_result = {"ok": False, "error_code": v.error_code}
    attributed = attribution_code_for_order(referral_code, user)
    referral_percent = customer_discount_percent(
        attributed, user, email=email or (user.email if user is not None else "")
    )
    totals = compute_totals(
        lines, country, delivery_amount=delivery_amount, coupon=coupon,
        referral_discount_percent=referral_percent,
    )
    return {
        "totals": {
            "subtotal": str(totals.subtotal),
            "discount": str(totals.discount),
            "referral_discount": str(totals.referral_discount),
            # The RATE, so the summary can label the row "Referral discount (5%)" rather
            # than leaving a bare number the customer has to reverse-engineer.
            "referral_discount_percent": str(totals.referral_discount_percent),
            "delivery": str(totals.delivery),
            "tax": str(totals.tax),
            # What the tax line is CALLED in this market ("VAT", "Sales Tax", ...).
            # Rides with the numbers so the storefront never joins against /meta.
            "tax_label": country.tax_label,
            "grand_total": str(totals.grand_total),
            "currency": totals.currency,
        },
        "coupon": coupon_result,
    }
