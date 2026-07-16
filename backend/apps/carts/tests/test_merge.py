import pytest
from decimal import Decimal

from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.carts.services import merge_guest_cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _ng_stock(variant, qty):
    # NG + NGN seeded by core migration 0003; fetch rather than create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("100.00"))
    return ng


def test_merge_sums_quantities_and_caps_at_stock(django_user_model):
    variant = ProductVariantFactory()
    ng = _ng_stock(variant, qty=6)
    user = django_user_model.objects.create_user(email="m@x.com", password="pw")

    guest = CartFactory(user=None, country=ng, currency=ng.currency)
    CartItem.objects.create(cart=guest, variant=variant, quantity=4, unit_price_snapshot="100.00")
    user_cart = CartFactory(user=user, country=ng, currency=ng.currency)
    CartItem.objects.create(cart=user_cart, variant=variant, quantity=5, unit_price_snapshot="100.00")

    merged = merge_guest_cart(user, guest.id, ng)

    assert merged.id == user_cart.id
    # 4 + 5 = 9 requested, capped at 6 available.
    assert CartItem.objects.get(cart=user_cart, variant=variant).quantity == 6
    # Guest cart consumed.
    assert Cart.objects.get(id=guest.id).status == "converted"


def test_merge_ignores_foreign_or_claimed_guest_cart(django_user_model):
    variant = ProductVariantFactory()
    ng = _ng_stock(variant, qty=6)
    user = django_user_model.objects.create_user(email="m2@x.com", password="pw")
    other = django_user_model.objects.create_user(email="o@x.com", password="pw")
    claimed = CartFactory(user=other, country=ng, currency=ng.currency)  # not a guest cart

    merged = merge_guest_cart(user, claimed.id, ng)  # must not steal it

    assert merged.user_id == user.id and merged.id != claimed.id
