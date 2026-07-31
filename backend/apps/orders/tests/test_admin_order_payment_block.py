"""What the admin order detail must let a screen READ — Plan-18a Task 1.

`AdminOrderSerializer` exposed the order and its items and nothing about money: no
payments, no refunds, no gateway, no refundable remainder. All three payments admin routes
are POST-only. So the payment panel — the screen 18a exists for — had nothing to render, and
the refund modal could not tell an operator how much was left to refund before they refunded
it.

Also here: `allowed_transitions`, which publishes THE ENDPOINT'S legal set rather than
`ALLOWED_TRANSITIONS`. The raw constant is a superset of what a person may do, and
rendering it as buttons would offer moves the API now refuses.
"""
from decimal import Decimal
from itertools import count

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import grant_role
from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.models import Payment, Refund

pytestmark = pytest.mark.django_db

_numbers = count(200_001)


def make_order(status="processing", **kw):
    ng = Country.objects.get(code="NG")
    return OrderFactory(
        number=f"TC-{next(_numbers)}", country=ng, currency=ng.currency,
        status=status, grand_total=Decimal("2000.00"), **kw,
    )


def staff(role, email=None):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email=email or f"{role.lower()}@toke.test", password="Str0ng!pass9"
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return grant_role(user, role)


def client_for(role, email=None):
    c = APIClient()
    c.force_authenticate(user=staff(role, email))
    return c


def pay(order, amount="2000.00", status="succeeded", gateway="bank_transfer", **kw):
    # `idempotency_key` is unique and defaults blank, so two payments on one order
    # collide unless each is given its own.
    kw.setdefault("idempotency_key", f"idem-{next(_numbers)}")
    return Payment.objects.create(
        order=order, gateway=gateway, purpose=kw.pop("purpose", "goods"),
        amount=Decimal(amount), currency=order.currency, status=status, **kw,
    )


def detail(client, order):
    return client.get(f"/api/v1/admin/orders/{order.number}/")


# --- the payments block --------------------------------------------------------------


def test_the_detail_carries_the_payments():
    order = make_order()
    pay(order, gateway="bank_transfer", gateway_reference="NIP-123")

    r = detail(client_for("Manager"), order)

    assert r.status_code == 200, r.data
    assert len(r.data["payments"]) == 1
    row = r.data["payments"][0]
    assert row["gateway"] == "bank_transfer"
    assert row["status"] == "succeeded"
    assert row["amount"] == "2000.00"
    assert row["gateway_reference"] == "NIP-123"


def test_a_payment_carries_its_refunds():
    order = make_order()
    payment = pay(order)
    Refund.objects.create(payment=payment, amount=Decimal("500.00"), reason="damaged",
                          status="succeeded")

    r = detail(client_for("Manager"), order)

    refunds = r.data["payments"][0]["refunds"]
    assert len(refunds) == 1
    assert refunds[0]["amount"] == "500.00"
    assert refunds[0]["reason"] == "damaged"
    assert refunds[0]["status"] == "succeeded"


def test_the_refundable_remainder_is_shown_BEFORE_refunding():
    """The refund modal could previously only learn `remaining` from the RESPONSE to a
    refund — i.e. after moving money. An operator needs it while deciding."""
    order = make_order()
    payment = pay(order, "2000.00")
    Refund.objects.create(payment=payment, amount=Decimal("750.00"), status="succeeded")

    r = detail(client_for("Manager"), order)

    assert r.data["payments"][0]["refundable"] == "1250.00"


def test_an_in_flight_refund_reduces_the_remainder_too():
    """`refundable_amount` counts pending refunds as spent — reusing it here rather than
    recomputing means the panel cannot disagree with the endpoint that enforces it."""
    order = make_order()
    payment = pay(order)
    Refund.objects.create(payment=payment, amount=Decimal("2000.00"), status="pending")

    r = detail(client_for("Manager"), order)

    assert r.data["payments"][0]["refundable"] == "0.00"


def test_a_failed_refund_does_not_reduce_the_remainder():
    order = make_order()
    payment = pay(order)
    Refund.objects.create(payment=payment, amount=Decimal("2000.00"), status="failed")

    r = detail(client_for("Manager"), order)

    assert r.data["payments"][0]["refundable"] == "2000.00"


def test_freight_payments_are_distinguishable_from_goods():
    """A freight receipt is not what refunding this order means — `OrderRefundView` picks
    `purpose="goods"` for exactly that reason, so the panel must show which is which."""
    order = make_order()
    pay(order, "2000.00", purpose="goods")
    pay(order, "3500.00", purpose="freight")

    r = detail(client_for("Manager"), order)

    purposes = {p["purpose"] for p in r.data["payments"]}
    assert purposes == {"goods", "freight"}


def test_an_order_with_no_payments_reports_an_empty_list():
    """Every migrated legacy order will look like this. Not an error state."""
    r = detail(client_for("Manager"), make_order(status="on_hold"))

    assert r.data["payments"] == []


# --- allowed_transitions -------------------------------------------------------------


def test_allowed_transitions_are_published_with_the_scope_each_needs():
    order = make_order(status="processing")

    r = detail(client_for("Manager"), order)

    by_status = {t["status"]: t["requires_scope"] for t in r.data["allowed_transitions"]}
    assert by_status["shipped"] is None
    assert by_status["on_hold"] is None


def test_cancelled_declares_the_scope_it_needs():
    """`ELEVATED_STATUSES` lives in the view, not the state machine, so a UI reading the
    raw constant would render a Cancel button that 403s for Support."""
    order = make_order(status="pending_payment")

    r = detail(client_for("Manager"), order)

    by_status = {t["status"]: t["requires_scope"] for t in r.data["allowed_transitions"]}
    assert by_status["cancelled"] == "orders.manage"


def test_REFUNDED_IS_NEVER_OFFERED():
    """It is in ALLOWED_TRANSITIONS from processing/shipped/delivered/completed and the
    endpoint now refuses it (backend-v0.5.2). Publishing it would render a button whose
    only outcome is a 400 — or, before that fix, a silent fake refund."""
    client = client_for("Manager")
    for status in ("processing", "shipped", "delivered", "completed"):
        r = detail(client, make_order(status=status))
        offered = {t["status"] for t in r.data["allowed_transitions"]}
        assert "refunded" not in offered, f"refunded offered from {status}"


def test_EXPIRED_IS_NEVER_OFFERED():
    """The sweep's move, not an operator's."""
    r = detail(client_for("Manager"), make_order(status="pending_payment"))

    assert "expired" not in {t["status"] for t in r.data["allowed_transitions"]}


def test_a_terminal_order_offers_nothing():
    r = detail(client_for("Manager"), make_order(status="cancelled"))

    assert r.data["allowed_transitions"] == []


def test_the_legacy_triage_state_still_offers_its_moves():
    """`on_hold` is deliberately broad for Plan-23's 879 migrated orders."""
    r = detail(client_for("Manager"), make_order(status="on_hold"))

    offered = {t["status"] for t in r.data["allowed_transitions"]}
    assert {"processing", "shipped", "delivered", "completed", "cancelled"} <= offered


# --- the surface is unchanged otherwise ----------------------------------------------


def test_support_can_still_read_an_order():
    """`orders.view` is the detail endpoint's scope and this task does not narrow it."""
    order = make_order()
    pay(order)

    assert detail(client_for("Support"), order).status_code == 200


def test_the_list_endpoint_is_not_given_the_payments_block():
    """It is a table of many orders; a payments array per row is weight nothing renders."""
    order = make_order()
    pay(order)

    r = client_for("Manager").get("/api/v1/admin/orders/")

    assert r.status_code == 200, r.data
    assert "payments" not in r.data["results"][0]
