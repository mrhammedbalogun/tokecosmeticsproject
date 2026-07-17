import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db

_counter = iter(range(500001, 599999))


def _order(**kw):
    ng = Country.objects.get(code="NG")
    number = kw.pop("number", None) or f"TC-{next(_counter)}"
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        status=kw.pop("status", "pending_payment"),
                        reservation_reference=number, **kw)


def test_quote_is_born_awaiting_quote():
    """The row exists from order placement, BEFORE anyone quotes. If it were created
    at quote time, 'orders awaiting a freight quote' would be a NOT EXISTS query — an
    absence, which no admin screen surfaces and nobody notices, while a paid order
    sits silent and the customer waits. A row that exists is a work queue."""
    order = _order()

    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    assert quote.status == "awaiting_quote"
    assert quote.amount is None
    assert quote.is_settled is False


def test_one_quote_per_order():
    order = _order()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(Exception):  # IntegrityError under the OneToOne constraint
        ShippingQuote.objects.create(order=order, currency=order.currency)


@pytest.mark.parametrize(
    "status,settled",
    [("awaiting_quote", False), ("quoted", False), ("paid", True), ("waived", True),
     ("cancelled", True)],
)
def test_is_settled(status, settled):
    """is_settled drives Order.is_shippable. awaiting_quote and quoted are NOT settled:
    the order must not ship while freight is unpaid."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency, status=status)

    assert quote.is_settled is settled
