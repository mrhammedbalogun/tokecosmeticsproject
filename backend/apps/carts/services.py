"""Cart identity + mutation helpers. The ONLY place that decides which Cart a
request owns, so views stay thin and identity rules live in one file."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.carts.models import Cart, CartItem
from apps.inventory.services import available_for_country
from apps.pricing.services import resolve_price


def get_or_create_cart(request, kind: str = "standard") -> Cart:
    """Resolve the caller's active cart of `kind`, creating one if needed.

    Authed  -> the user's single active cart of that kind (get_or_create).
    Guest   -> the cart named by the X-Cart-Id header if it exists and is active
               and unclaimed; otherwise a fresh guest cart.
    """
    country = request.country
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        cart, _ = Cart.objects.get_or_create(
            user=user, kind=kind, status="active",
            defaults={"country": country, "currency": country.currency},
        )
        return cart

    cart_id = request.headers.get("X-Cart-Id")
    if cart_id:
        cart = Cart.objects.filter(
            id=cart_id, user__isnull=True, kind=kind, status="active"
        ).first()
        if cart:
            return cart
    return Cart.objects.create(
        user=None, kind=kind, country=country, currency=country.currency
    )


def _snapshot_price(variant, country) -> Decimal:
    resolved = resolve_price(variant, country)
    return resolved.amount if resolved else Decimal("0.00")


def _cap(variant, country, wanted: int) -> int:
    """Clamp a requested quantity to what's actually available in the country."""
    available = available_for_country(variant, country)
    return max(0, min(wanted, available))


@transaction.atomic
def add_item(cart, variant, qty: int, country) -> CartItem | None:
    """Add `qty` of a variant, merging into an existing line. Result quantity is
    capped at available stock. Returns the line, or None if it was capped to 0."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    line = CartItem.objects.select_for_update().filter(cart=cart, variant=variant).first()
    current = line.quantity if line else 0
    new_qty = _cap(variant, country, current + qty)
    return _write_line(cart, variant, new_qty, country, line)


@transaction.atomic
def set_quantity(cart, variant, qty: int, country) -> CartItem | None:
    """Set an absolute quantity (capped at stock). qty<=0 removes the line."""
    line = CartItem.objects.select_for_update().filter(cart=cart, variant=variant).first()
    new_qty = _cap(variant, country, qty) if qty > 0 else 0
    return _write_line(cart, variant, new_qty, country, line)


def _write_line(cart, variant, new_qty, country, line):
    if new_qty <= 0:
        if line:
            line.delete()
        return None
    if line:
        line.quantity = new_qty
        line.unit_price_snapshot = _snapshot_price(variant, country)
        line.save(update_fields=["quantity", "unit_price_snapshot", "added_at", "updated_at"])
        return line
    return CartItem.objects.create(
        cart=cart, variant=variant, quantity=new_qty,
        unit_price_snapshot=_snapshot_price(variant, country),
    )


def remove_item(cart, variant, country=None) -> None:
    CartItem.objects.filter(cart=cart, variant=variant).delete()
