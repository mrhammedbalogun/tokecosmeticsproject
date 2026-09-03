"""Read-only pricing preview for the storefront (Plan-14). Reuses compute_totals +
validate_coupon (+ optional delivery). Places nothing, mutates nothing."""
from __future__ import annotations

from decimal import Decimal

from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals
from apps.combos.services import cart_combo_discount
from apps.referrals.services import attribution_code_for_order, customer_discount_percent


def _lines(cart):
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


def quote(cart, country, *, user=None, email="", phone="", coupon_code="",
          delivery_amount=Decimal("0.00"), referral_code=""):
    """Return {"totals": {...string money...}, "coupon": {"ok": bool, "error_code"?: str}}.

    ``email`` (Plan-38): the guest's submitted email, so the per-email coupon limits
    the preview checks are the ones place_order will enforce. Ignored when a user is
    present — the user's own email wins, exactly as in place_order.

    ``phone`` (2026-08-28): the guest's submitted phone, used for nothing but the
    self-referral guard, and there only so this preview reaches the SAME verdict
    placement will. A guest quoting from /cart has typed neither yet, so the cart page
    previews the discount on the strength of the code alone and the review step — where
    the contact details exist — is where a self-referring guest sees it withdrawn. That
    is the right place for it to happen: before the pay button rather than as a
    `cart_changed` refusal at it.

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
    combo_discount = cart_combo_discount(cart, country)
    # Captured BEFORE the coupon block, which rebinds `email` to the user's own address
    # when there is a user. Attribution wants the GUEST's details specifically, and
    # reading a rebound variable further down is exactly the kind of quiet coupling that
    # breaks the next time these two blocks are reordered.
    guest_email, guest_phone = ("", "") if user is not None else (email, phone)
    # Subtotal first — validate_coupon's min-spend (min_not_met) check needs it.
    base = compute_totals(lines, country, combo_discount=combo_discount)  # no coupon, no delivery
    coupon = None
    coupon_result = {"ok": True}
    if coupon_code:
        # Mirrors apps/checkout/services/checkout.py's place_order call: same kwargs
        # (item_product_ids from the cart lines, email from the user) so a quote and
        # the real checkout never disagree about whether a coupon applies.
        product_ids = {v.product_id for v, _ in lines}
        email = user.email if user is not None else email
        # The POST-BUNDLE goods figure, matching `place_order`: a min-spend must be met
        # by what the customer actually pays for the goods, not by the list price of
        # parts they bought at a discount.
        v = validate_coupon(
            coupon_code, base.subtotal - base.combo_discount, country, user=user,
            email=email, item_product_ids=product_ids
        )
        if v.ok:
            coupon = v.coupon
        else:
            coupon_result = {"ok": False, "error_code": v.error_code}
    attributed = attribution_code_for_order(
        referral_code, user, email=guest_email, phone=guest_phone
    )
    referral_percent = customer_discount_percent(
        attributed, user, email=guest_email or (user.email if user is not None else "")
    )
    totals = compute_totals(
        lines, country, delivery_amount=delivery_amount, coupon=coupon,
        referral_discount_percent=referral_percent, combo_discount=combo_discount,
    )
    return {
        "totals": {
            "subtotal": str(totals.subtotal),
            "discount": str(totals.discount),
            # What the order's bundles took off. Its own row so the summary can say
            # "Combo saving" rather than leaving the customer to reconcile three
            # reductions folded into one number.
            "combo_discount": str(totals.combo_discount),
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
