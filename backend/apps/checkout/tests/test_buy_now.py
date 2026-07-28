"""Buy Now = add to the shopper's ordinary cart and go to checkout.

The original design (Plan-08 D14) kept a separate `kind="express"` cart, but no
storefront surface ever consumed it — checkout always reads the standard cart, so
Buy Now produced an empty checkout (found live, 2026-07-28). Ruled with Hammed:
Buy Now is now add+navigate on the ONE standard cart, and must never clear it —
clearing here would silently destroy the shopper's bag.
"""
import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.carts.models import Cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _variant(wh, ngn, price="1000.00", stock=5):
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal(price))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return variant


@pytest.fixture()
def shop(django_user_model):
    # Seed migration already created NG + NGN — fetch, don't re-create (avoids PK collision).
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    user = django_user_model.objects.create_user(email="b@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)
    return client, user, wh, ng.currency


def _buy_now(client, variant, qty):
    return client.post(
        "/api/v1/checkout/buy-now/", {"variant_id": variant.id, "quantity": qty},
        format="json", HTTP_X_COUNTRY="NG",
    )


def test_buy_now_adds_to_the_standard_cart_and_creates_no_express_cart(shop):
    client, user, wh, ngn = shop
    variant = _variant(wh, ngn)

    r = _buy_now(client, variant, 1)

    assert r.status_code == 200
    assert r.data["kind"] == "standard"
    assert r.data["items"][0]["quantity"] == 1
    assert Cart.objects.filter(user=user, kind="express").count() == 0
    # The returned cart IS the one the checkout page reads.
    standard = Cart.objects.get(user=user, kind="standard", status="active")
    assert str(standard.id) == str(r.data["id"])


def test_buy_now_keeps_what_is_already_in_the_bag(shop):
    client, user, wh, ngn = shop
    already_in_bag = _variant(wh, ngn)
    bought_now = _variant(wh, ngn)
    client.post("/api/v1/cart/items/", {"variant_id": already_in_bag.id, "quantity": 2},
                format="json", HTTP_X_COUNTRY="NG")

    r = _buy_now(client, bought_now, 1)

    quantities = {i["variant_id"]: i["quantity"] for i in r.data["items"]}
    assert quantities == {already_in_bag.id: 2, bought_now.id: 1}


def test_buying_the_same_variant_again_merges_the_line(shop):
    client, user, wh, ngn = shop
    variant = _variant(wh, ngn, stock=5)

    _buy_now(client, variant, 1)
    r = _buy_now(client, variant, 3)

    assert [i["quantity"] for i in r.data["items"]] == [4]
    # Capped at available stock on a further buy, like any other add.
    r = _buy_now(client, variant, 99)
    assert [i["quantity"] for i in r.data["items"]] == [5]
