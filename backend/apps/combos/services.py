"""What a combo costs, where it is buyable, and how many of it can be bought.

THE ONE PLACE COMBO MONEY IS DECIDED, in the same sense that
`apps.pricing.services.resolve_price` is for a variant and
`apps.checkout.services.totals.compute_totals` is for an order. The storefront's price
tag, the cart's saving line, the checkout preview and `place_order` all come through
`resolve_combo_price`, so they cannot disagree about what a bundle costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.catalog.services import sellable_in
from apps.pricing.services import resolve_price

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def q2(amount) -> Decimal:
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ComboPricing:
    """What a combo costs in one market, and what it saves against buying the parts.

    `components_total` is what the same variants would cost bought separately at today's
    prices — the honest strike-through number, recomputed on every read rather than
    stored, so it can never be a stale claim about a discount.
    """

    components_total: Decimal
    amount: Decimal
    saving: Decimal
    saving_percent: Decimal
    currency: str
    pinned: bool


def component_lines(combo) -> list[tuple]:
    """[(ProductVariant, quantity)] — the shape everything downstream already speaks.

    Delivery quoting, `compute_totals`, `reserve` and `OrderItem` all take exactly this,
    which is why a combo needs no special case in any of them.
    """
    return [(item.variant, item.quantity) for item in combo.items.all()]


def components_total(combo, country) -> Decimal | None:
    """What the parts cost separately in this market, or None if ANY of them has no price.

    None rather than a partial sum on purpose: a bundle missing one component's price is
    not cheap, it is unpriceable, and the storefront must hide it rather than sell four
    items for the price of three. Same "hide until priced" rule as `sellable_in`.
    """
    items = list(combo.items.all())
    if not items:
        return None
    total = ZERO
    for item in items:
        resolved = resolve_price(item.variant, country)
        if resolved is None:
            return None
        total += q2(resolved.amount) * item.quantity
    return q2(total)


# Where `attach_pricing` parks its answer. An attribute rather than a module-level dict
# so it cannot outlive the objects it describes.
_MEMO = "_resolved_pricing"


def attach_pricing(combos, country) -> list:
    """Resolve each combo's price ONCE and park it on the instance. Returns the list.

    THE READ PATH ASKED THE SAME QUESTION THREE TIMES. `available_in` calls
    `resolve_combo_price`, then the serializer calls it again for `pricing`, and
    `unsellable_components` walks the same items in between — so a three-combo list cost
    59 queries, 29 of them price lookups, and it grew linearly. Measured, not guessed.

    This is the same shape as `catalog.services.annotate_min_price`: the view prepares
    what the serializer will need, and the serializer reads it through a `getattr` fast
    path that still works when nobody prepared anything (the admin's detail view, a
    wishlist serializing a lone instance).

    Deliberately NOT a cache with a lifetime. It lives exactly as long as the Python
    objects the view built, which is one request — so it cannot go stale between a write
    and the response that follows it, the way a keyed cache would.
    """
    for combo in combos:
        setattr(combo, _MEMO, (country.code, _resolve_combo_price(combo, country)))
    return list(combos)


def resolve_combo_price(combo, country) -> ComboPricing | None:
    """The public entry point: the parked answer when the view prepared one, else fresh.

    The country is part of the parked key because one process serves every market, and a
    price resolved for NG must never be handed back for GB.
    """
    parked = getattr(combo, _MEMO, None)
    if parked is not None and parked[0] == country.code:
        return parked[1]
    return _resolve_combo_price(combo, country)


def _resolve_combo_price(combo, country) -> ComboPricing | None:
    """The combo's price in `country`, or None when it cannot be priced there.

    A pinned `ComboPrice` wins; otherwise `discount_percent` comes off the component
    total. The pinned amount is clamped to the component total — a "combo" that costs
    MORE than buying the parts is a data-entry accident, and charging it would be the
    kind of wrongness a customer screenshots.
    """
    total = components_total(combo, country)
    if total is None:
        return None
    pinned_row = next((p for p in combo.prices.all() if p.country_id == country.code), None)
    if pinned_row is not None:
        amount = min(q2(pinned_row.amount), total)
        pinned = True
    else:
        percent = Decimal(combo.discount_percent or 0)
        amount = q2(total * (Decimal("100") - percent) / Decimal("100"))
        pinned = False
    amount = max(amount, ZERO)
    saving = q2(total - amount)
    percent_off = (
        q2(saving * Decimal("100") / total) if total > 0 else ZERO
    )
    return ComboPricing(
        components_total=total,
        amount=amount,
        saving=saving,
        saving_percent=percent_off,
        currency=country.currency.code,
        pinned=pinned,
    )


def unsellable_components(combo, country) -> list:
    """The `ComboItem`s that stop this bundle being sold in `country`. Empty = none do.

    THREE CHECKS, and the first two are the ones `sellable_in` cannot make.
    `apps.catalog.services.sellable_in` asks a PRODUCT-level question — "is any active
    variant of this product priced here?" — which is the right question for a product
    page and the wrong one for a bundle. A combo names ONE VARIANT, so:

      * `variant.is_active` — a variant the merchant switched off. The standalone
        add-to-cart path has always refused these (`CartItemsView` looks up with
        `is_active=True`); before this check a combo was the one way to buy one.
      * `product.status` — a draft or archived product never appears in the shop, and a
        bundle must not be the back door to it. Draft components are still PICKABLE in
        the builder on purpose (bundles get built ahead of a launch); this is what keeps
        the finished bundle off the shelf until the launch happens.
      * `sellable_in` — the market and "hide until priced" rules, unchanged.

    Returns the offending items rather than a bare False so the admin can say WHICH
    product is holding the bundle back, which is the difference between a warning
    somebody can act on and one they have to investigate.
    """
    problems = []
    # `sellable_in` is a PRODUCT-level question and costs two queries per call (it does
    # `product.variants.filter(...)`, which bypasses any prefetch). A bundle routinely
    # holds two variants of one product — two sizes of the same serum — so the answer is
    # memoised for the length of this call. The variant-level checks are prefetch-served
    # and short-circuit before it, so a switched-off variant costs nothing at all.
    seen_products: dict[int, bool] = {}
    for item in combo.items.all():
        variant = item.variant
        if not variant.is_active or variant.product.status != "active":
            problems.append(item)
            continue
        product_id = variant.product_id
        if product_id not in seen_products:
            seen_products[product_id] = sellable_in(variant.product, country)
        if not seen_products[product_id]:
            problems.append(item)
    return problems


def market_allowed(combo, country) -> bool:
    """Empty `available_countries` = everywhere, exactly like a Product's."""
    allowed = combo.available_countries.all()
    return not allowed or any(c.code == country.code for c in allowed)


def available_in(combo, country) -> bool:
    """Is this combo buyable in this market right now?

    Four things, all of which must hold: it is active, the market is allowed, every
    component is itself sellable there (`unsellable_components`), and the whole bundle
    prices. A combo whose component was archived last night stops being offered without
    anybody editing the combo — which is the behaviour that keeps a curated list from
    rotting.
    """
    if combo.status != "active":
        return False
    if not market_allowed(combo, country):
        return False
    items = list(combo.items.all())
    if not items:
        return False
    if unsellable_components(combo, country):
        return False
    return resolve_combo_price(combo, country) is not None


def max_addable(combo, country) -> int:
    """How many WHOLE combos the shelves can currently fill.

    The binding constraint is the scarcest component: two jars of a thing that appears
    twice in the box is one combo, not two. Returns 0 when anything is out.
    """
    from apps.inventory.services import available_for_country

    items = list(combo.items.all())
    if not items:
        return 0
    return min(available_for_country(item.variant, country) // item.quantity for item in items)


def visible_combos(country):
    """Queryset of combos that could be shown in `country`, prefetched for pricing.

    Deliberately NOT the final list: `available_in` still has to run per combo (it asks
    the pricing engine, which is not expressible as a filter). This narrows the rows and
    loads the joins so that check costs no queries.

    Callers that go on to SERIALIZE the result should put it through `attach_pricing`
    first — otherwise the price is resolved once for the availability check and again for
    the payload.
    """
    from django.db.models import Q

    from apps.combos.models import Combo

    return (
        Combo.objects.filter(status="active")
        .filter(Q(available_countries__isnull=True) | Q(available_countries=country))
        .distinct()
        .prefetch_related(
            "items__variant__prices",
            "items__variant__product__available_countries",
            "items__variant__product__variants__prices",
            "items__variant__images",
            "items__variant__product__images",
            "prices",
            "available_countries",
        )
    )


def pricing_for_cart(combo, country) -> ComboPricing | None:
    """The price a bundle ALREADY IN A BASKET still earns, or None.

    Narrower than `resolve_combo_price` and wider than `available_in`, and both
    differences are deliberate:

    * It refuses an ARCHIVED or DRAFT combo, and one withdrawn from this market. Without
      that, archiving a combo would stop new sales while every basket already holding one
      kept the deal — so a bundle archived BECAUSE ITS PRICE WAS WRONG would keep charging
      the wrong price, which is exactly the case archiving exists for.
    * It refuses a bundle whose COMPONENTS have stopped being sellable, for the same
      reason and by the same rule (`unsellable_components`). Pulling a product from sale
      has to end the deal that contains it; the goods left in the basket are then handled
      by `place_order`, which refuses any line whose product is no longer sellable and
      names the SKU.
    * It does NOT ask about stock. The lines were capped when they were added, and
      checkout's `reserve` is the authority; a bundle is not repriced for being scarce.

    The cart serializer and `cart_combo_discount` both come through here, so what the
    shopper is shown and what they are charged cannot part company.
    """
    if combo.status != "active" or not market_allowed(combo, country):
        return None
    if unsellable_components(combo, country):
        return None
    return resolve_combo_price(combo, country)


def cart_combo_discount(cart, country) -> Decimal:
    """What every bundle in this cart saves, together. 0.00 for a cart with none.

    THE SINGLE SOURCE FOR THE ORDER'S COMBO SAVING. The cart drawer, the checkout quote
    and `place_order` all call this, so the number the shopper watched cannot differ from
    the one they are charged — and when it does differ (a component was repriced between
    the quote and the pay button) the `expected_total` guard turns that into an honest
    "totals changed" rather than a quiet overcharge.

    A group whose combo has lapsed — unpriceable here, archived, or withdrawn from this
    market — contributes nothing. Its component lines still sit in the cart at full price,
    which is the correct fallback: the goods are real, only the bundle deal has ended.
    """
    total = ZERO
    for group in cart.combo_groups.select_related("combo").prefetch_related(
        "combo__available_countries", "combo__items__variant__prices", "combo__prices"
    ):
        pricing = pricing_for_cart(group.combo, country)
        if pricing is not None:
            total += pricing.saving * group.quantity
    return q2(total)
