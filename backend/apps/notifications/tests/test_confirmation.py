"""The confirmation gate for external recipients.

An external address is one somebody typed into a form. Everything here exists because a
typo (`orders@gmali.com`) is accepted, joins the list, and then fails in a way that is
indistinguishable from working: silence.
"""
import pytest
from django.core import mail
from django.test import Client

from apps.notifications.confirm import confirm_url_for, inherit_confirmation, send_confirmation
from apps.notifications.models import NotificationRecipient, resolve_recipients
from apps.notifications.tokens import (
    CONFIRM_MAX_AGE,
    ConfirmTokenError,
    make_confirm_token,
    read_confirm_token,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.API_PUBLIC_URL = "https://api.example.com"


def external(event="order.paid", email="packing@example.com"):
    return NotificationRecipient.objects.create(event=event, email=email)


def path_for(recipient):
    return confirm_url_for(recipient).split("https://api.example.com")[-1]


# ── the gate ────────────────────────────────────────────────────────────────────────

def test_a_new_external_address_receives_nothing_until_it_confirms():
    row = external()
    assert row.is_confirmed is False
    assert resolve_recipients("order.paid") == []


def test_a_staff_row_is_confirmed_by_construction(django_user_model):
    """Their address is already proven — they accepted an emailed invite at it and sign in
    with it. A second confirmation would be ceremony with no control behind it."""
    person = django_user_model.objects.create_user(email="colleague@x.com", is_staff=True)
    row = NotificationRecipient.objects.create(event="order.paid", user=person)
    assert row.is_confirmed is True
    assert resolve_recipients("order.paid") == ["colleague@x.com"]


# ── scanner safety: the whole reason this is a page and not a link ──────────────────

def test_a_GET_does_not_confirm():
    """THE CONTROL THIS FEATURE LIVES OR DIES BY. Corporate mail security (SafeLinks,
    Proofpoint) FETCHES every URL in an incoming message. A confirm-on-GET endpoint is
    therefore auto-clicked by a robot, seconds after sending, for exactly the recipients
    whose employer runs link scanning — confirming an address no human ever saw."""
    row = external()
    response = Client().get(path_for(row))

    row.refresh_from_db()
    assert response.status_code == 200
    assert row.confirmed_at is None
    assert b'<form method="post">' in response.content


def test_a_POST_confirms():
    row = external()
    client = Client()
    client.post(path_for(row))

    row.refresh_from_db()
    assert row.confirmed_at is not None
    assert resolve_recipients("order.paid") == ["packing@example.com"]


def test_confirming_twice_keeps_the_first_timestamp():
    """People click twice, clients prefetch, back-buttons re-issue. None should move a
    record of when consent was actually given."""
    row = external()
    client = Client()
    client.post(path_for(row))
    row.refresh_from_db()
    first = row.confirmed_at

    client.post(path_for(row))
    row.refresh_from_db()
    assert row.confirmed_at == first


# ── confirmation is a property of the ADDRESS ──────────────────────────────────────

def test_one_click_confirms_every_event_that_address_is_on():
    """Otherwise subscribing one bookkeeper to three events means three near-identical
    'click to confirm' emails — which trains the click-links-in-unexpected-mail habit
    that makes people phishable."""
    a = external(event="order.paid")
    external(event="inventory.low_stock")
    external(event="delivery.gig_wallet_low")

    Client().post(path_for(a))

    assert NotificationRecipient.objects.filter(confirmed_at__isnull=True).count() == 0
    assert resolve_recipients("inventory.low_stock") == ["packing@example.com"]


def test_a_later_subscription_inherits_confirmation_without_a_second_email():
    a = external(event="order.paid")
    Client().post(path_for(a))
    mail.outbox = []

    later = external(event="inventory.low_stock")
    assert inherit_confirmation(later) is True
    later.refresh_from_db()
    assert later.confirmed_at is not None
    assert mail.outbox == []


def test_a_different_address_is_not_confirmed_by_someone_else_s_click():
    a = external(email="a@example.com")
    b = external(event="inventory.low_stock", email="b@example.com")

    Client().post(path_for(a))

    b.refresh_from_db()
    assert b.confirmed_at is None


# ── tokens ──────────────────────────────────────────────────────────────────────────

def test_the_confirmation_email_carries_a_working_link():
    row = external()
    assert send_confirmation(row) is True
    assert mail.outbox[-1].to == ["packing@example.com"]
    assert confirm_url_for(row).split("?token=")[1][:10] in mail.outbox[-1].body


def test_a_staff_row_is_never_sent_a_confirmation(django_user_model):
    person = django_user_model.objects.create_user(email="c@x.com", is_staff=True)
    row = NotificationRecipient.objects.create(event="order.paid", user=person)
    assert send_confirmation(row) is False
    assert mail.outbox == []


def test_a_garbage_token_is_refused():
    response = Client().post("/api/v1/notifications/confirm/?token=nonsense")
    assert response.status_code == 400
    assert b"expired" in response.content.lower()


def test_a_token_for_a_different_address_is_refused():
    """The address is bound into the signature because the address is what the recipient
    consented to. If the Owner edits the row to point elsewhere, the old link must not
    confirm the new address — that person never agreed to it."""
    row = external()
    tampered = make_confirm_token(row.pk, "someone-else@example.com")

    response = Client().post(f"/api/v1/notifications/confirm/?token={tampered}")

    row.refresh_from_db()
    assert response.status_code == 400
    assert row.confirmed_at is None


def test_an_expired_token_is_refused():
    from datetime import timedelta

    row = external()
    token = make_confirm_token(row.pk, row.email)
    with pytest.raises(ConfirmTokenError):
        read_confirm_token(token, max_age=timedelta(seconds=-1))
    assert CONFIRM_MAX_AGE == timedelta(days=7)


def test_a_token_for_a_deleted_row_is_refused():
    row = external()
    token = make_confirm_token(row.pk, row.email)
    row.delete()

    response = Client().post(f"/api/v1/notifications/confirm/?token={token}")
    assert response.status_code == 400
