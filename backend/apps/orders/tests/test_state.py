"""The order state machine: legal/illegal moves, the audit trail, the review flag's
independence from status, and the side-effect lanes."""
import pytest
from django.db import transaction

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import Order, OrderEvent
from apps.orders.state import ALLOWED_TRANSITIONS, IllegalTransition, transition, transition_by_id

pytestmark = pytest.mark.django_db


def _order(number="TC-300001", status="pending_payment", **kw):
    ng = Country.objects.get(code="NG")
    return OrderFactory(number=number, country=ng, currency=ng.currency, status=status, **kw)


def test_legal_transition_updates_status_and_writes_an_event():
    order = _order(status="processing")

    transition_by_id(order.pk, "shipped", message="courier collected")

    order.refresh_from_db()
    assert order.status == "shipped"
    event = order.events.get()
    assert event.type == "status:shipped"
    assert event.message == "courier collected"


def test_illegal_transition_raises_and_changes_nothing():
    order = _order(status="pending_payment")

    with pytest.raises(IllegalTransition):
        transition_by_id(order.pk, "delivered")

    order.refresh_from_db()
    assert order.status == "pending_payment"
    assert not order.events.exists()  # a rejected move leaves no trace


def test_terminal_states_allow_no_moves():
    assert ALLOWED_TRANSITIONS["cancelled"] == set()
    assert ALLOWED_TRANSITIONS["refunded"] == set()


def test_paid_orders_cannot_be_cancelled():
    """`cancelled` means no money was ever captured. A paid order exits via `refunded`,
    so there is never a cancelled order with money sitting against it."""
    order = _order(status="processing")

    with pytest.raises(IllegalTransition):
        transition_by_id(order.pk, "cancelled")


def test_transition_never_clears_the_review_flag():
    """The double-payment case: review_reason set, status left processing. Shipping the
    order must NOT erase the flag — otherwise nobody ever refunds the second charge."""
    order = _order(status="processing", review_reason="possible double payment — refund payment 7")

    transition_by_id(order.pk, "shipped")

    order.refresh_from_db()
    assert order.status == "shipped"
    assert order.review_reason == "possible double payment — refund payment 7"


@pytest.mark.django_db(transaction=True)  # the default harness wraps tests in an atomic block
def test_transition_requires_an_open_transaction():
    """transition() writes status + event + effects as one unit and assumes the caller
    holds the row lock. Calling it bare would race the expiry task."""
    order = Order(status="processing")  # unsaved — the assert fires before any query

    with pytest.raises(AssertionError):
        transition(order, "shipped")


def test_transition_records_the_actor_when_a_human_drives_it(django_user_model):
    staff = django_user_model.objects.create_user(email="ops@x.com", password="x")
    order = _order(status="processing")

    transition_by_id(order.pk, "shipped", actor=staff)

    assert order.events.get().actor == staff


def test_machine_driven_transitions_have_a_null_actor_but_say_why():
    order = _order(status="processing")

    transition_by_id(order.pk, "shipped", message="expiry task")

    event = order.events.get()
    assert event.actor is None
    assert event.message == "expiry task"  # provenance, or the timeline is useless


def test_deferred_effects_are_registered_not_executed(django_capture_on_commit_callbacks):
    """Emails must never be enqueued inside the row lock: a worker can pick the job up
    and query the order before the transaction commits, and email about an order the
    database won't yet admit exists. transition() must only REGISTER the effect."""
    fired = []
    order = _order(status="processing")

    with django_capture_on_commit_callbacks() as callbacks:
        with transaction.atomic():
            o = Order.objects.select_for_update().get(pk=order.pk)
            transition(o, "shipped", effects=[lambda order_pk: fired.append(order_pk)])
        assert fired == []  # registered under the lock, but NOT run there

    assert len(callbacks) == 1
    callbacks[0]()  # what Django itself does once the outermost block commits
    assert fired == [order.pk]


def test_event_timeline_is_ordered_oldest_first():
    order = _order(status="processing")
    transition_by_id(order.pk, "shipped")
    transition_by_id(order.pk, "delivered")

    assert [e.type for e in order.events.all()] == ["status:shipped", "status:delivered"]


def test_order_event_survives_actor_deletion(django_user_model):
    """The audit trail outlives the staff account that made the change."""
    staff = django_user_model.objects.create_user(email="leaver@x.com", password="x")
    order = _order(status="processing")
    transition_by_id(order.pk, "shipped", actor=staff)

    staff.delete()

    assert OrderEvent.objects.get(order=order).type == "status:shipped"
