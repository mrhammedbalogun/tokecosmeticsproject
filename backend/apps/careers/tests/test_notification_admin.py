"""The careers Notifications tab: what it can reach, and — mostly — what it cannot.

`order.paid` has nine real recipients on production, several of them bare external
addresses. This file exists to prove that a holder of `careers.notifications.manage`
cannot read, write, delete or confirm any of them. Every test below that names another
event is testing the fence, not the feature.
"""
import pytest
from rest_framework.test import APIClient

from apps.careers.emails import EVENT_APPLICATION_RECEIVED
from apps.catalog.tests.factories_admin import staff_user
from apps.notifications.models import NotificationRecipient

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/careers/notifications/"
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


def careers_row(**kwargs):
    return NotificationRecipient.objects.create(
        event=EVENT_APPLICATION_RECEIVED, **kwargs
    )


def other_row(**kwargs):
    """A row this viewset must never touch."""
    return NotificationRecipient.objects.create(event=OTHER_EVENT, **kwargs)


# --- the ordinary job -------------------------------------------------------


def test_a_manager_can_add_a_bare_address_and_it_lands_on_the_careers_event(manager):
    response = manager.post(BASE, {"email": "Careers@Toke.TEST"}, format="json")
    assert response.status_code == 201, response.data

    row = NotificationRecipient.objects.get()
    assert row.event == EVENT_APPLICATION_RECEIVED
    # Lowercased by the model, so the unique index can see a collision.
    assert row.email == "careers@toke.test"
    # An external address receives NOTHING until it confirms.
    assert row.confirmed_at is None
    assert row.is_confirmed is False


def test_a_staff_member_can_be_added_and_is_confirmed_by_construction(manager):
    colleague = staff_user(email="hiring@toke.test", role="Support")
    response = manager.post(BASE, {"user": colleague.pk}, format="json")
    assert response.status_code == 201, response.data
    assert NotificationRecipient.objects.get().is_confirmed is True


def test_the_list_shows_only_careers_rows(manager):
    careers_row(email="wanted@toke.test")
    other_row(email="orders@toke.test")

    rows = manager.get(BASE).data
    assert [r["email"] for r in rows] == ["wanted@toke.test"]


def test_a_recipient_can_be_removed(manager):
    row = careers_row(email="gone@toke.test")
    assert manager.delete(f"{BASE}{row.pk}/").status_code == 204
    assert not NotificationRecipient.objects.filter(pk=row.pk).exists()


def test_a_duplicate_is_refused_with_a_sentence(manager):
    careers_row(email="dupe@toke.test")
    response = manager.post(BASE, {"email": "dupe@toke.test"}, format="json")
    assert response.status_code == 400
    assert "already on this list" in str(response.data)


def test_neither_or_both_of_the_two_row_kinds_is_refused(manager):
    colleague = staff_user(email="both@toke.test", role="Support")
    assert manager.post(BASE, {}, format="json").status_code == 400
    assert manager.post(
        BASE, {"user": colleague.pk, "email": "x@toke.test"}, format="json"
    ).status_code == 400


def test_a_customer_account_cannot_be_subscribed(manager):
    """The picker offers staff; the endpoint is a POST and the pk is whatever was sent."""
    from django.contrib.auth import get_user_model

    customer = get_user_model().objects.create_user(
        email="shopper@example.com", password="Str0ng!pass9"
    )
    response = manager.post(BASE, {"user": customer.pk}, format="json")
    assert response.status_code == 400
    assert "active staff member" in str(response.data)


# --- THE FENCE --------------------------------------------------------------


def test_the_event_cannot_be_chosen_by_the_client(manager):
    """`event` is read-only, so a body naming another one is ignored, not honoured."""
    response = manager.post(
        BASE, {"email": "sneaky@toke.test", "event": OTHER_EVENT}, format="json"
    )
    assert response.status_code == 201
    assert NotificationRecipient.objects.get().event == EVENT_APPLICATION_RECEIVED


def test_a_row_for_another_event_is_invisible_and_undeletable(manager):
    row = other_row(email="orders@toke.test")

    # 404 and not 403: the endpoint must not reveal which ids belong to other events.
    assert manager.get(f"{BASE}{row.pk}/").status_code == 404
    assert manager.delete(f"{BASE}{row.pk}/").status_code == 404
    assert NotificationRecipient.objects.filter(pk=row.pk).exists()


def test_the_body_addressed_actions_cannot_reach_another_events_row(manager):
    """THE ESCALATION THIS FILE EXISTS FOR.

    The actions take a `recipient_id` from the BODY. Before the shared mixin they looked
    it up through `NotificationRecipient.objects` — fine on the unfiltered Owner-only
    viewset, and a way through the fence here. Each one must resolve through the scoped
    queryset instead.
    """
    row = other_row(email="orders@toke.test")
    for path in ("resend-confirmation", "mark-confirmed", "test-send"):
        response = manager.post(f"{BASE}{path}/", {"recipient_id": row.pk}, format="json")
        assert response.status_code in (403, 404), (
            f"{path} reached a row for {OTHER_EVENT}: {response.status_code}"
        )
    row.refresh_from_db()
    assert row.confirmed_at is None, "an out-of-scope row was confirmed"


def test_vouching_for_an_address_stays_owner_only(manager, owner):
    """`confirm()` matches on the ADDRESS, not the event, so it reaches rows this
    viewset cannot see. The queryset fence cannot stop that — the elevation does."""
    row = careers_row(email="pending@toke.test")

    refused = manager.post(f"{BASE}mark-confirmed/", {"recipient_id": row.pk},
                           format="json")
    assert refused.status_code == 403
    assert "Only the Owner" in str(refused.data)
    row.refresh_from_db()
    assert row.confirmed_at is None

    allowed = owner.post(f"{BASE}mark-confirmed/", {"recipient_id": row.pk},
                         format="json")
    assert allowed.status_code == 200
    row.refresh_from_db()
    assert row.confirmed_at is not None


def test_a_manager_may_still_resend_a_confirmation(manager):
    """The controls a Manager keeps: they can ask the address to confirm itself."""
    row = careers_row(email="pending@toke.test")
    response = manager.post(f"{BASE}resend-confirmation/", {"recipient_id": row.pk},
                            format="json")
    assert response.status_code == 200
    assert response.data["sent_to"] == "pending@toke.test"


def test_resend_is_refused_for_a_staff_row_and_for_a_confirmed_one(manager):
    colleague = staff_user(email="colleague@toke.test", role="Support")
    staff_row = careers_row(user=colleague)
    assert manager.post(f"{BASE}resend-confirmation/", {"recipient_id": staff_row.pk},
                        format="json").status_code == 400

    from django.utils import timezone

    done = careers_row(email="done@toke.test", confirmed_at=timezone.now())
    assert manager.post(f"{BASE}resend-confirmation/", {"recipient_id": done.pk},
                        format="json").status_code == 400


def test_a_test_send_is_refused_until_the_address_has_confirmed(manager):
    """An unconfirmed inbox gets its confirmation link and nothing else."""
    row = careers_row(email="pending@toke.test")
    response = manager.post(f"{BASE}test-send/", {"recipient_id": row.pk}, format="json")
    assert response.status_code == 400
    assert "has not confirmed" in str(response.data)


def test_a_test_send_goes_to_the_stored_address_never_one_in_the_body(manager):
    from django.utils import timezone

    row = careers_row(email="real@toke.test", confirmed_at=timezone.now())
    response = manager.post(
        f"{BASE}test-send/",
        {"recipient_id": row.pk, "email": "attacker@evil.test"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["sent_to"] == "real@toke.test"


def test_a_deactivated_staff_row_is_shown_rather_than_silently_dropped(manager):
    """A subscription that stops without saying so is the bug this whole feature ends."""
    colleague = staff_user(email="left@toke.test", role="Support")
    careers_row(user=colleague)
    colleague.is_active = False
    colleague.save(update_fields=["is_active"])

    rows = manager.get(BASE).data
    assert len(rows) == 1
    assert rows[0]["address"] == ""   # resolves to nobody — the screen warns on this


def test_the_staff_picker_offers_only_active_staff(manager):
    staff_user(email="active@toke.test", role="Support")
    gone = staff_user(email="gone@toke.test", role="Support")
    gone.is_active = False
    gone.save(update_fields=["is_active"])

    offered = {row["email"] for row in manager.get(f"{BASE}staff-options/").data}
    assert "active@toke.test" in offered
    assert "gone@toke.test" not in offered


def test_adding_a_recipient_is_audited_with_who_did_it(manager):
    from apps.core.models import AuditLog

    manager.post(BASE, {"email": "audited@toke.test"}, format="json")
    row = AuditLog.objects.filter(model_label="notifications.notificationrecipient").last()
    assert row is not None
    assert row.action == "create"
    assert row.actor_email == "manager@toke.test"
    # `event` is not client-supplied here, so it is not in the allowlist; the address is
    # the whole content of the decision.
    assert row.changes.get("email") == "audited@toke.test"
