import factory

from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    user = None
    kind = "standard"
    status = "active"
    # country/currency must be passed in by the test (no default market in a fresh DB).


class CartItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    variant = factory.SubFactory(ProductVariantFactory)
    quantity = 1
    unit_price_snapshot = "0.00"
