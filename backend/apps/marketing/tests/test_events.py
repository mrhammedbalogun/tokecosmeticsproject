"""The policy layer: who gets an event, who does not, and why the record says so."""
from __future__ import annotations


import pytest

from apps.marketing.events import enqueue_purchase, purchase_payload
from apps.marketing.models import ConversionEvent
from apps.marketing.tests.factories import (
    add_item, attribution, channel, configure, customer, enable_tracking, make_order,
)


@pytest.fixture
def order(django_user_model):
    user = customer(django_user_model, "amina@x.com", first_name="Amina", last_name="Bello")
    order = make_order(user=user, subtotal="50000.00", referral_discount="2500.00",
                       shipping="1500.00", status="pending_payment")
    add_item(order)
    return order


@pytest.mark.django_db
def test_a_consented_order_queues_one_event_per_configured_channel(settings, order):
    enable_tracking()
    configure(settings, "meta", "tiktok")
    channel("meta")
    channel("tiktok")
    attribution(order)

    enqueue_purchase(order.pk)

    rows = ConversionEvent.objects.filter(order=order)
    assert {r.channel for r in rows} == {"meta", "tiktok"}
    assert all(r.event_id == order.number for r in rows), "event_id must be the order number"


@pytest.mark.django_db
def test_without_marketing_consent_nothing_is_sent_and_the_refusal_is_recorded(
    settings, order
):
    """A `skipped` row rather than no row. When purchases go missing from an ad account
    the question is always 'did we not send it, or did they not take it', and a table
    that only records attempts cannot answer."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    attribution(order, marketing=False)

    enqueue_purchase(order.pk)

    row = ConversionEvent.objects.get(order=order, channel="meta")
    assert row.status == "skipped"
    assert row.last_error == "no_marketing_consent"


@pytest.mark.django_db
def test_the_master_switch_stops_every_channel_and_records_nothing(settings, order):
    """Silent, unlike the consent and credential skips below.

    The master switch is a global state, visible on the settings screen. Recording it per
    order would add a row to every order for ever and bury the skips that mean something.
    """
    enable_tracking(tracking_enabled=False)
    configure(settings, "meta")
    channel("meta")
    attribution(order)

    enqueue_purchase(order.pk)

    assert not ConversionEvent.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_a_switched_off_channel_records_nothing_either(settings, order):
    enable_tracking()
    configure(settings, "meta")
    channel("meta", is_enabled=False)
    attribution(order)

    enqueue_purchase(order.pk)

    assert not ConversionEvent.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_a_channel_with_its_server_half_switched_off_records_nothing(settings, order):
    """The browser pixel is still doing its job; there is nothing missing to explain."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta", server_enabled=False)
    attribution(order)

    enqueue_purchase(order.pk)

    assert not ConversionEvent.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_a_missing_credential_is_named_so_the_admin_can_say_what_to_add(
    settings, order
):
    enable_tracking()
    settings.META_CAPI_ACCESS_TOKEN = ""
    channel("meta")
    attribution(order)

    enqueue_purchase(order.pk)

    assert ConversionEvent.objects.get(order=order).last_error == (
        "missing_credential:META_CAPI_ACCESS_TOKEN"
    )


@pytest.mark.django_db
def test_an_order_with_no_attribution_snapshot_is_never_sent(settings, order):
    """Orders that predate Plan-44, and orders placed by the admin or an importer. Sending
    one would mean asserting a consent nobody ever recorded."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta")

    enqueue_purchase(order.pk)

    assert ConversionEvent.objects.get(order=order).last_error == "no_attribution_snapshot"


@pytest.mark.django_db
def test_a_platform_with_no_server_api_never_gets_a_row_at_all():
    """Not a skip — "this platform has no server API" is a fact about the platform, not
    a decision about an order, so it writes nothing rather than a `skipped` row.

    `BROWSER_ONLY_CHANNELS` is empty since Plan-44b gave Google Ads a server sender, so
    the rule is asserted at the seam every caller actually asks rather than through a
    channel that no longer qualifies. The next browser-only platform inherits it.
    """
    from apps.marketing.credentials import BROWSER_ONLY_CHANNELS, supports_server_side

    assert supports_server_side("google_ads") is True
    for code in BROWSER_ONLY_CHANNELS:
        assert supports_server_side(code) is False


@pytest.mark.django_db
def test_running_twice_never_produces_a_second_event(settings, order):
    """A webhook redelivery, a replayed Celery task, an admin re-confirming a payment.
    The unique constraint is what makes this true before any network call happens."""
    enable_tracking()
    configure(settings, "meta")
    channel("meta")
    attribution(order)

    enqueue_purchase(order.pk)
    enqueue_purchase(order.pk)

    assert ConversionEvent.objects.filter(order=order, channel="meta").count() == 1


@pytest.mark.django_db
def test_enqueue_never_raises_even_when_the_order_is_gone():
    """It runs on the `on_commit` lane behind a paying customer's confirmation email.
    Nothing it does may abandon the callbacks after it."""
    enqueue_purchase(999999)  # no exception


@pytest.mark.django_db
def test_the_payload_carries_the_order_number_as_the_dedup_key_and_the_placed_at_time(order):
    attribution(order)
    payload = purchase_payload(order, order.marketing_attribution)

    assert payload.event_id == order.number
    # `placed_at`, not now: a bank transfer confirmed three days later must report the
    # sale on the day it happened or the platforms bill it to the wrong day's spend.
    assert payload.event_time == int(order.placed_at.timestamp())
    assert payload.currency == "NGN"
    assert payload.contents[0].content_id == "SKU-1"


@pytest.mark.django_db
def test_the_payload_identifies_an_account_holder_but_never_invents_an_id_for_a_guest(
    django_user_model,
):
    guest = make_order(user=None, email="guest@x.com")
    attribution(guest)
    assert purchase_payload(guest, guest.marketing_attribution).user.external_id == ""

    user = customer(django_user_model, "amina@x.com")
    theirs = make_order(user=user)
    attribution(theirs)
    assert purchase_payload(theirs, theirs.marketing_attribution).user.external_id == str(user.pk)


@pytest.mark.django_db
def test_the_address_snapshot_is_the_source_of_the_match_fields(order):
    order.shipping_address = {
        "first_name": "Amina", "last_name": "Bello", "area": "Lekki",
        "state": "Lagos", "postcode": "101233", "country_code": "NG",
    }
    order.save(update_fields=["shipping_address"])
    attribution(order)

    user = purchase_payload(order, order.marketing_attribution).user
    assert (user.first_name, user.city, user.state, user.country) == (
        "Amina", "Lekki", "Lagos", "NG"
    )
