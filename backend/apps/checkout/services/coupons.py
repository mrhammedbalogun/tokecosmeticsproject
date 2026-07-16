"""Coupon eligibility. Returns a CouponValidation — never raises for the normal
'invalid' cases (the API maps error_code → 400). Usage counts read the redemption
ledger; note there's a soft race on the very last use under concurrency (two
checkouts, one remaining use) — acceptable for MVP; the ledger records the truth
and admin can see overuse. Tighten with a locked counter post-launch if needed."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from apps.checkout.models import Coupon, CouponRedemption


@dataclass(frozen=True)
class CouponValidation:
    ok: bool
    error_code: str = ""
    coupon: Coupon | None = None


def _invalid(code: str) -> CouponValidation:
    return CouponValidation(ok=False, error_code=code)


def validate_coupon(
    code: str,
    subtotal: Decimal,
    country,
    user=None,
    email: str = "",
    item_product_ids: set[int] | None = None,
    item_category_ids: set[int] | None = None,
) -> CouponValidation:
    coupon = Coupon.objects.filter(code=(code or "").strip().upper()).first()
    if coupon is None:
        return _invalid("not_found")
    if not coupon.is_active:
        return _invalid("inactive")

    now = timezone.now()
    if coupon.starts_at and now < coupon.starts_at:
        return _invalid("not_started")
    if coupon.ends_at and now > coupon.ends_at:
        return _invalid("expired")

    if subtotal < coupon.min_subtotal:
        return _invalid("min_not_met")

    # A fixed coupon carries an absolute amount, so it needs a currency that matches
    # the cart. Missing currency is ambiguous → reject rather than apply cross-currency.
    if coupon.type == "fixed" and coupon.currency_id != country.currency_id:
        return _invalid("wrong_currency")

    if coupon.usage_limit is not None:
        total_used = CouponRedemption.objects.filter(coupon=coupon).count()
        if total_used >= coupon.usage_limit:
            return _invalid("exhausted")

    if coupon.usage_limit_per_user is not None:
        # Count prior redemptions for this shopper: by user if signed in, else by email.
        if user is not None:
            used = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
        elif email:
            used = CouponRedemption.objects.filter(coupon=coupon, email__iexact=email).count()
        else:
            used = 0
        if used >= coupon.usage_limit_per_user:
            return _invalid("user_exhausted")

    # applies_to gate: if the coupon restricts to products/categories, the cart must
    # contain at least one matching item (MVP: discount then applies to whole subtotal).
    restricts_products = coupon.applies_to_products.exists()
    restricts_categories = coupon.applies_to_categories.exists()
    if restricts_products or restricts_categories:
        allowed_products = set(coupon.applies_to_products.values_list("id", flat=True))
        allowed_categories = set(coupon.applies_to_categories.values_list("id", flat=True))
        matched = bool((item_product_ids or set()) & allowed_products) or bool(
            (item_category_ids or set()) & allowed_categories
        )
        if not matched:
            return _invalid("not_valid_for_items")

    return CouponValidation(ok=True, coupon=coupon)
