import pytest
from decimal import Decimal

from apps.carts.factories import CartFactory, CartItemFactory
from apps.carts.serializers import serialize_cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _ng():
    # Seeded by core migration 0003 with tax_rate_percent=7.50, prices_include_tax=True.
    return Country.objects.get(code="NG")


def test_cart_lines_priced_from_resolve_price_not_snapshot():
    ng = _ng()
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ng.currency, amount=Decimal("1000.00"))
    cart = CartFactory(country=ng, currency=ng.currency)
    # snapshot deliberately stale (500) — output must use the live 1000 price.
    CartItemFactory(cart=cart, variant=variant, quantity=2, unit_price_snapshot="500.00")

    data = serialize_cart(cart, ng)

    line = data["items"][0]
    assert line["unit_price"] == "1000.00"
    assert line["line_total"] == "2000.00"
    assert line["unavailable"] is False
    assert data["subtotal"] == "2000.00"
    assert data["currency"] == "NGN"


def test_unpriced_line_marked_unavailable():
    ng = _ng()
    variant = ProductVariantFactory()  # no Price row for NG
    cart = CartFactory(country=ng, currency=ng.currency)
    CartItemFactory(cart=cart, variant=variant, quantity=1, unit_price_snapshot="0.00")

    data = serialize_cart(cart, ng)

    assert data["items"][0]["unavailable"] is True
    assert data["items"][0]["unit_price"] is None
    assert data["subtotal"] == "0.00"  # unavailable lines contribute 0
