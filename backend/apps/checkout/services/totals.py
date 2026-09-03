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
    # What the bundles in this order take off the subtotal (Combos, 2026-09-02). Its own
    # field for the same reason `referral_discount` is: the receipt has to be able to say
    # "Combo saving" rather than folding three unrelated reasons into one number nobody
    # can reconcile. Comes off FIRST — see the ordering note in compute_totals.
    combo_discount: Decimal
    discount: Decimal
    # The referred customer's own discount, kept apart from `discount` so the cart, the
    # invoice and the confirmation email can each name it — see Order.referral_discount_total.
    referral_discount: Decimal
    referral_discount_percent: Decimal
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


def _referral_discount(percent: Decimal, base: Decimal) -> Decimal:
    """The referred customer's discount, on what is left after any coupon.

    Charged on `subtotal - coupon discount` rather than on the raw subtotal so the two
    can never together exceed the goods: a 60%-off coupon plus 5% takes 5% of the
    remaining 40%, not 65% of the order. It also matches how a shopper reads a receipt —
    each line comes off the line above it.

    Shipping is not in the base, for the same reason it is not in the commission base:
    the shop discounts its own goods, not the courier's fee.
    """
    if percent <= 0 or base <= 0:
        return Decimal("0.00")
    return min(q2(base * percent / Decimal("100")), base)


def compute_totals(
    items,
    country,
    delivery_amount=Decimal("0.00"),
    coupon=None,
    referral_discount_percent=Decimal("0.00"),
    combo_discount=Decimal("0.00"),
) -> Totals:
    """items = iterable of (ProductVariant, qty). delivery_amount already resolved by
    the caller (via apps.delivery). coupon must be pre-validated (validate_coupon).

    `referral_discount_percent` is what the REFERRED CUSTOMER gets for arriving through
    somebody's link. The caller resolves it — `referrals.services.customer_discount_percent`
    is the only thing that should — because deciding it needs the attribution code, the
    buyer's identity and their order history, none of which this function has or wants.
    Passing 0 (the default) is what every non-referred order does, and keeps this function
    byte-identical to its pre-2026-08-27 behaviour.

    `combo_discount` is what the order's bundles save against their components' list
    prices, resolved by the caller — `apps.combos.services.resolve_combo_price` via
    `cart_combo_discount` is the only thing that should — because it needs the cart's
    combo GROUPS, which `items` has already flattened away into bare (variant, qty) pairs.
    Passing 0 (the default) is what every combo-free order does, and keeps this function
    byte-identical to its pre-2026-09-02 behaviour.

    THE THREE DISCOUNTS COME OFF IN ORDER, each from what the one above it left:
    combo, then coupon, then referral. Combo is first because it is the only one that is
    a property of the GOODS rather than of the shopper — the bundle costs what it costs
    before anybody types a code — so a 20%-off coupon discounts the bundle price, not the
    list price of its parts. The alternative (coupon on the list total) would let a
    combo plus a coupon pay the customer to shop.

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

    # Clamped to the subtotal: a saving larger than the goods is impossible today (a
    # combo's price is floored at 0 and capped at its components' total) but a negative
    # goods figure would propagate into the tax base and the commission base, and neither
    # is a place to discover an impossible number.
    combo_discount = min(q2(combo_discount), subtotal)
    goods = subtotal - combo_discount
    discount = _coupon_discount(coupon, goods)
    referral_discount = _referral_discount(
        Decimal(str(referral_discount_percent)), goods - discount
    )

    delivery = q2(delivery_amount)
    if coupon is not None and coupon.type == "free_shipping":
        delivery = Decimal("0.00")

    # Both discounts leave the tax base. That is correct BECAUSE both are genuine price
    # reductions — the customer is paying less for the goods, so less tax is due on them.
    # A tender (store credit, commission spent at checkout) would have to be subtracted
    # AFTER tax instead, or the shop would under-declare VAT on goods sold at full price.
    taxable = goods - discount - referral_discount
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
        combo_discount=combo_discount,
        discount=discount,
        referral_discount=referral_discount,
        # Echoed back so the order can snapshot the rate it was actually given, and so a
        # quote can label the line "Referral discount (5%)" without asking a second source.
        referral_discount_percent=(
            Decimal(str(referral_discount_percent)) if referral_discount else Decimal("0.00")
        ),
        delivery=delivery,
        tax=tax,
        delivery_tax=delivery_tax,
        grand_total=grand_total,
        currency=country.currency.code,
    )
