from decimal import Decimal

import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote
from apps.shipping.services import (
    ShippingError,
    quote_freight,
    record_freight_receipt,
    waive_freight,
)

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


def test_recording_a_receipt_creates_a_freight_payment(staff):
    """Cash-in is sum(Payment) grouped by currency — ONE table. The freight receipt is
    a Payment; the quote is not."""
    from apps.payments.models import Payment

    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        quote, staff_user=staff, amount_received=Decimal("32.00"),
        bank_reference="TC-100001-F", note="short after correspondent fees",
    )

    payment = Payment.objects.get(order=order, purpose="freight")
    assert payment.amount == Decimal("32.00")      # what LANDED
    assert payment.status == "succeeded"
    assert payment.gateway == "bank_transfer"
    quote.refresh_from_db()
    assert quote.status == "paid"
    assert quote.amount == Decimal("40.00")        # what was ASKED — a different number


def test_quoted_and_received_are_allowed_to_differ_without_a_flag(staff):
    """An intl wire quoted at €40 lands ~€32 after correspondent fees. That gap is
    NORMAL on the freight leg and must not raise, must not require accept_discrepancy,
    and must not flag the order for review — otherwise the review flag fires on every
    RoW order and becomes a keystroke (see payments.W001 crying wolf)."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        quote, staff_user=staff, amount_received=Decimal("32.00"),
        bank_reference="TC-100001-F", note="",
    )

    order.refresh_from_db()
    assert order.review_reason == ""


def test_a_duplicate_bank_reference_is_refused(staff):
    """One transfer quoted against two orders means goods ship twice against money
    that arrived once. A REAL unique constraint on a REAL column — not the
    raw_response JSON key that gave Plan-09b its TOCTOU race."""
    from django.db import IntegrityError

    o1, o2 = _order(), _order()
    for order in (o1, o2):
        q = ShippingQuote.objects.create(order=order, currency=order.currency)
        quote_freight(q, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        o1.shipping_quote, staff_user=staff, amount_received=Decimal("40.00"),
        bank_reference="DUP-1", note="",
    )
    with pytest.raises(IntegrityError):
        record_freight_receipt(
            o2.shipping_quote, staff_user=staff, amount_received=Decimal("40.00"),
            bank_reference="DUP-1", note="",
        )


def test_a_long_bank_reference_still_fits_the_idempotency_key(staff):
    """idempotency_key is varchar(64); prod is Postgres which enforces it. A staff-entered
    reference up to the 128-char gateway_reference limit must not overflow the key and 500."""
    from apps.payments.models import Payment

    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")
    long_ref = "SWIFT-" + "X" * 100   # 106 chars, within gateway_reference's 128

    record_freight_receipt(
        quote, staff_user=staff, amount_received=Decimal("40.00"),
        bank_reference=long_ref, note="",
    )

    payment = Payment.objects.get(order=order, purpose="freight")
    assert payment.gateway_reference == long_ref          # full reference preserved on the 128-col
    assert len(payment.idempotency_key) <= 64             # key is bounded


def test_recording_a_receipt_before_quoting_is_refused(staff):
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(ShippingError) as exc:
        record_freight_receipt(
            quote, staff_user=staff, amount_received=Decimal("40.00"),
            bank_reference="X-1", note="",
        )

    assert exc.value.code == "quote_required_before_receipt"
