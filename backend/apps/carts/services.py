"""Cart identity + mutation helpers. The ONLY place that decides which Cart a
request owns, so views stay thin and identity rules live in one file."""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.carts.models import Cart, CartComboGroup, CartItem
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
    line = _standalone_line(cart, variant, lock=True)
    current = line.quantity if line else 0
    new_qty = _cap(variant, country, current + qty)
    return _write_line(cart, variant, new_qty, country, line), new_qty > current


@transaction.atomic
def set_quantity(cart, variant, qty: int, country) -> CartItem | None:
    """Set an absolute quantity (capped at stock). qty<=0 removes the line."""
    line = _standalone_line(cart, variant, lock=True)
    new_qty = _cap(variant, country, qty) if qty > 0 else 0
    return _write_line(cart, variant, new_qty, country, line)


def _standalone_line(cart, variant, *, lock: bool = False):
    """The cart's ORDINARY line for this variant, never a combo's copy of it.

    Every mutation the variant-keyed API can reach goes through here. Without the
    `combo_group__isnull=True` filter, `PATCH /cart/items/{variant_id}/` on a product
    that also sits inside a bundle would pick up whichever row the database returned
    first and quietly resize the bundle — the shopper would see a combo they never
    edited come apart, priced as one.
    """
    qs = CartItem.objects.filter(cart=cart, variant=variant, combo_group__isnull=True)
    if lock:
        qs = qs.select_for_update()
    return qs.first()


def _combo_cap(combo, country, wanted: int) -> int:
    """Clamp a combo quantity to how many whole bundles the shelves can fill."""
    from apps.combos.services import max_addable

    return max(0, min(wanted, max_addable(combo, country)))


@transaction.atomic
def add_combo(cart, combo, qty: int, country) -> tuple[CartComboGroup | None, bool]:
    """Add `qty` of a combo, merging into an existing group for the same combo.

    Returns (group, grew). `grew=False` means the stock cap ate the whole request — the
    scarcest component cannot fill another box — which the view turns into an explicit
    409 rather than a silent 200 that appears to have worked.

    ONE GROUP PER COMBO PER CART, deliberately. Two groups of the same bundle would show
    the shopper two identical cards they then have to reconcile; adding again simply
    raises the number on the one they already have, exactly as adding a product again
    raises its quantity.
    """
    if qty <= 0:
        raise ValueError("qty must be positive")
    group = (
        CartComboGroup.objects.select_for_update().filter(cart=cart, combo=combo).first()
    )
    current = group.quantity if group else 0
    new_qty = _combo_cap(combo, country, current + qty)
    if new_qty <= current:
        return group, False
    if group is None:
        try:
            # ITS OWN SAVEPOINT, and that is load-bearing rather than tidy. This function
            # is `@transaction.atomic`, so an IntegrityError raised straight into it
            # marks the whole transaction unusable — the recovery `.get()` below would
            # then fail with "current transaction is aborted", turning a handled race
            # into a 500. The inner atomic() rolls back to the savepoint instead, leaving
            # the outer transaction healthy enough to finish the job.
            with transaction.atomic():
                group = CartComboGroup.objects.create(
                    cart=cart, combo=combo, quantity=new_qty
                )
        except IntegrityError:
            # Lost the race for the `uniq_cart_combo_group` slot — a concurrent request
            # created the group between our lock (which matched no row, so locked
            # nothing) and this insert. Its group is the winner; fold into it rather than
            # failing, exactly as `_user_cart` does for the one-active-cart slot.
            #
            # Deliberately NOT re-deriving the quantity from `current`: that was read
            # before the race and is stale. The winner's own quantity is the truth.
            group = CartComboGroup.objects.select_for_update().get(cart=cart, combo=combo)
            new_qty = _combo_cap(combo, country, group.quantity + qty)
            if new_qty <= group.quantity:
                return group, False
    return _write_combo_group(group, new_qty, country), True


@transaction.atomic
def set_combo_quantity(cart, group, qty: int, country) -> CartComboGroup | None:
    """Set an absolute combo quantity (capped at what the components can fill).
    qty<=0 removes the whole group and every line under it."""
    locked = CartComboGroup.objects.select_for_update().filter(pk=group.pk, cart=cart).first()
    if locked is None:
        return None
    new_qty = _combo_cap(locked.combo, country, qty) if qty > 0 else 0
    return _write_combo_group(locked, new_qty, country)


def _write_combo_group(group, new_qty: int, country) -> CartComboGroup | None:
    """Rewrite a group's component lines to `new_qty` bundles, or delete it at 0.

    The lines are DERIVED here and nowhere else: `line.quantity = combo_qty x
    item.quantity`. That is what keeps a group from drifting into a half-combo, and it is
    why the component rows have no independent edit path.
    """
    if new_qty <= 0:
        group.delete()  # CASCADE takes the component lines with it
        return None
    group.quantity = new_qty
    group.save(update_fields=["quantity", "updated_at"])
    wanted = {item.variant_id: (item.variant, item.quantity) for item in group.combo.items.all()}
    existing = {line.variant_id: line for line in group.items.all()}
    for variant_id, (variant, per_box) in wanted.items():
        line = existing.pop(variant_id, None)
        qty = new_qty * per_box
        price = _snapshot_price(variant, country)
        if line is None:
            CartItem.objects.create(
                cart=group.cart, variant=variant, combo_group=group,
                quantity=qty, unit_price_snapshot=price,
            )
        else:
            line.quantity = qty
            line.unit_price_snapshot = price
            line.save(update_fields=["quantity", "unit_price_snapshot", "added_at", "updated_at"])
    # Anything left in `existing` is a component the combo no longer contains — the
    # curator edited the bundle while it sat in somebody's basket. Drop it: the group is
    # priced as the combo is defined TODAY, so it must contain what the combo says today.
    for orphan in existing.values():
        orphan.delete()
    return group


def remove_combo(cart, group) -> None:
    CartComboGroup.objects.filter(pk=group.pk, cart=cart).delete()


def combo_groups(cart):
    """A cart's combo groups, prefetched for pricing and rendering in one go."""
    return (
        cart.combo_groups.select_related("combo")
        .prefetch_related(
            "combo__available_countries",
            # The GROUP's own lines are what gets rendered (they carry the quantities);
            # the combo's item list is what gets rewritten from. Both are needed, and
            # both are prefetched, because `variant_image_path` walks two image sets per
            # line and that is a query apiece without this.
            "items__variant__product",
            "items__variant__prices",
            "items__variant__images",
            "items__variant__product__images",
            "combo__items__variant__prices",
            "combo__prices",
        )
        .all()
    )


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
    CartItem.objects.filter(cart=cart, variant=variant, combo_group__isnull=True).delete()


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
        # Standalone lines only. A combo's component rows are rebuilt from its GROUP
        # below; folding them in here as well would add the bundle's contents twice —
        # once at full price as singles, once inside the combo.
        for gi in guest.items.select_related("variant").filter(combo_group__isnull=True):
            existing = _standalone_line(user_cart, gi.variant)
            base = existing.quantity if existing else 0
            set_quantity(user_cart, gi.variant, base + gi.quantity, country)
        for group in guest.combo_groups.select_related("combo").all():
            add_combo(user_cart, group.combo, group.quantity, country)
        guest.status = "converted"
        guest.save(update_fields=["status", "updated_at"])
    return user_cart
