from decimal import Decimal

import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote
from apps.shipping.services import ShippingError, quote_freight, waive_freight

pytestmark = pytest.mark.django_db

_counter = iter(range(600001, 699999))


def _order():
    ng = Country.objects.get(code="NG")
    number = f"TC-{next(_counter)}"
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        status="pending_payment", reservation_reference=number)


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(email="s@x.com", password="pw", is_staff=True)


def test_quote_sets_amount_and_status(staff):
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    quote.refresh_from_db()
    assert quote.status == "quoted"
    assert quote.amount == Decimal("40.00")
    assert quote.quoted_at is not None


def test_requoting_appends_to_note_and_never_erases_the_trail(staff):
    """Re-quoting overwrites `amount`, so `note` is the ONLY record of what was
    previously promised. Assigning instead of appending is the money-loss bug."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")
    quote_freight(quote, staff_user=staff, amount=Decimal("28.00"), note="cheaper forwarder")

    quote.refresh_from_db()
    assert quote.amount == Decimal("28.00")
    assert "40.00" in quote.note        # the superseded figure survives
    assert "Adex" in quote.note
    assert "cheaper forwarder" in quote.note


def test_waiving_without_a_prior_quote_is_refused(staff):
    """Waiving a charge with no amount records NOTHING — the off-books hole this design
    exists to close, re-entered through the front door."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(ShippingError) as exc:
        waive_freight(quote, staff_user=staff, note="goodwill")

    assert exc.value.code == "quote_required_before_waive"
    quote.refresh_from_db()
    assert quote.status == "awaiting_quote"


def test_waiving_after_a_quote_records_the_forgiven_amount(staff):
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    waive_freight(quote, staff_user=staff, note="goodwill — repeat customer")

    quote.refresh_from_db()
    assert quote.status == "waived"
    assert quote.amount == Decimal("40.00")     # the forgiven value is still legible
    assert quote.settled_at is not None


def test_waiving_requires_a_reason(staff):
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    with pytest.raises(ShippingError) as exc:
        waive_freight(quote, staff_user=staff, note="")

    assert exc.value.code == "reason_required"
