"""compute_totals — the ONLY place order money is calculated. Used by cart display,
checkout, and order creation, so they can never disagree. Re-resolves every line via
resolve_price (snapshots are display-only). Rounds half-up per line, then sums."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.pricing.services import resolve_price

CENT = Decimal("0.01")


def q2(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    discount: Decimal
    delivery: Decimal
    tax: Decimal
    grand_total: Decimal
    currency: str


def _coupon_discount(coupon, subtotal: Decimal) -> Decimal:
    """Discount amount on the subtotal. free_shipping discounts nothing here (it
    zeroes delivery instead). Never exceeds the subtotal."""
    if coupon is None or coupon.type == "free_shipping":
        return Decimal("0.00")
    value = Decimal(coupon.value)  # coerce: factory-built instances hold a str value
    if coupon.type == "percent":
        raw = subtotal * (value / Decimal("100"))
    else:  # fixed
        raw = value
    return min(q2(raw), subtotal)


def compute_totals(items, country, delivery_amount=Decimal("0.00"), coupon=None) -> Totals:
    """items = iterable of (ProductVariant, qty). delivery_amount already resolved by
    the caller (via apps.delivery). coupon must be pre-validated (validate_coupon)."""
    rate = country.tax_rate_percent / Decimal("100")
    subtotal = Decimal("0.00")
    for variant, qty in items:
        resolved = resolve_price(variant, country)
        if resolved is None:
            raise ValueError(f"Variant {variant.sku} has no price in {country.code}")
        subtotal += q2(resolved.amount) * qty
    subtotal = q2(subtotal)

    discount = _coupon_discount(coupon, subtotal)

    delivery = q2(delivery_amount)
    if coupon is not None and coupon.type == "free_shipping":
        delivery = Decimal("0.00")

    taxable = subtotal - discount
    if country.prices_include_tax:
        # Tax is the portion already inside the price: taxable - taxable/(1+r).
        tax = q2(taxable - (taxable / (Decimal("1") + rate))) if rate else Decimal("0.00")
        grand_total = q2(taxable + delivery)
    else:
        tax = q2(taxable * rate)
        grand_total = q2(taxable + tax + delivery)

    return Totals(
        subtotal=subtotal,
        discount=discount,
        delivery=delivery,
        tax=tax,
        grand_total=grand_total,
        currency=country.currency.code,
    )
