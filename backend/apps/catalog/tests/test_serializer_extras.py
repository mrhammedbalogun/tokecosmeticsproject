"""Plan-13 D2: additive read-only serializer fields. Existing fields must be untouched."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.models import ProductImage
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory


@pytest.fixture
def client_product(db):
    """An active product with two active variants (v_low is_default with stock 3,
    v_ok stock 50), both NGN-priced and served to NG, plus two images."""
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory()
    wh.serves_countries.add(ng)

    product = ProductFactory()
    v_low = ProductVariantFactory(product=product, is_default=True, position=0)
    v_ok = ProductVariantFactory(product=product, is_default=False, position=1)
    for v in (v_low, v_ok):
        PriceFactory(variant=v, amount=Decimal("1000"))
    StockItemFactory(variant=v_low, warehouse=wh, quantity=3)
    StockItemFactory(variant=v_ok, warehouse=wh, quantity=50)

    ProductImage.objects.create(
        product=product, image="catalog/products/a.jpg", alt="front", position=0)
    ProductImage.objects.create(
        product=product, image="catalog/products/b.jpg", alt="back", position=1)
    return product, v_low, v_ok


@pytest.mark.django_db
class TestVariantExtras:
    def test_detail_variant_exposes_id_and_low_stock(self, client_product):
        product, v_low, v_ok = client_product
        res = APIClient().get(f"/api/v1/products/{product.slug}/", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        variants = {v["sku"]: v for v in res.data["variants"]}
        assert variants[v_low.sku]["id"] == v_low.id
        assert variants[v_low.sku]["low_stock"] is True      # qty 3
        assert variants[v_ok.sku]["low_stock"] is False      # qty 50
        # regression: pre-existing fields still present
        assert {"sku", "name", "option_values", "price", "in_stock"} <= set(variants[v_ok.sku])

    def test_detail_images_expose_variant_id(self, client_product):
        product, _, _ = client_product
        res = APIClient().get(f"/api/v1/products/{product.slug}/", HTTP_X_COUNTRY="NG")
        assert all("variant_id" in i for i in res.data["images"])


@pytest.mark.django_db
class TestCardExtras:
    def test_list_exposes_default_variant_and_hover_image(self, client_product):
        product, v_low, _ = client_product
        res = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="NG")
        row = next(r for r in res.data["results"] if r["slug"] == product.slug)
        assert row["default_variant_id"] == v_low.id          # v_low is is_default
        assert row["default_sku"] == v_low.sku
        assert row["hover_image"] is not None and row["hover_image"] != row["image"]
