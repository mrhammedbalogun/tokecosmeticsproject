from decimal import Decimal

import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db

_counter = iter(range(700001, 799999))


def _order():
    """A normal NG order — mirrors apps/shipping/tests/test_services.py::_order."""
    ng = Country.objects.get(code="NG")
    number = f"TC-{next(_counter)}"
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        status="pending_payment", reservation_reference=number)


def test_order_with_no_quote_is_shippable():
    """Every NG order. The gate must not change the default."""
    order = _order()
    assert order.is_shippable is True


@pytest.mark.parametrize("status,shippable", [
    ("awaiting_quote", False),
    ("quoted", False),
    ("paid", True),
    ("waived", True),
    ("cancelled", False),   # DECLINED freight must NOT be shippable — the key correction
])
def test_freight_state_gates_shipping(status, shippable):
    order = _order()
    ShippingQuote.objects.create(
        order=order, currency=order.currency, status=status,
        amount=None if status == "awaiting_quote" else Decimal("40.00"),
    )
    order.refresh_from_db()
    assert order.is_shippable is shippable
