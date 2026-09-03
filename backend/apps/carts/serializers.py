"""Cart → JSON with live per-country pricing. Not a DRF ModelSerializer: the
output is derived (prices re-resolved), so a plain builder is clearer and cheaper
than write-serializer machinery. Views handle writes directly."""
from __future__ import annotations

from decimal import Decimal

from apps.catalog.images import storage_url, variant_image_path
from apps.combos.services import pricing_for_cart
from apps.pricing.services import resolve_price

TWO_DP = Decimal("0.01")


def _line(item, country) -> dict:
    resolved = resolve_price(item.variant, country)
    v = item.variant
    base = {
        "id": item.id,
        "variant_id": v.id,
        "sku": v.sku,
        "name": v.product.name,
        "variant_name": v.option_values or {},
        "quantity": item.quantity,
        # Same picture the confirmation email and the order page show — one answer,
        # from apps/catalog/images.py. Thumbnail-first (256px, ~20KB) because every
        # consumer of this field renders it small: a 64px square in the cart drawer.
        "image": storage_url(variant_image_path(v)) or None,
        # Lets the cart link back to the product page it was added from.
        "product_slug": v.product.slug,
    }
    if resolved is None:
        base.update(unit_price=None, line_total=None, unavailable=True)
        return base
    unit = resolved.amount.quantize(TWO_DP)
    base.update(
        unit_price=str(unit),
        line_total=str((unit * item.quantity).quantize(TWO_DP)),
        unavailable=False,
    )
    return base


def _combo_group(group, country) -> dict:
    """One bundle in the bag: the box, what is in it, and what it saves.

    The component rows come out at their FULL prices, deliberately. The saving is stated
    once, as a number, rather than smeared across four lines nobody can check — which is
    also exactly how it reaches the order (`Order.combo_discount_total`), so the cart and
    the receipt tell the same story.

    ── `ended` IS ABOUT THE DEAL, NOT ABOUT THE GOODS ──────────────────────────────────

    When a bundle is archived or withdrawn from this market, `pricing_for_cart` says no
    and the DISCOUNT stops — but the component lines are still real rows that checkout
    will still charge for. So the money here keeps counting them, at full price, with a
    zero saving. Zeroing the whole group instead was the first version of this function
    and it was wrong in the worst direction: the cart showed 0.00 for goods the till
    would charge in full, which is a `cart_changed` refusal at the pay button, or worse,
    a shopper who thinks something is free.
    """
    combo = group.combo
    # `pricing_for_cart`, not `resolve_combo_price`: a bundle that has been archived or
    # withdrawn from this market earns nothing here AND nothing at checkout
    # (`cart_combo_discount` calls the same function), so the card and the till agree.
    pricing = pricing_for_cart(combo, country)
    lines = [_line(i, country) for i in group.items.all()]
    # What the goods in this box actually cost, summed from the rows themselves. This is
    # the figure the subtotal uses whether the deal stands or not.
    goods = sum(
        (Decimal(line["line_total"]) for line in lines if not line["unavailable"]),
        Decimal("0.00"),
    ).quantize(TWO_DP)
    base = {
        "group_id": group.id,
        "combo_slug": combo.slug,
        "name": combo.name,
        "image": storage_url(combo.image.name) if combo.image else None,
        "quantity": group.quantity,
        "items": lines,
        "components_total": str(goods),
    }
    if pricing is None:
        base.update(
            unit_price=None,
            line_total=str(goods),
            saving="0.00",
            saving_percent="0.00",
            # The deal has ended; the goods have not. The storefront says exactly that
            # rather than "no longer available", which would be a lie about the products.
            ended=True,
            # Only true when a COMPONENT cannot be priced at all — the state that really
            # does mean "this cannot be bought here".
            unavailable=any(line["unavailable"] for line in lines),
        )
        return base
    base.update(
        unit_price=str(pricing.amount),
        line_total=str((pricing.amount * group.quantity).quantize(TWO_DP)),
        components_total=str((pricing.components_total * group.quantity).quantize(TWO_DP)),
        saving=str((pricing.saving * group.quantity).quantize(TWO_DP)),
        saving_percent=str(pricing.saving_percent),
        ended=False,
        unavailable=False,
    )
    return base


def serialize_cart(cart, country) -> dict:
    """The bag, priced.

    ── WHAT THE THREE MONEY FIELDS MEAN ────────────────────────────────────────────
    They mirror `checkout.services.totals.compute_totals` exactly, because the cart and
    the checkout summary must never appear to disagree:

      subtotal       every line at its LIST price, combo components included
      combo_discount what the bundles STILL RUNNING take off that
      total          subtotal - combo_discount, i.e. what the goods actually cost

    `items` carries STANDALONE lines only; a combo's components are nested inside its
    entry in `combos` instead. Rendering them twice is the obvious bug here, and keeping
    the two lists disjoint is what makes it impossible rather than merely unlikely.
    """
    # prefetch the image sets: `variant_image_path` looks at variant.images then
    # product.images for every line, which is two extra queries per line without this.
    lines = (
        cart.items.select_related("variant__product")
        .prefetch_related("variant__images", "variant__product__images")
        .filter(combo_group__isnull=True)
    )
    items = [_line(i, country) for i in lines]

    from apps.carts.services import combo_groups

    combos = [_combo_group(g, country) for g in combo_groups(cart)]

    def _sum(values) -> Decimal:
        return sum(values, Decimal("0.00")).quantize(TWO_DP)

    standalone = _sum(Decimal(i["line_total"]) for i in items if not i["unavailable"])
    # `components_total` counts whether the deal stands or not — those rows are goods the
    # till will charge for either way. `saving` is 0.00 for an ended bundle, so the
    # discount falls away on its own without a second condition to keep in step.
    combo_list = _sum(Decimal(c["components_total"]) for c in combos)
    combo_discount = _sum(Decimal(c["saving"]) for c in combos)
    subtotal = (standalone + combo_list).quantize(TWO_DP)
    return {
        "id": str(cart.id),
        "kind": cart.kind,
        "status": cart.status,
        "country": country.code,
        "currency": country.currency.code,
        "items": items,
        "combos": combos,
        "subtotal": str(subtotal),
        "combo_discount": str(combo_discount),
        "total": str((subtotal - combo_discount).quantize(TWO_DP)),
        "has_unavailable": any(i["unavailable"] for i in items)
        or any(c["unavailable"] for c in combos),
    }
