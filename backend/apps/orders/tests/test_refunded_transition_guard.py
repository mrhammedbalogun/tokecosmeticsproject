"""A status flip must never stand in for a refund.

`AdminOrderTransitionView` elevated exactly one destination (`cancelled`) and routed
exactly one to a service. Everything else fell through to `transition_by_id`, a bare status
flip — and `refunded` is reachable from `processing`, `shipped`, `delivered` and `completed`
(`orders/state.py`). So a caller holding only `orders.operate` could POST
`{"to_status": "refunded"}` and get a 200 with **no Refund row, no money moved, no restock**,
leaving the order in a terminal status and out of the pipeline. Audited — which means the
trail recorded a refund that never happened.

The view's own comment states the rule it broke: *"Any status with a mandatory side-effect
belongs in this dispatch."*

BLOCKING IT OUTRIGHT WOULD HAVE BEEN WRONG. `on_hold` is the triage state for Plan-23's 879
migrated legacy orders, and `on_hold → refunded` is deliberate: a legacy order refunded in
WooCommerce years ago has no money to move and needs recording as history. So the guard
separates the two cases by what the LEDGER says rather than by status alone:

* an order with a succeeded, not-yet-fully-refunded payment → refuse; the refund machinery
  owns that move;
* an order with no such payment → allow, with `orders.manage`.
"""
from decimal import Decimal
from itertools import count

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import grant_role
from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import Order
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"

_numbers = count(100_001)


def make_order(status):
    """`OrderFactory` leaves number/country/currency to the caller by design."""
    ng = Country.objects.get(code="NG")
    return OrderFactory(
        number=f"TC-{next(_numbers)}",
        country=ng,
        currency=ng.currency,
        status=status,
        grand_total=Decimal("1000.00"),
    )


def staff(email, role):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(email=email, password=PW)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return grant_role(user, role)


def client_for(role, email=None):
    c = APIClient()
    c.force_authenticate(user=staff(email or f"{role.lower()}@toke.test", role))
    return c


def paid(order, status="succeeded"):
    """A goods payment on the order, as a real capture would leave it."""
    return Payment.objects.create(
        order=order,
        gateway="bank_transfer",
        purpose="goods",
        amount=order.grand_total or Decimal("1000.00"),
        currency=order.currency,
        status=status,
    )


def transition(c, order, to_status):
    return c.post(
        f"/api/v1/admin/orders/{order.number}/transition/",
        {"to_status": to_status, "message": "test"},
        format="json",
    )


# --- the hole itself -----------------------------------------------------------------


def test_support_cannot_mark_a_paid_order_refunded():
    """THE DEFECT. Before the guard this returned 200 and silently ended the order."""
    order = make_order("processing")
    paid(order)

    r = transition(client_for("Support"), order, "refunded")

    assert r.status_code == 403, r.data
    order.refresh_from_db()
    assert order.status == "processing"


def test_a_manager_cannot_either_when_money_is_actually_owed():
    """Scope is not the whole control. A Manager may issue refunds — through the refund
    endpoint, which moves money and writes a Refund row. A status flip does neither, and
    holding `orders.manage` does not make it mean anything different."""
    order = make_order("processing")
    paid(order)

    r = transition(client_for("Manager"), order, "refunded")

    assert r.status_code == 400, r.data
    assert "refund" in str(r.data).lower()
    order.refresh_from_db()
    assert order.status == "processing"


def test_no_refund_row_is_created_by_the_refusal():
    order = make_order("processing")
    payment = paid(order)

    transition(client_for("Manager"), order, "refunded")

    assert payment.refunds.count() == 0


# --- the legacy triage path, which must keep working ---------------------------------


def test_a_manager_may_record_a_legacy_refund_from_on_hold():
    """Plan-23 migrates 879 legacy orders into `on_hold` for triage. One refunded in
    WooCommerce years ago has no captured payment here and no money to move — recording it
    is history, not a financial act."""
    order = make_order("on_hold")

    r = transition(client_for("Manager"), order, "refunded")

    assert r.status_code == 200, r.data
    order.refresh_from_db()
    assert order.status == "refunded"


def test_support_still_cannot_record_one():
    """The legacy path is legitimate; it is not Support's to walk."""
    order = make_order("on_hold")

    r = transition(client_for("Support"), order, "refunded")

    assert r.status_code == 403, r.data


def test_a_fully_refunded_payment_does_not_block_the_status_catching_up():
    """The refund machinery sets `refunded` itself, but a partially-applied history — the
    ledger settled, the lifecycle not — must remain correctable by hand."""
    order = make_order("on_hold")
    paid(order, status="refunded")

    r = transition(client_for("Manager"), order, "refunded")

    assert r.status_code == 200, r.data


# --- everything else must be untouched -----------------------------------------------


@pytest.mark.parametrize("to_status", ["shipped", "on_hold"])
def test_ordinary_transitions_still_work_for_support(to_status):
    order = make_order("processing")

    r = transition(client_for("Support"), order, to_status)

    assert r.status_code == 200, r.data


def test_cancelling_still_requires_orders_manage():
    """The pre-existing elevation must survive the new one."""
    order = make_order("pending_payment")

    assert transition(client_for("Support"), order, "cancelled").status_code == 403
    assert transition(client_for("Manager"), order, "cancelled").status_code == 200


def test_an_illegal_transition_is_still_a_400_not_a_403():
    """The scope check runs before the order lookup, so it must not swallow the state
    machine's own refusal."""
    order = make_order("cancelled")  # terminal

    r = transition(client_for("Manager"), order, "shipped")

    assert r.status_code == 400, r.data
    assert Order.objects.get(pk=order.pk).status == "cancelled"
