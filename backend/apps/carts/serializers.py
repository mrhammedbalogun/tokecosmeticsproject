"""Cart → JSON with live per-country pricing. Not a DRF ModelSerializer: the
output is derived (prices re-resolved), so a plain builder is clearer and cheaper
than write-serializer machinery. Views handle writes directly."""
from __future__ import annotations

from decimal import Decimal

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


def serialize_cart(cart, country) -> dict:
    items = [_line(i, country) for i in cart.items.select_related("variant__product").all()]
    subtotal = sum(
        (Decimal(i["line_total"]) for i in items if not i["unavailable"]),
        Decimal("0.00"),
    )
    return {
        "id": str(cart.id),
        "kind": cart.kind,
        "status": cart.status,
        "country": country.code,
        "currency": country.currency.code,
        "items": items,
        "subtotal": str(subtotal.quantize(TWO_DP)),
        "has_unavailable": any(i["unavailable"] for i in items),
    }
