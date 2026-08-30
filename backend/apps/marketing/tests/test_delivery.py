"""The outbox task: what it sends, what it retries, and what it refuses to retry.

Every vendor call is mocked with respx, the same way the payment gateway suites do it.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from apps.marketing.models import ConversionEvent
from apps.marketing.tasks import deliver_conversion_event
from apps.marketing.tests.factories import (
    add_item, attribution, channel, configure, customer, enable_tracking, make_order,
)

META_URL = "https://graph.facebook.com/v25.0/PIXEL123/events"


@pytest.fixture
def paid_order(django_user_model):
    user = customer(django_user_model, "amina@x.com")
    order = make_order(user=user, subtotal="50000.00", status="processing")
    add_item(order)
    attribution(order)
    return order


def _queued(order, code="meta") -> ConversionEvent:
    return ConversionEvent.objects.create(
        channel=code, event_name="purchase", event_id=order.number, order=order,
    )


@pytest.mark.django_db
@respx.mock
def test_a_delivered_event_records_what_was_actually_sent(settings, paid_order):
    """The stored payload is the body the adapter produced at DELIVERY time, not one
    guessed at enqueue time — it is the only answer to 'what did we send'."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    route = respx.post(META_URL).mock(
        return_value=httpx.Response(200, json={"events_received": 1})
    )
    event = _queued(paid_order)

    deliver_conversion_event(event.pk)

    event.refresh_from_db()
    assert route.called
    assert event.status == "sent" and event.sent_at is not None
    assert event.payload["data"][0]["event_name"] == "Purchase"
    assert event.attempts == 1


@pytest.mark.django_db
@respx.mock
def test_a_400_fails_permanently_rather_than_retrying_a_body_that_cannot_improve(
    settings, paid_order
):
    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    respx.post(META_URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "Invalid parameter"}})
    )
    event = _queued(paid_order)

    deliver_conversion_event(event.pk)

    event.refresh_from_db()
    assert event.status == "failed"
    assert "Invalid parameter" in event.last_error


@pytest.mark.django_db
@respx.mock
def test_a_channel_switched_off_after_enqueue_stops_the_backlog_too(settings, paid_order):
    """Turning a channel off means 'stop sending', including what is already queued.
    Honouring the newer decision is the whole point of a kill switch."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta", is_enabled=False)
    route = respx.post(META_URL).mock(return_value=httpx.Response(200, json={}))
    event = _queued(paid_order)

    deliver_conversion_event(event.pk)

    event.refresh_from_db()
    assert not route.called
    assert event.status == "skipped"
    assert event.last_error == "channel_disabled_before_delivery"


@pytest.mark.django_db
@respx.mock
def test_a_duplicate_task_for_a_sent_event_does_nothing(settings, paid_order):
    """Celery guarantees at-least-once. This is the 'at least' part arriving."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    route = respx.post(META_URL).mock(return_value=httpx.Response(200, json={}))
    event = _queued(paid_order)
    event.status = "sent"
    event.save(update_fields=["status"])

    result = deliver_conversion_event(event.pk)

    assert not route.called
    assert result["skipped"] == "already_sent"


@pytest.mark.django_db
def test_a_vanished_row_is_not_an_error(settings):
    assert deliver_conversion_event(999999)["skipped"] == "row_gone"


@pytest.mark.django_db
@respx.mock
def test_tiktok_business_refusal_inside_a_200_is_recorded_as_a_failure(settings, paid_order):
    """The end-to-end version of the adapter test: an integration that looks healthy
    while the ad account receives nothing must show up in this table as failed."""
    enable_tracking()
    configure(settings, "tiktok")
    channel("tiktok")
    respx.post("https://business-api.tiktok.com/open_api/v1.3/event/track/").mock(
        return_value=httpx.Response(200, json={"code": 40100, "message": "token invalid"})
    )
    event = _queued(paid_order, "tiktok")

    deliver_conversion_event(event.pk)

    event.refresh_from_db()
    assert event.status == "failed"
    assert "40100" in event.last_error


@pytest.mark.django_db
def test_the_paid_transition_queues_the_events_on_commit(settings, django_user_model,
                                                         django_capture_on_commit_callbacks,
                                                         monkeypatch):
    """The wiring itself: `orders.state` registers the marketing effect on the move to
    `processing`, and it runs AFTER the customer's confirmation email.

    Asserted through `django_capture_on_commit_callbacks` because the effects are
    deferred to commit and a plain `django_db` test never commits — which is exactly how
    this wiring could be broken without a single test noticing.
    """
    from django.db import transaction

    from apps.marketing import tasks as marketing_tasks
    from apps.orders.state import transition

    # The delivery task itself is exercised by the tests above; here only the WIRING is
    # under test, and a real `.delay` would reach for a broker that is not running.
    queued: list[int] = []
    monkeypatch.setattr(marketing_tasks.deliver_conversion_event, "delay", queued.append)

    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    user = customer(django_user_model, "amina@x.com")
    order = make_order(user=user, status="pending_payment")
    add_item(order)
    attribution(order)

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            transition(order, "processing", message="test")

    row = ConversionEvent.objects.get(order=order, channel="meta")
    assert row.status == "pending"
    assert queued == [row.pk], "the outbox row must be handed to a worker"


def test_the_marketing_effect_runs_after_the_customer_email():
    """Ordering is load-bearing, not stylistic: `on_commit` callbacks are not
    independent, and one that raises abandons every callback registered after it. The
    customer's confirmation email must never sit behind an ad platform."""
    from apps.orders.emails import enqueue_order_confirmation
    from apps.orders.state import _effects_for

    effects = _effects_for("processing")
    names = [fn.__name__ for fn in effects]
    assert effects[0] is enqueue_order_confirmation
    assert names[-1] == "enqueue_purchase", f"marketing must be last, got {names}"
