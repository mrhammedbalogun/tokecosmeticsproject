import pytest
from decimal import Decimal

from rest_framework.test import APIClient

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


def test_guest_cart_roundtrip_via_header():
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=10)  # seeds stock + NGN price for NG
    client = APIClient()

    # First GET with no header creates a cart and returns its id.
    r = client.get("/api/v1/cart/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    cart_id = r.data["id"]

    # Add an item using that cart id.
    r = client.post(
        "/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 2},
        format="json", HTTP_X_COUNTRY="NG", HTTP_X_CART_ID=cart_id,
    )
    assert r.status_code == 200
    assert r.data["items"][0]["quantity"] == 2
    assert r.data["subtotal"] == "2000.00"


def test_patch_and_delete_line(django_user_model):
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=10)  # seeds stock + NGN price for NG
    user = django_user_model.objects.create_user(email="c@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)

    client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 4},
                format="json", HTTP_X_COUNTRY="NG")
    r = client.patch(f"/api/v1/cart/items/{variant.id}/", {"quantity": 1},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r.data["items"][0]["quantity"] == 1
    r = client.delete(f"/api/v1/cart/items/{variant.id}/", HTTP_X_COUNTRY="NG")
    assert r.data["items"] == []
