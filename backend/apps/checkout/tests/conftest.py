"""Shared fixtures for apps/checkout tests."""
from decimal import Decimal

import pytest

from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.pricing.models import Price


@pytest.fixture
def priced_cart(django_user_model):
    """(user, cart) — an active NG cart with one priced line, ready for a totals quote.
    NG/NGN are seeded by core migration 0003 (tax_rate_percent=7.50, prices_include_tax=True)
    — fetch, don't re-create (mirrors apps/checkout/tests/test_checkout_flow.py::_world)."""
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    user = django_user_model.objects.create_user(email="quote@x.com", password="pw")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")
    return user, cart
