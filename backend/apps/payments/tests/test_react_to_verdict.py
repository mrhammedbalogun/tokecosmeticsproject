"""_react_to_verdict — the recovery ladder both confirmation paths share, and the one
thing the verdict alone cannot tell a caller: did the order actually end up FULFILLED?

NOOP_EXPIRED is the subtle case. The same verdict ends in fulfilment when the late
payment could re-reserve stock, and in an unresolved flag when the stock is gone. A
caller that writes "overpaid — refund the difference" on the second one appends noise to
the ladder's own, more urgent, instruction and implies goods shipped when they did not.
"""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import adjust, release, reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.services import MarkPaidResult, _react_to_verdict, mark_paid

pytestmark = pytest.mark.django_db


def _setup(qty=10):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    return ng, ngn, variant


def _order(number, ng, ngn, *, total="1000.00", status="pending_payment"):
    return OrderFactory(
        number=number, country=ng, currency=ngn, reservation_reference=number,
        grand_total=total, status=status, email="c@x.com",
    )


def _item(order, variant):
    return OrderItem.objects.create(order=order, variant=variant, product_name="X",
                                    unit_price="500.00", line_total="1000.00", quantity=2)


def test_fulfilled_verdict_reports_true():
    ng, ngn, variant = _setup()
    order = _order("TC-200040", ng, ngn)
    _item(order, variant)
    reserve(variant, 2, ng, reference="TC-200040")
    payment = PaymentFactory(order=order, currency=ngn, amount=Decimal("1000.00"))

    assert _react_to_verdict(payment, mark_paid(payment)) is True

    order.refresh_from_db()
    assert order.status == "processing"


def test_late_payment_that_cannot_re_reserve_reports_false():
    """Same NOOP_EXPIRED verdict as the re-reserving case — only the return value can
    tell them apart, and here we hold the customer's money but not their goods."""
    ng, ngn, variant = _setup(qty=2)
    order = _order("TC-200041", ng, ngn, status="expired")
    _item(order, variant)
    reserve(variant, 2, ng, reference="TC-200041")
    release("TC-200041")
    # Someone else buys the stock before the late payment lands.
    adjust(variant.stock_items.get(), 0, reason="correction", note="sold out")
    payment = PaymentFactory(order=order, currency=ngn, amount=Decimal("1000.00"))

    assert _react_to_verdict(payment, MarkPaidResult.NOOP_EXPIRED) is False

    order.refresh_from_db()
    assert order.status == "expired"  # the truth — it really did expire
    assert "could not re-reserve" in order.review_reason


def test_late_payment_that_re_reserves_reports_true():
    """The counterpart to the case above: an IDENTICAL NOOP_EXPIRED verdict, but the
    stock is still there, so the order does end up fulfilled. The pair is the whole
    reason this function returns anything — the return value tracks the outcome, not the
    verdict it was handed. Without this half, `return False` here would keep the suite
    green while telling callers no goods shipped when they did."""
    ng, ngn, variant = _setup(qty=10)
    order = _order("TC-200042", ng, ngn, status="expired")
    _item(order, variant)
    reserve(variant, 2, ng, reference="TC-200042")
    release("TC-200042")
    payment = PaymentFactory(order=order, currency=ngn, amount=Decimal("1000.00"))

    assert _react_to_verdict(payment, MarkPaidResult.NOOP_EXPIRED) is True

    order.refresh_from_db()
    assert order.status == "processing"
    assert order.reservation_reference == "TC-200042/2"  # bumped attempt suffix


def test_cancelled_order_reports_false_and_flags_a_refund():
    ng, ngn, variant = _setup()
    order = _order("TC-200043", ng, ngn, status="cancelled")
    payment = PaymentFactory(order=order, currency=ngn, amount=Decimal("1000.00"))

    assert _react_to_verdict(payment, MarkPaidResult.NOOP_CANCELLED) is False

    order.refresh_from_db()
    assert order.status == "cancelled"  # unchanged
    assert "refund it" in order.review_reason
