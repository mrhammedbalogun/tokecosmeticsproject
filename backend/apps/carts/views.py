from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from apps.accounts.throttling import ScopedRateThrottle  # XFF-safe; NOT rest_framework.throttling
from rest_framework.views import APIView

from apps.carts.models import CartComboGroup
from apps.carts.serializers import serialize_cart
from apps.carts.services import (
    add_combo,
    add_item_reporting,
    get_or_create_cart,
    merge_guest_cart,
    remove_combo,
    remove_item,
    set_combo_quantity,
    set_quantity,
)
from apps.catalog.models import ProductVariant
from apps.combos.models import Combo

OUT_OF_STOCK = {"detail": "This item just sold out.", "code": "out_of_stock"}
BAD_QUANTITY = {"quantity": ["Must be a whole number."]}


def _quantity(data, default: int) -> int | None:
    """A quantity from an untrusted body, or None if it is not a whole number.

    `int(request.data.get("quantity", 1))` was the whole of this, and it raises on every
    shape a browser or a bad client can send: `"abc"` is a ValueError, `null` a
    TypeError, and both arrive as a 500 rather than a 400. The cart is an ANONYMOUS
    endpoint — anything on the internet can post to it — so the parse has to be total.

    A float is refused rather than truncated: somebody sending 2.7 has a bug, and quietly
    charging them for 2 is a worse answer than saying so.
    """
    raw = data.get("quantity", default)
    if isinstance(raw, bool):  # bools are ints in Python; a boolean quantity is a bug
        return None
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None
COMBO_OUT_OF_STOCK = {
    "detail": "This combo is out of stock right now.",
    "code": "combo_out_of_stock",
}
COMBO_UNAVAILABLE = {
    "detail": "This combo isn't available in your country.",
    "code": "combo_unavailable",
}


class _CartBase(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "cart"

    def initial(self, request, *args, **kwargs):
        """Refuse a body that is not an object, before any handler reads a key off it.

        Every write handler here does `request.data.get(...)`, and `request.data` is
        whatever JSON arrived — so a body of `[1, 2]` reaches `.get` on a LIST and raises
        AttributeError, i.e. a 500. These are ANONYMOUS endpoints; the shape check has to
        happen before the handler, not inside each one, or the next handler added here
        reintroduces it.

        A bodyless GET/DELETE parses to `{}` and passes; only a genuine list or scalar is
        refused.
        """
        super().initial(request, *args, **kwargs)
        if request.method in ("POST", "PATCH", "PUT") and not hasattr(request.data, "get"):
            raise ValidationError({"detail": "Expected a JSON object."})

    def _respond(self, cart, request):
        return Response(serialize_cart(cart, request.country))


class CartView(_CartBase):
    def get(self, request):
        cart = get_or_create_cart(request)
        return self._respond(cart, request)


class CartItemsView(_CartBase):
    def post(self, request):
        variant = get_object_or_404(
            ProductVariant, pk=request.data.get("variant_id"), is_active=True
        )
        qty = _quantity(request.data, 1)
        if qty is None:
            return Response(BAD_QUANTITY, status=status.HTTP_400_BAD_REQUEST)
        if qty <= 0:
            return Response({"quantity": ["Must be positive."]}, status=status.HTTP_400_BAD_REQUEST)
        cart = get_or_create_cart(request)
        _, added = add_item_reporting(cart, variant, qty, request.country)
        if not added:
            return Response(OUT_OF_STOCK, status=status.HTTP_409_CONFLICT)
        return self._respond(cart, request)


class CartItemDetailView(_CartBase):
    def patch(self, request, variant_id):
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        qty = _quantity(request.data, 0)
        if qty is None:
            return Response(BAD_QUANTITY, status=status.HTTP_400_BAD_REQUEST)
        cart = get_or_create_cart(request)
        set_quantity(cart, variant, qty, request.country)
        return self._respond(cart, request)

    def delete(self, request, variant_id):
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        cart = get_or_create_cart(request)
        remove_item(cart, variant, request.country)
        return self._respond(cart, request)


class CartMergeView(_CartBase):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        cart = merge_guest_cart(request.user, request.data.get("cart_id"), request.country)
        return self._respond(cart, request)


class CartCombosView(_CartBase):
    """POST a combo into the bag.

    AVAILABILITY IS RE-CHECKED HERE, not trusted from the page the shopper clicked on.
    That page may have been rendered from a cached response minutes ago, in a different
    market, before a component was archived. `available_in` asks the live question —
    active, sold in this country, every component still sellable, and the whole thing
    still prices — and a no is a 409 the storefront can explain rather than a bundle
    that fails at checkout.
    """

    def post(self, request):
        from apps.combos.services import available_in

        combo = get_object_or_404(Combo, slug=request.data.get("combo_slug"))
        qty = _quantity(request.data, 1)
        if qty is None:
            return Response(BAD_QUANTITY, status=status.HTTP_400_BAD_REQUEST)
        if qty <= 0:
            return Response({"quantity": ["Must be positive."]}, status=status.HTTP_400_BAD_REQUEST)
        if not available_in(combo, request.country):
            return Response(COMBO_UNAVAILABLE, status=status.HTTP_409_CONFLICT)
        cart = get_or_create_cart(request)
        _, added = add_combo(cart, combo, qty, request.country)
        if not added:
            return Response(COMBO_OUT_OF_STOCK, status=status.HTTP_409_CONFLICT)
        return self._respond(cart, request)


class CartComboDetailView(_CartBase):
    """Resize or drop one bundle. The group is looked up WITHIN the caller's own cart,
    so a guessed id belonging to somebody else's basket is a 404, not an edit."""

    def _group(self, request, group_id):
        cart = get_or_create_cart(request)
        group = get_object_or_404(CartComboGroup, pk=group_id, cart=cart)
        return cart, group

    def patch(self, request, group_id):
        qty = _quantity(request.data, 0)
        if qty is None:
            return Response(BAD_QUANTITY, status=status.HTTP_400_BAD_REQUEST)
        cart, group = self._group(request, group_id)
        set_combo_quantity(cart, group, qty, request.country)
        return self._respond(cart, request)

    def delete(self, request, group_id):
        cart, group = self._group(request, group_id)
        remove_combo(cart, group)
        return self._respond(cart, request)
