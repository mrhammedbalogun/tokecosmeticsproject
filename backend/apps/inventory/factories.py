import factory

from apps.catalog.factories import ProductVariantFactory
from apps.inventory.models import StockItem, Warehouse


class WarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Warehouse

    name = factory.Sequence(lambda n: f"WH {n}")
    location_country = "NG"
    priority = 100


class StockItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StockItem

    variant = factory.SubFactory(ProductVariantFactory)
    warehouse = factory.SubFactory(WarehouseFactory)
    quantity = 0
    reserved = 0
