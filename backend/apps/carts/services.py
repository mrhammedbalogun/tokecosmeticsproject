"""Cart identity + mutation helpers. The ONLY place that decides which Cart a
request owns, so views stay thin and identity rules live in one file."""
from __future__ import annotations

from apps.carts.models import Cart


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
