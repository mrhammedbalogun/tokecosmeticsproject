import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Product, ProductVariant
from apps.core.models import Country
from apps.inventory.models import StockItem, Warehouse


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="P", slug="p")
    return ProductVariant.objects.create(product=p, sku="P-1", name="50ml", is_default=True)


@pytest.mark.django_db
def test_warehouse_serves_countries():
    ng = Country.objects.get(code="NG")
    w = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    w.serves_countries.add(ng)
    assert list(w.serves_countries.all()) == [ng]


@pytest.mark.django_db
def test_stockitem_available_and_unique(variant):
    w = Warehouse.objects.create(name="W", location_country="NG")
    si = StockItem.objects.create(variant=variant, warehouse=w, quantity=10, reserved=3)
    assert si.available == 7
    with pytest.raises(IntegrityError):
        StockItem.objects.create(variant=variant, warehouse=w, quantity=1)  # unique (variant, warehouse)


@pytest.mark.django_db
def test_stockitem_cannot_oversell_constraint(variant):
    w = Warehouse.objects.create(name="W2", location_country="NG")
    # reserved must never exceed quantity (DB CHECK backstop).
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StockItem.objects.create(variant=variant, warehouse=w, quantity=2, reserved=5)
