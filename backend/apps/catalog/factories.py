"""factory_boy factories for catalog + pricing test data. Import only from tests."""
from decimal import Decimal

import factory

from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Currency
from apps.pricing.models import Price


class BrandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand {n}")
    slug = factory.Sequence(lambda n: f"brand-{n}")


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    name = factory.Sequence(lambda n: f"Product {n}")
    slug = factory.Sequence(lambda n: f"product-{n}")
    status = "active"


class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Sequence(lambda n: f"{n}ml")
    is_default = True


class PriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Price

    variant = factory.SubFactory(ProductVariantFactory)
    amount = Decimal("5000.00")
    country = None

    @factory.lazy_attribute
    def currency(self):
        # Seed migration guarantees NGN exists in every test DB.
        return Currency.objects.get(code="NGN")
