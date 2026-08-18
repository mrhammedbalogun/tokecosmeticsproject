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
    # The slice of `tax` sitting on the delivery fee (0 unless the market taxes
    # delivery). Kept separate because referral commissions must subtract ITEM tax
    # only — see apps/referrals/services.commission_base.
    delivery_tax: Decimal
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
    the caller (via apps.delivery). coupon must be pre-validated (validate_coupon).

    Tax is charged only when BOTH switches are on — the store-wide master
    (`StoreSettings.charge_tax`) and the market's own (`Country.charge_tax`). When
    either is off the customer pays exactly the admin-entered price: for an
    inclusive-price market the grand total is identical either way, the tax line just
    reads 0 and the storefront hides it.
    """
    from apps.core.models import StoreSettings

    charging = StoreSettings.load().charge_tax and country.charge_tax
    rate = country.tax_rate_percent / Decimal("100") if charging else Decimal("0")
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
    # The delivery fee joins the tax base only where the market says so (UK VAT
    # applies to shipping; NG practice does not).
    taxed_delivery = delivery if (rate and country.tax_applies_to_delivery) else Decimal("0.00")
    if country.prices_include_tax:
        # Tax is the portion already inside the amounts: base - base/(1+r). The grand
        # total never moves — inclusive means the price already contains it.
        def _inside(base: Decimal) -> Decimal:
            return q2(base - (base / (Decimal("1") + rate))) if rate else Decimal("0.00")

        tax = _inside(taxable + taxed_delivery)
        delivery_tax = _inside(taxed_delivery)
        grand_total = q2(taxable + delivery)
    else:
        tax = q2((taxable + taxed_delivery) * rate)
        delivery_tax = q2(taxed_delivery * rate)
        grand_total = q2(taxable + tax + delivery)

    return Totals(
        subtotal=subtotal,
        discount=discount,
        delivery=delivery,
        tax=tax,
        delivery_tax=delivery_tax,
        grand_total=grand_total,
        currency=country.currency.code,
    )
