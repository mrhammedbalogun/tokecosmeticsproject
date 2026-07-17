"""Manual refunds — the path EVERY refund takes now that bank transfer is the only live
gateway at launch.

The wedge these exist to prevent: BankTransferGateway never implemented refund(), so it
inherited base.py's bare NotImplementedError. That is a RuntimeError, not a GatewayError,
so it escaped create_refund's `except GatewayError` — the staff request 500'd AND the
`pending` Refund row reserved in phase 1 was never resolved. refundable_amount counts
pending rows, so one 500 reserved that money forever and every later refund on that
payment failed amount_exceeds_remaining. Permanently.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import GatewayError
from apps.payments.models import Refund
from apps.payments.refunds import (
    RefundError,
    create_refund,
    record_manual_refund,
    refundable_amount,
)

pytestmark = pytest.mark.django_db


def _bank_transfer_order(number="TC-800001", total="10000.00", qty=2, status="processing"):
    # Seed migration already created NG + NGN — fetch, don't re-create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=8)
    order = OrderFactory(number=number, country=ng, currency=ngn, reservation_reference=number,
                         grand_total=total, status=status, email="c@x.com")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="5000.00", line_total=total, quantity=qty,
                             fulfillment_warehouses={"Lagos HQ": qty})
    payment = PaymentFactory(order=order, currency=ngn, gateway="bank_transfer",
                             gateway_reference=number, amount=total, status="succeeded")
    return order, payment, variant


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                 is_staff=True)


def test_full_manual_refund_settles_the_payment_and_the_order(staff):
    """The transfer has ALREADY left our bank by the time staff record it — there is no
    pending phase to pass through, so the Refund is born succeeded."""
    order, payment, _ = _bank_transfer_order()

    refund = record_manual_refund(payment=payment, amount=Decimal("10000.00"),
                                  staff_user=staff, bank_reference="RF001")

    assert refund.status == "succeeded"
    assert refund.gateway_reference == "RF001"
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "refunded"
    assert order.status == "refunded"
    assert refundable_amount(payment) == Decimal("0")


def test_manual_refund_is_auditable_back_to_the_human_and_the_bank_line(staff):
    """Nothing else links this money leaving the bank to a person who decided it should.
    No gateway record exists to reconcile against — this event IS the reconciliation."""
    order, payment, _ = _bank_transfer_order(number="TC-800002")

    record_manual_refund(payment=payment, amount=Decimal("10000.00"), staff_user=staff,
                         bank_reference="RF-BANKLINE-77", note="customer returned it")

    event = order.events.get(type="refund_recorded_manually")
    assert event.actor == staff
    assert "RF-BANKLINE-77" in event.message


def test_partial_manual_refund_leaves_a_shipped_order_shipped(staff):
    """A partial refund is a ledger fact, not a lifecycle move. Stomping a shipped order
    drops it out of the packing pipeline while the customer is still owed the rest."""
    order, payment, _ = _bank_transfer_order(number="TC-800003", status="shipped")

    record_manual_refund(payment=payment, amount=Decimal("2500.00"), staff_user=staff,
                         bank_reference="RF002")

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "partially_refunded"  # the ledger records the partial
    assert order.status == "shipped"  # ...the lifecycle does not
    assert refundable_amount(payment) == Decimal("7500.00")


def test_routing_a_bank_transfer_through_the_gateway_path_does_not_wedge_the_payment():
    """The regression test for the wedge. create_refund must fail in the GATEWAY
    vocabulary so its existing handler releases the row it reserved — a NotImplementedError
    escaping instead would strand that `pending` row and reserve the amount forever.
    """
    order, payment, _ = _bank_transfer_order(number="TC-800004")

    with pytest.raises(GatewayError, match="manual"):
        create_refund(payment=payment, amount=Decimal("10000.00"))

    assert not Refund.objects.filter(status="pending").exists()  # nothing stranded
    payment.refresh_from_db()
    assert refundable_amount(payment) == Decimal("10000.00")  # still fully refundable
    assert payment.status == "succeeded"  # unchanged


def test_manual_refund_rejects_more_than_is_left(staff):
    order, payment, _ = _bank_transfer_order(number="TC-800005")
    record_manual_refund(payment=payment, amount=Decimal("8000.00"), staff_user=staff,
                         bank_reference="RF003")

    with pytest.raises(RefundError) as exc:
        record_manual_refund(payment=payment, amount=Decimal("3000.00"), staff_user=staff,
                             bank_reference="RF004")
    assert exc.value.code == "amount_exceeds_remaining"


def test_manual_restock_rejected_on_a_partial_refund(staff):
    """The fulfillment_warehouses snapshot says where each line shipped from, not which
    lines a partial covers — the same rule create_refund enforces, not a looser one."""
    order, payment, _ = _bank_transfer_order(number="TC-800006")

    with pytest.raises(RefundError) as exc:
        record_manual_refund(payment=payment, amount=Decimal("100.00"), staff_user=staff,
                             bank_reference="RF005", restock=True)
    assert exc.value.code == "restock_requires_full_refund"


def test_manual_refund_cannot_be_taken_against_uncollected_money(staff):
    order, payment, _ = _bank_transfer_order(number="TC-800007")
    payment.status = "initiated"
    payment.save(update_fields=["status"])

    with pytest.raises(RefundError) as exc:
        record_manual_refund(payment=payment, amount=Decimal("100.00"), staff_user=staff,
                             bank_reference="RF006")
    assert exc.value.code == "payment_not_refundable"


# --- API ---------------------------------------------------------------------


def _url(order):
    return f"/api/v1/admin/orders/{order.number}/manual-refund/"


def test_manual_refund_api_records_the_refund(staff):
    order, payment, _ = _bank_transfer_order(number="TC-800008")
    client = APIClient()
    client.force_authenticate(staff)

    r = client.post(_url(order),
                    {"amount": "4000.00", "bank_reference": "RF007", "note": "damaged"},
                    format="json")

    assert r.status_code == 201, r.data
    assert r.data["status"] == "succeeded"
    assert r.data["remaining"] == "6000.00"
    assert r.data["payment_status"] == "partially_refunded"
    refund = Refund.objects.get()
    assert refund.created_by == staff
    assert refund.gateway_reference == "RF007"


def test_a_customer_cannot_record_a_refund_to_themselves(django_user_model):
    order, payment, _ = _bank_transfer_order(number="TC-800009")
    user = django_user_model.objects.create_user(email="nobody@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)

    r = client.post(_url(order), {"amount": "100.00", "bank_reference": "RF008"},
                    format="json")

    assert r.status_code == 403
    assert not Refund.objects.exists()


def test_manual_refund_api_maps_a_refund_error_to_400(staff):
    order, payment, _ = _bank_transfer_order(number="TC-800010")
    client = APIClient()
    client.force_authenticate(staff)

    r = client.post(_url(order), {"amount": "99999.00", "bank_reference": "RF009"},
                    format="json")

    assert r.status_code == 400, r.data
    assert r.data["error"] == "amount_exceeds_remaining"
