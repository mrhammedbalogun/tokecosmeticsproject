"""The edge cases, each pinned to the failure it used to produce.

Every test here was written against a REPRODUCED defect, not a hypothetical. The
docstrings say what happened before the fix, because that is the thing a future reader
needs in order to know whether the guard is still earning its place.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.carts.factories import CartFactory
from apps.carts.models import CartComboGroup
from apps.carts.serializers import serialize_cart
from apps.carts.services import add_combo
from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.combos.services import (
    available_in,
    cart_combo_discount,
    unsellable_components,
)

pytestmark = pytest.mark.django_db


def _admin():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="edge@toke.test"))
    return c


# ── sellability: the checks `sellable_in` cannot make ───────────────────────────────

def test_a_switched_off_variant_cannot_be_sold_inside_a_combo(ng, combo):
    """A combo was the one way to buy a deactivated variant.

    `CartItemsView` has always looked the variant up with `is_active=True`, so the
    standalone path refused it. `available_in` only asked `sellable_in`, which is a
    PRODUCT-level question — "is ANY active variant priced here?" — and a product with a
    second, active variant answered yes. Measured before the fix: `available_in` True,
    `max_addable` 39.
    """
    c = combo()
    item = c.items.first()
    ProductVariantFactory(product=item.variant.product, is_default=False)  # a live sibling
    item.variant.is_active = False
    item.variant.save(update_fields=["is_active"])

    assert unsellable_components(c, ng) == [item]
    assert available_in(c, ng) is False


def test_a_draft_component_keeps_the_combo_off_the_shelf(ng, combo):
    """Bundles get built ahead of a launch — the builder's product search includes drafts
    on purpose. This is what stops the finished bundle going live before the product it
    contains does. `sellable_in` never looks at `status`."""
    c = combo()
    product = c.items.first().variant.product
    product.status = "draft"
    product.save(update_fields=["status"])

    assert available_in(c, ng) is False


def test_pulling_a_component_ends_the_deal_in_baskets_already_holding_it(ng, combo):
    """Same rule as archiving the combo itself: withdrawing a product has to end the
    bundle price that contains it. The goods stay and are still charged."""
    c = combo()
    cart = CartFactory(country=ng, currency=ng.currency)
    add_combo(cart, c, 1, ng)
    assert cart_combo_discount(cart, ng) == Decimal("200.00")

    product = c.items.first().variant.product
    product.status = "archived"
    product.save(update_fields=["status"])

    assert cart_combo_discount(cart, ng) == Decimal("0.00")
    payload = serialize_cart(cart, ng)
    assert payload["combos"][0]["ended"] is True
    assert payload["subtotal"] == "2000.00"  # the goods are still charged for


# ── admin validation: every 500 the database used to raise ──────────────────────────

def test_a_zero_quantity_row_is_refused_by_name(ng, priced_variant):
    """`combo_item_quantity_positive` answered this with an IntegrityError 500."""
    v = priced_variant("1000.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "Z", "slug": "z", "items": [{"variant": v.id, "quantity": 0}],
    }, format="json")
    assert r.status_code == 400
    assert v.sku in str(r.data)


def test_an_absurd_quantity_is_refused_before_it_overflows_the_money_columns(ng, priced_variant):
    """999,999,999 of a ₦18,500 product prices a bundle at ₦18.5 TRILLION. The money
    columns are `max_digits=12`, so that is accepted here, shown in the shop, and then
    raises DataError from Postgres when `place_order` writes `Order.subtotal` — inside
    the locked transaction, which is a 500 at the till."""
    v = priced_variant("1000.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "Big", "slug": "big", "items": [{"variant": v.id, "quantity": 999_999_999}],
    }, format="json")
    assert r.status_code == 400


def test_two_prices_for_one_market_are_refused(ng, priced_variant):
    """`uniq_combo_price_market` answered this with an IntegrityError 500."""
    v = priced_variant("1000.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "D", "slug": "d", "items": [{"variant": v.id, "quantity": 1}],
        "prices": [{"country": "NG", "amount": "10"}, {"country": "NG", "amount": "20"}],
    }, format="json")
    assert r.status_code == 400
    assert "NG" in str(r.data)


def test_a_negative_pinned_price_is_refused_rather_than_clamped(ng, priced_variant):
    """`resolve_combo_price` clamps a negative pin to zero — it must never hand the shop
    a negative price. That clamp means a typed "-500" SHIPS AS A FREE COMBO, silently.
    The serializer is the only place there is still somebody to tell."""
    v = priced_variant("1000.00")
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "N", "slug": "n", "items": [{"variant": v.id, "quantity": 1}],
        "prices": [{"country": "NG", "amount": "-500"}],
    }, format="json")
    assert r.status_code == 400


def test_a_switched_off_variant_is_refused_at_build_time(ng, priced_variant):
    """It could never be sold, so putting it in a bundle is always a mistake — and one
    worth catching while somebody is looking at the screen rather than as a combo that
    silently never appears."""
    v = priced_variant("1000.00")
    v.is_active = False
    v.save(update_fields=["is_active"])
    r = _admin().post("/api/v1/admin/combos/", {
        "name": "Off", "slug": "off", "items": [{"variant": v.id, "quantity": 1}],
    }, format="json")
    assert r.status_code == 400
    assert v.sku in str(r.data)


# ── deleting catalogue rows a combo holds ───────────────────────────────────────────

def test_deleting_a_variant_inside_a_combo_refuses_by_name(ng, combo):
    """`ComboItem.variant` is PROTECT on purpose. Unhandled, it reached the Owner as a
    500 and a psycopg traceback; what they need is which combo to edit."""
    c = combo(name="Glow Kit")
    variant = c.items.first().variant
    ProductVariantFactory(product=variant.product, is_default=False)  # not the last one

    r = _admin().delete(f"/api/v1/admin/variants/{variant.id}/")
    assert r.status_code == 400
    assert "Glow Kit" in str(r.data)


def test_deleting_a_product_whose_variant_is_in_a_combo_refuses_by_name(ng, combo):
    """A product delete cascades into its variants and hits the same PROTECT."""
    c = combo(name="Glow Kit")
    product = c.items.first().variant.product

    r = _admin().delete(f"/api/v1/admin/products/{product.slug}/")
    assert r.status_code == 400
    assert "Glow Kit" in str(r.data)


# ── untrusted input on an anonymous endpoint ────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"combo_slug": "c", "quantity": "abc"},   # ValueError before the fix
    {"combo_slug": "c", "quantity": None},    # TypeError before the fix
    {"combo_slug": "c", "quantity": 2.7},     # silently truncated to 2 before the fix
    {"combo_slug": "c", "quantity": True},    # a bool IS an int in Python
])
def test_a_nonsense_quantity_is_a_400_not_a_500(ng, combo, body):
    """/cart/combos/ is ANONYMOUS — anything on the internet can post to it — so the
    parse has to be total."""
    c = combo()
    r = APIClient().post(
        "/api/v1/cart/combos/", {**body, "combo_slug": c.slug},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 400, r.data


@pytest.mark.parametrize("path", ["/api/v1/cart/combos/", "/api/v1/cart/items/"])
def test_a_body_that_is_not_an_object_is_a_400_not_a_500(ng, path):
    """`request.data` is whatever JSON arrived, and every handler reads a key off it —
    so `[1, 2]` reached `.get` on a LIST and raised AttributeError. Guarded once in
    `_CartBase.initial`, so the next handler added to this file cannot reintroduce it."""
    r = APIClient().post(path, [1, 2], format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 400, r.data


def test_the_same_nonsense_is_a_400_on_the_item_routes_too(ng, priced_variant):
    """The identical one-line defect, on the routes that predate combos."""
    v = priced_variant("1000.00")
    client = APIClient()
    assert client.post("/api/v1/cart/items/", {"variant_id": v.id, "quantity": "abc"},
                       format="json", HTTP_X_COUNTRY="NG").status_code == 400
    assert client.patch(f"/api/v1/cart/items/{v.id}/", {"quantity": None},
                        format="json", HTTP_X_COUNTRY="NG").status_code == 400


# ── the cart-group race ─────────────────────────────────────────────────────────────

def test_one_cart_cannot_hold_the_same_combo_twice(ng, combo):
    """`add_combo` locks before deciding whether to create — but a SELECT ... FOR UPDATE
    matching NO ROW locks nothing, so two concurrent adds (a double-tapped button is
    enough) both saw "no group" and both created one. The shopper then had two identical
    cards, and the second was invisible to the merge for ever after."""
    from django.db import IntegrityError

    c = combo()
    cart = CartFactory(country=ng, currency=ng.currency)
    CartComboGroup.objects.create(cart=cart, combo=c, quantity=1)
    with pytest.raises(IntegrityError):
        CartComboGroup.objects.create(cart=cart, combo=c, quantity=1)
