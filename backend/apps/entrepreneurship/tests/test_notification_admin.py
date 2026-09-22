"""The programme's Notifications tab: what it can reach, and — mostly — what it cannot.

`order.paid` has nine real recipients on production, several of them bare external
addresses. This file exists to prove that a holder of
`entrepreneurship.notifications.manage` cannot read, write, delete or confirm any of
them. Every test below that names another event is testing the FENCE, not the feature —
and the fence is the entire reason `rbac.py` is willing to grant this scope to a Manager
rather than to the Owner alone.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.entrepreneurship.emails import EVENT_APPLICATION_RECEIVED
from apps.notifications.models import NotificationRecipient

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/entrepreneurship/notifications/"
OTHER_EVENT = "order.paid"


@pytest.fixture
def owner():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def manager():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="manager@toke.test", role="Manager"))
    return c


def programme_row(**kwargs):
    return NotificationRecipient.objects.create(
        event=EVENT_APPLICATION_RECEIVED, **kwargs
    )


def other_row(**kwargs):
    """A row this viewset must never touch."""
    return NotificationRecipient.objects.create(event=OTHER_EVENT, **kwargs)


# ── the ordinary job ─────────────────────────────────────────────────────────


def test_a_manager_can_add_an_address_and_it_lands_on_the_programme_event(manager):
    response = manager.post(BASE, {"email": "Programme@Toke.TEST"}, format="json")
    assert response.status_code == 201, response.data

    row = NotificationRecipient.objects.get()
    assert row.event == EVENT_APPLICATION_RECEIVED
    # Lowercased by the model, so the unique index can see a collision.
    assert row.email == "programme@toke.test"
    # An external address receives NOTHING until it confirms — which is how a mistyped
    # address is caught, since otherwise it looks exactly like a working one.
    assert row.confirmed_at is None


def test_the_event_in_the_body_is_IGNORED_rather_than_honoured(manager):
    """The serializer makes `event` read-only, so there is no code path at all where a
    client chooses which event they are subscribing somebody to. Ignoring rather than
    refusing means a stray key in a future client cannot turn into a 400 on a screen
    that has nothing to do with it."""
    manager.post(
        BASE, {"email": "x@toke.test", "event": OTHER_EVENT}, format="json"
    )
    assert NotificationRecipient.objects.get().event == EVENT_APPLICATION_RECEIVED


# ── the fence ────────────────────────────────────────────────────────────────


def test_the_list_shows_only_this_event(manager):
    programme_row(email="mine@toke.test")
    other_row(email="orders@toke.test")

    emails = {row["email"] for row in manager.get(BASE).data}
    assert emails == {"mine@toke.test"}


def test_ANOTHER_EVENTS_ROW_ANSWERS_404_AND_NOT_403(manager):
    """404, deliberately: a 403 would confirm the id exists, which turns this endpoint
    into a way to enumerate which recipient ids belong to `order.paid`."""
    foreign = other_row(email="orders@toke.test")
    assert manager.get(f"{BASE}{foreign.pk}/").status_code == 404


def test_another_events_row_cannot_be_deleted_through_this_surface(manager):
    foreign = other_row(email="orders@toke.test")
    assert manager.delete(f"{BASE}{foreign.pk}/").status_code == 404
    assert NotificationRecipient.objects.filter(pk=foreign.pk).exists()


def test_another_events_row_cannot_be_TEST_SENT_through_this_surface(manager):
    """The body-addressed actions are the ones that were a latent escalation before the
    mixin resolved them through `get_queryset()` rather than the bare manager."""
    foreign = other_row(email="orders@toke.test")
    response = manager.post(
        f"{BASE}test-send/", {"recipient_id": foreign.pk}, format="json"
    )
    assert response.status_code == 404


def test_another_events_row_cannot_be_RESENT_a_confirmation_through_this_surface(manager):
    foreign = other_row(email="orders@toke.test")
    response = manager.post(
        f"{BASE}resend-confirmation/", {"recipient_id": foreign.pk}, format="json"
    )
    assert response.status_code == 404


# ── the one action that escapes the fence, and is therefore Owner-only ───────


def test_VOUCHING_IS_REFUSED_TO_A_MANAGER_EVEN_ON_THEIR_OWN_SCREEN(manager):
    """`confirm()` marks every pending row for the SAME ADDRESS, filtered on the email
    alone — deliberately, because confirmation is a property of an address. That reach
    happens inside `confirm()` after the row has been found, so the queryset fence
    cannot stop it. The permission is narrowed instead.
    """
    mine = programme_row(email="programme@toke.test")
    response = manager.post(
        f"{BASE}mark-confirmed/", {"recipient_id": mine.pk}, format="json"
    )
    assert response.status_code == 403
    # And it says what to do instead, rather than just refusing.
    assert "Resend confirmation" in response.data["detail"]

    mine.refresh_from_db()
    assert mine.confirmed_at is None


def test_the_owner_can_vouch(owner):
    mine = programme_row(email="programme@toke.test")
    response = owner.post(
        f"{BASE}mark-confirmed/", {"recipient_id": mine.pk}, format="json"
    )
    assert response.status_code == 200
    mine.refresh_from_db()
    assert mine.confirmed_at is not None


def test_the_route_is_reachable_at_all_which_the_careers_board_learned_the_hard_way(
    owner,
):
    """Overriding an `@action`-decorated method in a subclass loses the routing metadata
    the router reads off it, and the route 405s. That is why the Owner-only narrowing is
    a `check_may_vouch()` hook rather than an override — and this asserts the route
    exists, so a future refactor back to an override fails here instead of in production.
    """
    response = owner.post(f"{BASE}mark-confirmed/", {"recipient_id": 999999},
                          format="json")
    assert response.status_code != 405
