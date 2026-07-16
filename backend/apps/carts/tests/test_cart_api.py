import pytest
from decimal import Decimal

from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.carts.services import add_item, set_quantity
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _ng_with_stock(variant, qty):
    # NG + NGN are seeded (core migration 0003); fetch rather than create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    return ng


def test_add_item_snapshots_price_and_creates_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)

    add_item(cart, variant, 2, ng)

    line = CartItem.objects.get(cart=cart, variant=variant)
    assert line.quantity == 2
    assert line.unit_price_snapshot == Decimal("1000.00")


def test_add_item_merges_into_existing_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 2, ng)
    add_item(cart, variant, 3, ng)
    assert CartItem.objects.get(cart=cart, variant=variant).quantity == 5


def test_add_item_capped_at_available_stock():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=3)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 10, ng)  # only 3 exist
    assert CartItem.objects.get(cart=cart, variant=variant).quantity == 3


def test_set_quantity_zero_removes_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 2, ng)
    set_quantity(cart, variant, 0, ng)
    assert not CartItem.objects.filter(cart=cart, variant=variant).exists()
