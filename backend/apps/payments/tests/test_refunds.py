"""Refunds: partial math, the concurrent double-refund guard, restock from the
fulfillment snapshot, and the failed-gateway path freeing the reserved amount."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import GatewayError, PaymentGateway, RefundResult
from apps.payments.models import Refund
from apps.payments.refunds import RefundError, create_refund, refundable_amount

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    code = "fakerf"
    supported_currencies = {"NGN"}
    result = RefundResult("succeeded", "rf_1", {"ok": True})
    boom = False

    def initiate(self, payment, order, return_url=""):  # pragma: no cover
        raise NotImplementedError

    def refund(self, payment, amount, reason=""):
        if self.boom:
            raise GatewayError("gateway down")
        return self.result


@pytest.fixture
def fakerf(monkeypatch):
    gw = _FakeGateway()
    monkeypatch.setitem(registry._REGISTRY, "fakerf", gw)
    return gw


def _paid_order(number="TC-700001", total="1000.00", qty=2):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=8)
    order = OrderFactory(number=number, country=ng, currency=ngn, reservation_reference=number,
                         grand_total=total, status="processing", email="c@x.com")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total=total, quantity=qty,
                             fulfillment_warehouses={"Lagos HQ": qty})
    payment = PaymentFactory(order=order, currency=ngn, gateway="fakerf",
                             gateway_reference=number, amount=total, status="succeeded")
    return order, payment, variant


def test_full_refund_marks_refunded(fakerf):
    order, payment, _ = _paid_order()
    refund = create_refund(payment=payment, amount=Decimal("1000.00"), reason="returned")

    assert refund.status == "succeeded"
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "refunded"
    assert order.status == "refunded"
    assert refundable_amount(payment) == Decimal("0")


def test_partial_refund_math(fakerf):
    order, payment, _ = _paid_order()
    create_refund(payment=payment, amount=Decimal("250.00"))

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "partially_refunded"
    assert order.status == "processing"  # lifecycle untouched by a partial refund
    assert refundable_amount(payment) == Decimal("750.00")

    # A second partial brings it to fully refunded.
    create_refund(payment=payment, amount=Decimal("750.00"))
    payment.refresh_from_db()
    assert payment.status == "refunded"
    assert refundable_amount(payment) == Decimal("0")


def test_partial_refund_leaves_order_lifecycle_untouched(fakerf):
    """A partial refund is a payment-ledger fact, not a lifecycle move. Refunding one
    damaged item off a shipped order must leave it shipped — stomping the status drops
    the order out of the packing/delivery pipeline and nobody chases the rest of it."""
    order, payment, _ = _paid_order()
    order.status = "shipped"
    order.save(update_fields=["status"])

    create_refund(payment=payment, amount=Decimal("250.00"))

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == "partially_refunded"  # the ledger records the partial
    assert order.status == "shipped"  # ...the lifecycle does not


def test_refund_over_remaining_is_rejected(fakerf):
    order, payment, _ = _paid_order()
    create_refund(payment=payment, amount=Decimal("800.00"))
    with pytest.raises(RefundError) as exc:
        create_refund(payment=payment, amount=Decimal("300.00"))
    assert exc.value.code == "amount_exceeds_remaining"


def test_pending_refund_reserves_amount_blocking_concurrent_double_refund(fakerf):
    """A pending (async) refund still holds its claim — a second admin refunding the
    same money must be rejected, not silently allowed through."""
    order, payment, _ = _paid_order()
    fakerf.result = RefundResult("pending", "rf_async", {})
    create_refund(payment=payment, amount=Decimal("1000.00"))

    payment.refresh_from_db()
    assert refundable_amount(payment) == Decimal("0")  # reserved by the pending refund
    with pytest.raises(RefundError) as exc:
        create_refund(payment=payment, amount=Decimal("1000.00"))
    assert exc.value.code == "amount_exceeds_remaining"


def test_failed_gateway_refund_frees_the_amount(fakerf):
    order, payment, _ = _paid_order()
    fakerf.boom = True
    with pytest.raises(GatewayError):
        create_refund(payment=payment, amount=Decimal("1000.00"))

    assert Refund.objects.get().status == "failed"
    payment.refresh_from_db()
    assert refundable_amount(payment) == Decimal("1000.00")  # failed refund frees it
    assert payment.status == "succeeded"  # unchanged


def test_full_refund_with_restock_puts_stock_back(fakerf):
    order, payment, variant = _paid_order(qty=2)
    before = variant.stock_items.get().quantity
    create_refund(payment=payment, amount=Decimal("1000.00"), restock=True)

    assert variant.stock_items.get().quantity == before + 2  # from the fulfillment snapshot


def test_restock_rejected_on_partial_refund(fakerf):
    order, payment, _ = _paid_order()
    with pytest.raises(RefundError) as exc:
        create_refund(payment=payment, amount=Decimal("100.00"), restock=True)
    assert exc.value.code == "restock_requires_full_refund"


def test_unpaid_payment_cannot_be_refunded(fakerf):
    order, payment, _ = _paid_order()
    payment.status = "initiated"
    payment.save(update_fields=["status"])
    with pytest.raises(RefundError) as exc:
        create_refund(payment=payment, amount=Decimal("100.00"))
    assert exc.value.code == "payment_not_refundable"


# --- API ---------------------------------------------------------------------


def test_refund_api_requires_staff(fakerf, django_user_model):
    order, payment, _ = _paid_order()
    user = django_user_model.objects.create_user(email="nobody@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)
    r = client.post(f"/api/v1/admin/orders/{order.number}/refunds/", {"amount": "100.00"},
                    format="json")
    assert r.status_code == 403


def test_refund_api_creates_refund(fakerf, django_user_model):
    order, payment, _ = _paid_order()
    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    r = client.post(f"/api/v1/admin/orders/{order.number}/refunds/",
                    {"amount": "400.00", "reason": "damaged"}, format="json")

    assert r.status_code == 201, r.data
    assert r.data["status"] == "succeeded"
    assert r.data["remaining"] == "600.00"
    assert Refund.objects.get().created_by == staff
