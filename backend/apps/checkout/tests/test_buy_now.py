import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.carts.models import Cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def test_buy_now_creates_single_express_cart(django_user_model):
    # Seed migration already created NG + NGN — fetch, don't re-create (avoids PK collision).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=5)
    user = django_user_model.objects.create_user(email="b@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)

    r1 = client.post("/api/v1/checkout/buy-now/", {"variant_id": variant.id, "quantity": 1},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r1.status_code == 200
    assert r1.data["kind"] == "express"
    assert r1.data["items"][0]["quantity"] == 1

    # A second Buy Now replaces the express cart contents (still one express cart).
    r2 = client.post("/api/v1/checkout/buy-now/", {"variant_id": variant.id, "quantity": 3},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r2.data["id"] == r1.data["id"]
    assert r2.data["items"][0]["quantity"] == 3
    assert Cart.objects.filter(user=user, kind="express", status="active").count() == 1
