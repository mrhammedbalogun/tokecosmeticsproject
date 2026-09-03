"""Shared scaffolding for the combo tests: a market, stock, and a priced bundle."""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price


@pytest.fixture
def ng():
    # NG + NGN are seeded by the core data migration; fetch rather than create.
    return Country.objects.get(code="NG")


@pytest.fixture
def warehouse(ng):
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    return wh


@pytest.fixture
def priced_variant(ng, warehouse):
    """A factory-of-a-factory: `priced_variant(amount, stock)` → a sellable variant."""

    def make(amount="1000.00", stock=100):
        variant = ProductVariantFactory()
        Price.objects.create(
            variant=variant, currency=ng.currency, amount=Decimal(amount)
        )
        StockItemFactory(variant=variant, warehouse=warehouse, quantity=stock)
        return variant

    return make


@pytest.fixture
def combo(priced_variant):
    """Two items, ₦1,000 + 2 x ₦500 = ₦2,000 of components, 10% off → ₦1,800."""

    def make(discount_percent=10, **kwargs):
        c = ComboFactory(discount_percent=discount_percent, **kwargs)
        ComboItemFactory(combo=c, variant=priced_variant("1000.00"), quantity=1)
        ComboItemFactory(combo=c, variant=priced_variant("500.00"), quantity=2)
        return c

    return make
