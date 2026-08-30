"""The attribution snapshot: what a hostile checkout body can and cannot put in the DB."""
from __future__ import annotations

import pytest

from apps.marketing.capture import record_attribution
from apps.marketing.models import OrderAttribution
from apps.marketing.tests.factories import customer, make_order


@pytest.fixture
def order(django_user_model):
    return make_order(user=customer(django_user_model, "a@x.com"))


@pytest.mark.django_db
def test_a_normal_blob_is_stored_whole(order):
    record_attribution(order, {
        "consent": {"marketing": True, "analytics": True, "version": 2},
        "click_ids": {"fbclid": "FB1", "ttclid": "TT1", "ts": 1700000000},
        "pixel_cookies": {"fbp": "fb.1.1.1", "ga": "111.222"},
        "client_ip": "102.89.1.1",
        "client_user_agent": "Mozilla/5.0",
        "event_source_url": "https://tokecosmetics.com/checkout",
    })
    row = OrderAttribution.objects.get(order=order)
    assert row.consent_marketing and row.consent_version == 2
    assert row.click_ids == {"fbclid": "FB1", "ttclid": "TT1", "ts": 1700000000}
    assert row.pixel_cookies == {"fbp": "fb.1.1.1", "ga": "111.222"}
    assert row.client_ip == "102.89.1.1"


@pytest.mark.django_db
def test_unknown_keys_are_dropped_rather_than_stored(order):
    """The allowlist is the actual control: this body is attacker-supplied, and nothing
    stops it carrying a megabyte of arbitrary keys except this."""
    record_attribution(order, {
        "click_ids": {"fbclid": "FB1", "evil": "x" * 10000, "__proto__": "y"},
        "pixel_cookies": {"fbp": "ok", "session_token": "stolen"},
    })
    row = OrderAttribution.objects.get(order=order)
    assert row.click_ids == {"fbclid": "FB1"}
    assert row.pixel_cookies == {"fbp": "ok"}


@pytest.mark.django_db
def test_oversized_values_are_capped(order):
    record_attribution(order, {"click_ids": {"fbclid": "F" * 5000},
                               "client_user_agent": "U" * 5000,
                               "event_source_url": "https://x.com/" + "p" * 5000})
    row = OrderAttribution.objects.get(order=order)
    assert len(row.click_ids["fbclid"]) == 512
    assert len(row.client_user_agent) == 500
    assert len(row.event_source_url) == 1000


@pytest.mark.django_db
def test_a_malformed_ip_becomes_null_instead_of_raising_inside_the_checkout_transaction(order):
    """A `GenericIPAddressField` would raise at save time — inside `place_order`'s
    locked transaction, which is a 500 at the till for a cosmetic field."""
    record_attribution(order, {"client_ip": "not-an-ip"})
    assert OrderAttribution.objects.get(order=order).client_ip is None


@pytest.mark.django_db
def test_a_junk_consent_version_reads_as_no_recorded_version(order):
    record_attribution(order, {"consent": {"marketing": True, "version": "banana"}})
    assert OrderAttribution.objects.get(order=order).consent_version == 0


@pytest.mark.django_db
def test_nonsense_input_never_raises_and_never_costs_the_order(order):
    """It runs inside the checkout transaction. Raising here would lose a sale to
    protect a row whose only consumer is an advertising dashboard."""
    for blob in (None, "", [], 42, {"consent": "yes"}, {"click_ids": "nope"}):
        OrderAttribution.objects.all().delete()
        record_attribution(order, blob)


@pytest.mark.django_db
def test_a_second_snapshot_for_the_same_order_does_not_break_the_transaction(order):
    """The OneToOne would raise IntegrityError, and a bare try/except would leave the
    transaction poisoned — the next query in `place_order` would die with
    TransactionManagementError. The inner savepoint is what makes this survivable."""
    from django.db import transaction

    with transaction.atomic():
        record_attribution(order, {"consent": {"marketing": True}})
        record_attribution(order, {"consent": {"marketing": True}})
        # The proof: the transaction is still usable afterwards.
        assert OrderAttribution.objects.filter(order=order).count() == 1
