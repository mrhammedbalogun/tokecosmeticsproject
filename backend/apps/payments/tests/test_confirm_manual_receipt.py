"""confirm_manual_receipt — the only path that can turn bank-transfer money into shipped
goods. There is no gateway to ask, so the staff member reading the bank statement IS the
verification, and every control here exists because the mistakes are expensive:

  * a typo (50000 for 5000) would fulfil AND plant a flag authorising a human to wire the
    difference out — with refunds manual, that flag is the whole authorisation;
  * one transfer quoted against two orders would ship goods twice for money that arrived
    once;
  * a tolerance band that silently swallowed an intl-wire shortfall would be a standing
    invitation to underpay.

So: any nonzero delta stops and makes the caller come back explicitly, with a reason.
"""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.services import (
    AmountDiscrepancy,
    DuplicateBankReference,
    confirm_manual_receipt,
)

pytestmark = pytest.mark.django_db


def _setup(qty=10):
    # Seed migration already created NG + NGN — fetch, don't re-create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    return ng, ngn, variant


def _order_awaiting_transfer(number, ng, ngn, variant, *, gateway="bank_transfer"):
    """An order sitting exactly where initiate() leaves it: pending_payment, stock held
    under its reservation reference, payment still 'initiated' because no machine can
    confirm it."""
    order = OrderFactory(
        number=number, country=ng, currency=ngn, reservation_reference=number,
        grand_total="10000.00", status="pending_payment", email="c@x.com",
    )
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="5000.00", line_total="10000.00", quantity=2)
    reserve(variant, 2, ng, reference=number)
    return order, PaymentFactory(
        order=order, currency=ngn, amount=Decimal("10000.00"),
        gateway=gateway, status="initiated",
    )


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(
        email="staff@x.com", password="pw", is_staff=True
    )


def test_exact_amount_fulfils(staff):
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300001", ng, ngn, variant)

    confirm_manual_receipt(
        payment, staff_user=staff, amount_received=Decimal("10000.00"),
        bank_reference="FT-001",
    )

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "processing"
    assert payment.status == "succeeded"
    assert order.review_reason == ""


def test_an_unexpected_amount_fails_loudly_instead_of_fulfilling(staff):
    """A staff typo is the expensive failure: 50000 for 5000 would fulfil and then flag
    "refund 45000" — and that flag IS the authorisation to wire real money out."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300002", ng, ngn, variant)

    with pytest.raises(AmountDiscrepancy) as exc:
        confirm_manual_receipt(
            payment, staff_user=staff, amount_received=Decimal("50000.00"),
            bank_reference="FT-002",
        )

    assert exc.value.expected == Decimal("10000.00")
    assert exc.value.received == Decimal("50000.00")
    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status != "succeeded"
    # Nothing happened, and the caller already has the numbers. A flag here would outlive
    # the corrected confirm that follows and leave staff chasing a resolved ghost.
    assert order.review_reason == ""
    assert order.events.filter(type="manual_receipt_refused").exists()


def test_overpayment_fulfils_and_flags_when_explicitly_accepted(staff):
    """They paid enough — don't hold their goods hostage. The surplus is a refund the
    merchant owes, which is a flag, not a reason to sit on a paid order."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300003", ng, ngn, variant)

    confirm_manual_receipt(
        payment, staff_user=staff, amount_received=Decimal("12000.00"),
        bank_reference="FT-003", note="customer rounded up", accept_discrepancy=True,
    )

    order.refresh_from_db()
    assert order.status == "processing"
    assert "2000" in order.review_reason
    assert "refund" in order.review_reason


def test_underpayment_does_not_fulfil_when_not_accepted(staff):
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300004", ng, ngn, variant)

    with pytest.raises(AmountDiscrepancy):
        confirm_manual_receipt(
            payment, staff_user=staff, amount_received=Decimal("6000.00"),
            bank_reference="FT-004",
        )

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status != "succeeded"


def test_accepted_shortfall_fulfils_and_records_who_accepted_it(staff):
    """The intl-wire case: intermediary banks eat a slice, so the amount ARRIVING is
    legitimately less than the amount sent. A human decides — never a silent tolerance
    band, which would just be a standing invitation to underpay."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300005", ng, ngn, variant)

    confirm_manual_receipt(
        payment, staff_user=staff, amount_received=Decimal("9982.00"),
        bank_reference="FT-005", note="intermediary bank fee", accept_discrepancy=True,
    )

    order.refresh_from_db()
    assert order.status == "processing"
    assert "18" in order.review_reason


def test_accepting_a_discrepancy_requires_a_reason(staff):
    """The anti-"staff always tick the box" control: mandatory friction where friction
    belongs, and it lands in the audit trail rather than in someone's memory."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300006", ng, ngn, variant)

    with pytest.raises(ValueError, match="reason"):
        confirm_manual_receipt(
            payment, staff_user=staff, amount_received=Decimal("12000.00"),
            bank_reference="FT-006", note="   ", accept_discrepancy=True,
        )

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status != "succeeded"
    assert order.review_reason == ""


def test_one_statement_line_cannot_release_two_orders(staff):
    """The customer sends ONE transfer and quotes the same reference twice. Without this,
    goods ship twice against money that arrived once — the cheapest fraud control we have."""
    ng, ngn, variant = _setup(qty=20)
    first, first_payment = _order_awaiting_transfer("TC-300007", ng, ngn, variant)
    second, second_payment = _order_awaiting_transfer("TC-300008", ng, ngn, variant)

    confirm_manual_receipt(
        first_payment, staff_user=staff, amount_received=Decimal("10000.00"),
        bank_reference="FT-DUP",
    )

    with pytest.raises(DuplicateBankReference, match="TC-300007"):
        confirm_manual_receipt(
            second_payment, staff_user=staff, amount_received=Decimal("10000.00"),
            bank_reference="FT-DUP",
        )

    second.refresh_from_db()
    assert second.status == "pending_payment"


def test_confirming_twice_is_a_benign_noop_not_a_double_payment_flag(staff):
    """Two staff confirming one transfer is one human being slow, NOT two charges."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300009", ng, ngn, variant)

    for _ in range(2):
        confirm_manual_receipt(
            payment, staff_user=staff, amount_received=Decimal("10000.00"),
            bank_reference="FT-009", allow_duplicate_reference=True,
        )

    order.refresh_from_db()
    assert order.status == "processing"
    assert "double payment" not in order.review_reason


def test_records_who_confirmed_and_against_which_statement_line(staff):
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300010", ng, ngn, variant)

    confirm_manual_receipt(
        payment, staff_user=staff, amount_received=Decimal("10000.00"),
        bank_reference="FT-010",
    )

    event = order.events.get(type="payment_confirmed_manually")
    assert event.actor == staff
    assert "FT-010" in event.message
    assert "10000.00" in event.message


def test_a_networked_gateway_cannot_be_hand_waved_into_succeeded(staff):
    """succeeded <=> money-actually-arrived holds only because nobody can assert it by
    hand for a gateway that can be asked."""
    ng, ngn, variant = _setup()
    order, payment = _order_awaiting_transfer("TC-300011", ng, ngn, variant,
                                              gateway="paystack")

    with pytest.raises(ValueError, match="machine-confirmed"):
        confirm_manual_receipt(
            payment, staff_user=staff, amount_received=Decimal("10000.00"),
            bank_reference="FT-011",
        )
