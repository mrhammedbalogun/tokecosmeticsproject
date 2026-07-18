from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote
from apps.shipping.services import (
    ShippingError,
    cancel_quote,
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


def _order_with_reserved_stock(qty=2):
    """An order whose stock is still RESERVED (not yet sold). cancel_order only frees
    stock that is still reserved — a paid order's stock is already committed via
    commit_sale, so `pending_payment` is the only state where 'releases stock' is a real,
    observable effect. Mirrors apps/orders/tests/test_cancel.py::_reserved_order."""
    ng = Country.objects.get(code="NG")
    order = _order()
    wh = WarehouseFactory(name=order.number, location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    reserve(variant, qty, ng, reference=order.reservation_reference)
    return order, variant


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


def test_cancelling_an_unpaid_quote_cancels_the_order_and_releases_stock(staff):
    """PRE-PAYMENT case: the customer declines before paying goods. No money was captured,
    so the order is cancelled outright and the stock reservation is freed for real buyers.
    Cosmetics have shelf life and trend risk — freeing the units recovers value."""
    order, variant = _order_with_reserved_stock(qty=2)   # pending_payment
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")
    assert variant.stock_items.get().reserved == 2

    cancel_quote(quote, staff_user=staff, note="customer declined €40")

    quote.refresh_from_db()
    order.refresh_from_db()
    assert quote.status == "cancelled"
    assert order.status == "cancelled"
    assert "declined" in quote.note
    assert variant.stock_items.get().reserved == 0   # freed for real buyers


def test_cancelling_a_paid_quote_holds_the_order_and_touches_no_money(staff):
    """MODAL case (quote-after-payment): the customer paid the goods total, then declined
    or ignored the freight quote. `cancelled` means no money was captured, so a PAID order
    must NOT be cancelled — it goes ON_HOLD, a goods refund is owed, and the owner records
    that refund by hand via record_manual_refund. This function moves NO money and NO
    stock."""
    order, variant = _order_with_reserved_stock(qty=2)
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")
    order.status = "processing"          # goods paid (mirrors _fulfil_locked's transition)
    order.save(update_fields=["status"])

    cancel_quote(quote, staff_user=staff, note="no reply after 2 weeks")

    quote.refresh_from_db()
    order.refresh_from_db()
    assert quote.status == "cancelled"
    assert order.status == "on_hold"                     # refund owed, not cancelled
    assert order.payments.count() == 0                   # no refund/freight Payment created
    assert not order.payments.filter(purpose="freight").exists()
    assert variant.stock_items.get().reserved == 2       # stock untouched — restock is the
    #                                                      manual refund's job, not ours


def test_cancelling_is_refused_once_goods_are_in_transit(staff):
    """A freight quote has no business being cancelled once the parcel has shipped. Fail
    loud rather than guess, and the atomic rollback must leave the quote untouched."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")
    order.status = "shipped"
    order.save(update_fields=["status"])

    with pytest.raises(ShippingError) as exc:
        cancel_quote(quote, staff_user=staff, note="customer changed their mind")

    assert exc.value.code == "order_not_cancellable"
    quote.refresh_from_db()
    assert quote.status == "quoted"                      # rollback left it untouched


def test_cancelling_requires_a_reason(staff):
    """The note is the ONLY authorisation artifact for the manual refund wire-out. A
    customer who paid the goods total exactly produces no discrepancy, so no
    accept_discrepancy reason string exists to authorise it."""
    order = _order()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff, amount=Decimal("40.00"), note="Adex")

    with pytest.raises(ShippingError) as exc:
        cancel_quote(quote, staff_user=staff, note="")

    assert exc.value.code == "reason_required"
