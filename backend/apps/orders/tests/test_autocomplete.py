"""The 14-day auto-complete sweep. Staff can complete an order sooner from the admin;
this is the backstop so orders don't park at `delivered` forever."""
import pytest
from django.utils import timezone

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderEvent
from apps.orders.tasks import complete_delivered_orders

pytestmark = pytest.mark.django_db


def _delivered(number, days_ago, status="delivered"):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=number, country=ng, currency=ng.currency, status=status,
                         email="b@x.com")
    # The clock runs from when it was DELIVERED, not when it was placed.
    OrderEvent.objects.filter(order=order).delete()
    event = OrderEvent.objects.create(order=order, type="status:delivered", message="seed")
    OrderEvent.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timezone.timedelta(days=days_ago)
    )
    return order


def test_completes_orders_delivered_longer_than_the_return_window():
    order = _delivered("TC-800001", days_ago=15)

    assert complete_delivered_orders() == 1

    order.refresh_from_db()
    assert order.status == "completed"


def test_leaves_orders_still_inside_the_return_window():
    order = _delivered("TC-800002", days_ago=13)

    assert complete_delivered_orders() == 0

    order.refresh_from_db()
    assert order.status == "delivered"


def test_ignores_orders_that_are_not_delivered():
    """A refunded or on_hold order is not waiting out a return window."""
    order = _delivered("TC-800003", days_ago=30, status="refunded")

    assert complete_delivered_orders() == 0

    order.refresh_from_db()
    assert order.status == "refunded"


def test_the_sweep_is_attributable_in_the_timeline():
    order = _delivered("TC-800004", days_ago=20)

    complete_delivered_orders()

    event = order.events.get(type="status:completed")
    assert event.actor is None  # machine-driven...
    assert "return window" in event.message  # ...so the message has to say why


def test_one_poison_order_cannot_block_the_rest(monkeypatch):
    """One transaction per order: a failure must not roll back its siblings or abort the
    sweep, or a single bad row freezes every future run."""
    from apps.orders import tasks

    a = _delivered("TC-800005", days_ago=20)
    b = _delivered("TC-800006", days_ago=20)

    real = tasks._complete_one
    calls = {"n": 0}

    def boom(pk):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("poison")
        return real(pk)

    monkeypatch.setattr(tasks, "_complete_one", boom)

    assert tasks.complete_delivered_orders() == 1  # the survivor still went through

    a.refresh_from_db()
    b.refresh_from_db()
    # The sweep's due-list order isn't guaranteed, so don't assume WHICH one was poisoned
    # — only that the failure didn't take its sibling down with it.
    assert sorted([a.status, b.status]) == ["completed", "delivered"]
