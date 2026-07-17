"""The late-payment recovery path must not erase a flag that was already there.

_reserve_and_fulfil_after_expiry assigned `review_reason` directly in three branches,
bypassing _flag_review's append. It is the one recovery path that runs LONG after an
earlier flag was written (a mismatch flagged while pending_payment, then the TTL elapses,
then the money finally lands), so it is precisely where an erasure is most likely and
least visible.
"""
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.services import _flag_review, _reserve_and_fulfil_after_expiry

pytestmark = pytest.mark.django_db

MISMATCH = "payment 1: gateway reported 5000 NGN, order total is 10000 NGN — not fulfilling"


def _expired_order(*, stock: int, number: str):
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    order = OrderFactory(number=number, country=ng, currency=ng.currency,
                         reservation_reference=number, grand_total="10000.00",
                         status="expired")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="5000.00", line_total="10000.00", quantity=2)
    return order, PaymentFactory(order=order, currency=ng.currency, status="initiated")


def test_a_late_payment_that_cannot_re_reserve_keeps_the_earlier_flag():
    # The money: staff see only "could not re-reserve stock" and refund the order total,
    # never learning the gateway had also reported a different amount. The fact that
    # explains WHY the money is in dispute is the one that got erased.
    order, payment = _expired_order(stock=0, number="TC-410001")
    _flag_review(order.pk, MISMATCH)

    _reserve_and_fulfil_after_expiry(order, payment)

    order.refresh_from_db()
    assert "could not re-reserve stock" in order.review_reason
    assert MISMATCH in order.review_reason


def test_a_late_payment_racing_onto_a_cancelled_order_keeps_the_earlier_flag():
    order, payment = _expired_order(stock=10, number="TC-410002")
    _flag_review(order.pk, MISMATCH)
    order.status = "cancelled"
    order.save(update_fields=["status"])

    _reserve_and_fulfil_after_expiry(order, payment)

    order.refresh_from_db()
    assert "cancelled order" in order.review_reason
    assert MISMATCH in order.review_reason


def test_a_late_payment_racing_to_another_status_keeps_the_earlier_flag():
    order, payment = _expired_order(stock=10, number="TC-410003")
    _flag_review(order.pk, MISMATCH)
    order.status = "on_hold"
    order.save(update_fields=["status"])

    _reserve_and_fulfil_after_expiry(order, payment)

    order.refresh_from_db()
    assert "a human must decide" in order.review_reason
    assert MISMATCH in order.review_reason
