"""The 'refunds owed' worklist — orders parked on_hold because a freight quote was
cancelled on a PAID order, where the operator still owes a manual goods refund.

Why this exists: cancel_quote (apps/shipping/services.py) moves a paid order to on_hold
and deliberately does NOT refund — a human records the refund later via
record_manual_refund. Nothing else surfaces that debt, and a solo operator will forget
it, leaving a paying customer with neither goods nor money. This queue is the reminder.

The predicate is on the QUOTE state, not a new Order status: `on_hold` alone is
ambiguous (the model also uses it for migrated orders), so the cancelled quote is what
identifies the freight-decline flow.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.models import Payment, Refund
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db

_counter = iter(range(700001, 799999))


def _order(status):
    ng = Country.objects.get(code="NG")
    number = f"TC-{next(_counter)}"
    return OrderFactory(number=number, country=ng, currency=ng.currency, status=status,
                        reservation_reference=number, grand_total=Decimal("40.00"))


def _quote(order, status):
    return ShippingQuote.objects.create(order=order, currency=order.currency, status=status)


def _goods_payment(order, amount="40.00", status="succeeded"):
    return Payment.objects.create(
        order=order, gateway="bank_transfer", purpose="goods",
        amount=Decimal(amount), currency=order.currency, status=status,
        # idempotency_key is globally unique; the "" default collides across orders.
        idempotency_key=f"goods:{order.number}",
    )


def _succeeded_refund(payment, amount):
    return Refund.objects.create(payment=payment, amount=Decimal(amount), status="succeeded")


def test_on_hold_order_with_a_cancelled_quote_is_in_the_worklist():
    from apps.orders.services import orders_owed_a_refund

    order = _order("on_hold")
    _quote(order, "cancelled")
    _goods_payment(order)

    assert list(orders_owed_a_refund()) == [order]


def test_on_hold_order_whose_quote_is_not_cancelled_is_excluded():
    """`on_hold` alone is ambiguous — the model uses it for migrated orders too. Only a
    CANCELLED quote marks the freight-decline flow that owes a refund. An on_hold order
    with a paid quote (or a migrated one with no cancel) is NOT a refund debt."""
    from apps.orders.services import orders_owed_a_refund

    paid_quote = _order("on_hold")
    _quote(paid_quote, "paid")
    _order("on_hold")  # a legacy on_hold order with no shipping_quote at all

    assert list(orders_owed_a_refund()) == []


def test_fully_refunded_order_is_excluded():
    """A full manual refund transitions the order off on_hold to `refunded`, so it drops
    out of the queue on its own — no explicit 'has a refund' filter needed."""
    from apps.orders.services import orders_owed_a_refund

    order = _order("refunded")
    _quote(order, "cancelled")
    p = _goods_payment(order, status="refunded")
    _succeeded_refund(p, "40.00")

    assert list(orders_owed_a_refund()) == []


def test_partially_refunded_on_hold_order_stays_on_the_queue():
    """The safety property: a PARTIAL refund leaves the order at on_hold, so money is
    still owed and it must remain visible. Excluding 'any order with a succeeded refund'
    would hide a half-settled debt."""
    from apps.orders.services import orders_owed_a_refund

    order = _order("on_hold")
    _quote(order, "cancelled")
    p = _goods_payment(order, status="partially_refunded")
    _succeeded_refund(p, "10.00")  # only part of the 40.00 sent back

    assert list(orders_owed_a_refund()) == [order]


def test_unpaid_declined_order_is_excluded():
    """When freight is cancelled on an UNPAID order, cancel_quote cancels the order (no
    money was captured) — status `cancelled`, not on_hold. Nothing is owed."""
    from apps.orders.services import orders_owed_a_refund

    order = _order("cancelled")
    _quote(order, "cancelled")

    assert list(orders_owed_a_refund()) == []


# --------------------------------------------------------------------------- endpoint
@pytest.fixture
def admin_client(django_user_model):
    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    return client


def test_endpoint_lists_owed_orders_with_the_outstanding_amount(admin_client):
    order = _order("on_hold")
    q = _quote(order, "cancelled")
    q.settled_at = order.placed_at  # cancelled timestamp exists
    q.note = "[2026-07-17 10:00] cancelled by staff@x.com: customer never answered"
    q.save()
    p = _goods_payment(order, amount="40.00", status="partially_refunded")
    _succeeded_refund(p, "10.00")

    r = admin_client.get("/api/v1/admin/refunds-owed/")

    assert r.status_code == 200, r.data
    rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["number"] == order.number
    assert row["goods_amount"] == "40.00"
    assert row["refunded"] == "10.00"
    assert row["outstanding"] == "30.00"
    assert "never answered" in row["cancel_note"]


def test_a_pending_refund_does_not_reduce_the_outstanding_amount(admin_client):
    """Only a SUCCEEDED refund is money that actually reached the customer. A pending or
    failed refund is in-flight or dead, so the debt is still fully owed — it must not shrink
    `outstanding` and quietly under-state what the customer is still due."""
    order = _order("on_hold")
    _quote(order, "cancelled")
    p = _goods_payment(order, amount="40.00")
    Refund.objects.create(payment=p, amount=Decimal("40.00"), status="pending")

    r = admin_client.get("/api/v1/admin/refunds-owed/")

    rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
    assert len(rows) == 1
    assert rows[0]["refunded"] == "0.00"
    assert rows[0]["outstanding"] == "40.00"


def test_endpoint_excludes_orders_that_owe_nothing(admin_client):
    settled = _order("on_hold")
    _quote(settled, "paid")  # not a refund debt

    r = admin_client.get("/api/v1/admin/refunds-owed/")

    assert r.status_code == 200, r.data
    rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
    assert rows == []


def test_endpoint_is_staff_only():
    order = _order("on_hold")
    _quote(order, "cancelled")

    r = APIClient().get("/api/v1/admin/refunds-owed/")

    assert r.status_code in (401, 403)


def test_endpoint_stays_query_bounded_as_rows_grow(admin_client, django_assert_max_num_queries):
    """The per-row money computation reads payments + refunds. Without the prefetch that is
    an N+1 that degrades as the backlog grows — the exact time the operator needs the
    screen. Adding orders must not add per-row queries."""
    for _ in range(4):
        o = _order("on_hold")
        _quote(o, "cancelled")
        p = _goods_payment(o)
        _succeeded_refund(p, "5.00")

    # A small fixed budget: auth/session + the order page + the prefetch queries. The point
    # is that it does NOT scale with the number of orders, not the exact constant.
    with django_assert_max_num_queries(12):
        r = admin_client.get("/api/v1/admin/refunds-owed/")
    assert r.status_code == 200
    rows = r.json()["results"] if isinstance(r.json(), dict) else r.json()
    assert len(rows) == 4
