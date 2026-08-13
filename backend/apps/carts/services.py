"""Cart identity + mutation helpers. The ONLY place that decides which Cart a
request owns, so views stay thin and identity rules live in one file."""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.carts.models import Cart, CartItem
from apps.inventory.services import available_for_country
from apps.pricing.services import resolve_price


def _safe_uuid(value) -> uuid.UUID | None:
    """Parse an untrusted cart id (X-Cart-Id header or request body) into a UUID,
    returning None for anything malformed. Without this, a corrupted cookie value
    reaches a UUIDField lookup and raises ValidationError → HTTP 500 on every
    cart request. A bad id is simply treated as 'no cart'."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _revive(cart: Cart) -> Cart:
    """Flip an abandoned cart back to active. The abandoned status is a marketing
    marker (idle >3h, see tasks.abandon_stale_carts), NOT a deletion — a shopper
    who returns days later must find their items where they left them. `converted`
    stays terminal: those items were bought."""
    cart.status = "active"
    cart.save(update_fields=["status", "updated_at"])
    return cart


def _user_cart(user, kind: str, country) -> Cart:
    """The user's single active cart of `kind` — reviving their most recent
    abandoned one before creating an empty replacement."""
    cart = Cart.objects.filter(user=user, kind=kind, status="active").first()
    if cart:
        return cart
    stale = (
        Cart.objects.filter(user=user, kind=kind, status="abandoned")
        .order_by("-updated_at")
        .first()
    )
    try:
        with transaction.atomic():
            if stale:
                return _revive(stale)
            return Cart.objects.create(
                user=user, kind=kind, country=country, currency=country.currency
            )
    except IntegrityError:
        # A concurrent request beat us to the one-active-cart-per-user slot;
        # its cart is the winner.
        return Cart.objects.get(user=user, kind=kind, status="active")


def get_or_create_cart(request, kind: str = "standard") -> Cart:
    """Resolve the caller's active cart of `kind`, creating one if needed.

    Authed  -> the user's single active cart of that kind; if the abandon task
               flagged it while they were away, the most recent abandoned one is
               revived instead of minting an empty replacement.
    Guest   -> the cart named by the X-Cart-Id header if it exists and is
               unclaimed (revived if flagged abandoned); otherwise a fresh cart.
    """
    country = request.country
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return _user_cart(user, kind, country)

    cart_id = _safe_uuid(request.headers.get("X-Cart-Id"))
    if cart_id:
        cart = Cart.objects.filter(
            id=cart_id, user__isnull=True, kind=kind,
            status__in=["active", "abandoned"],
        ).first()
        if cart:
            return cart if cart.status == "active" else _revive(cart)
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
    line, _ = add_item_reporting(cart, variant, qty, country)
    return line


@transaction.atomic
def add_item_reporting(cart, variant, qty: int, country) -> tuple[CartItem | None, bool]:
    """add_item, plus whether the line actually grew. False means the stock cap ate
    the whole request ("just sold out") — capped to 0, or an existing line already at
    the cap. Views turn that into an explicit 409 instead of a silent 200 no-op."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    line = CartItem.objects.select_for_update().filter(cart=cart, variant=variant).first()
    current = line.quantity if line else 0
    new_qty = _cap(variant, country, current + qty)
    return _write_line(cart, variant, new_qty, country, line), new_qty > current


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


def merge_guest_cart(user, guest_cart_id, country) -> Cart:
    """Fold an unclaimed guest cart's lines into the user's active standard cart
    (summing quantities, capped at available stock), then mark the guest cart
    converted. Foreign/claimed/missing guest ids are ignored — returns the user's
    cart unchanged. Idempotent: a converted guest cart won't be merged twice.
    Abandoned guest carts merge too — "idle >3h" must not cost a shopper who
    logs in the next morning their basket."""
    user_cart = _user_cart(user, "standard", country)
    guest_id = _safe_uuid(guest_cart_id)
    guest = (
        Cart.objects.filter(
            id=guest_id, user__isnull=True, kind="standard",
            status__in=["active", "abandoned"],
        ).first()
        if guest_id
        else None
    )
    if not guest or guest.id == user_cart.id:
        return user_cart
    with transaction.atomic():
        for gi in guest.items.select_related("variant").all():
            existing = CartItem.objects.filter(cart=user_cart, variant=gi.variant).first()
            base = existing.quantity if existing else 0
            set_quantity(user_cart, gi.variant, base + gi.quantity, country)
        guest.status = "converted"
        guest.save(update_fields=["status", "updated_at"])
    return user_cart
