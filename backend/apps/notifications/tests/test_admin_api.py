"""The Email Notifications endpoints. Who may call them, what they refuse, and what the
test-send button is and is not allowed to do.
"""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.notifications.models import NotificationRecipient

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/api/v1/admin/notification-recipients/"


def client_for(user) -> APIClient:
    """A token minted the way the real ceremony mints one — `force_authenticate` would
    skip `AdminJWTAuthentication` and never exercise the audience claim. Same reasoning
    as `apps/core/tests/test_admin_search.py`."""
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(user)['access']}",
        HTTP_CF_CONNECTING_IP="203.0.113.9",
    )
    return api


def confirmed(event="order.paid", email="pack@x.com"):
    """A CONFIRMED external recipient.

    Test-send is refused for an unconfirmed address by design (see
    `test_test_send_is_refused_for_an_unconfirmed_address`), so anything exercising the
    send path needs a row that has already clicked.
    """
    from django.utils import timezone

    return NotificationRecipient.objects.create(
        event=event, email=email, confirmed_at=timezone.now()
    )


def in_role(email, role):
    user = User.objects.create_user(email=email, is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def owner():
    return in_role("owner@toke.test", "Owner")


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# ── who may call it ─────────────────────────────────────────────────────────────────

def test_a_manager_cannot_read_the_list(owner):
    manager = in_role("manager@toke.test", "Manager")
    assert client_for(manager).get(BASE).status_code == 403


def test_a_manager_cannot_add_a_recipient():
    manager = in_role("manager@toke.test", "Manager")
    response = client_for(manager).post(
        BASE, {"event": "order.paid", "email": "me@x.com"}, format="json"
    )
    assert response.status_code == 403
    assert not NotificationRecipient.objects.exists()


def test_the_owner_can_read_the_list(owner):
    assert client_for(owner).get(BASE).status_code == 200


# ── what it refuses ─────────────────────────────────────────────────────────────────

def test_an_unregistered_event_is_refused(owner):
    response = client_for(owner).post(
        BASE, {"event": "made.up", "email": "me@x.com"}, format="json"
    )
    assert response.status_code == 400


def test_a_customer_account_cannot_be_subscribed(owner):
    """THE REASON `validate_user` CHECKS `is_staff`. A Server Function is a public POST
    endpoint and a customer id is not a secret, so without this check every order in the
    shop could be forwarded to an arbitrary customer's inbox."""
    customer = User.objects.create_user(email="shopper@x.com", is_staff=False)
    response = client_for(owner).post(
        BASE, {"event": "order.paid", "user": customer.pk}, format="json"
    )
    assert response.status_code == 400
    assert not NotificationRecipient.objects.exists()


def test_neither_target_is_refused_with_a_sentence(owner):
    """The database constraint would raise IntegrityError — a 500. A screen should get a
    400 it can render.

    THE MESSAGE IS ASSERTED, not just the status. Found on a live server: DRF's
    auto-generated `UniqueTogetherValidator` forces its fields to be required, so this
    came back as "email: This field is required." — telling the operator to fill in the
    field they had correctly left blank, on a form where either half is valid."""
    response = client_for(owner).post(BASE, {"event": "order.paid"}, format="json")
    assert response.status_code == 400
    assert "either a staff member or an email address" in str(response.data)


def test_a_staff_only_body_does_not_demand_an_email(owner):
    """The other half of the same bug: naming a staff member and nothing else is the
    normal way to use this endpoint, and it must not be refused for a missing `email`."""
    response = client_for(owner).post(BASE, {"event": "order.paid", "user": owner.pk},
                                      format="json")
    assert response.status_code == 201, response.data


def test_both_targets_are_refused(owner):
    response = client_for(owner).post(
        BASE, {"event": "order.paid", "user": owner.pk, "email": "me@x.com"},
        format="json",
    )
    assert response.status_code == 400
    assert "not both and not neither" in str(response.data)


def test_a_duplicate_is_refused_with_a_sentence(owner):
    client = client_for(owner)
    client.post(BASE, {"event": "order.paid", "email": "me@x.com"}, format="json")
    response = client.post(BASE, {"event": "order.paid", "email": "ME@x.com"},
                           format="json")
    assert response.status_code == 400
    # The shop's sentence, not the database's. DRF's generated validator answered "The
    # fields event, email must make a unique set", which says nothing to an operator.
    assert "already on this list" in str(response.data)
    assert NotificationRecipient.objects.count() == 1


def test_the_list_cannot_be_edited_in_place(owner):
    """No PUT and no PATCH: editing a row would let one audit entry stand for "this used
    to point at the warehouse and now points at my personal address"."""
    row = NotificationRecipient.objects.create(event="order.paid", email="a@x.com")
    client = client_for(owner)
    for method in (client.put, client.patch):
        response = method(f"{BASE}{row.pk}/", {"email": "b@x.com"}, format="json")
        assert response.status_code == 405


# ── what it does ────────────────────────────────────────────────────────────────────

def test_adding_and_removing_a_recipient(owner):
    client = client_for(owner)
    created = client.post(BASE, {"event": "order.paid", "email": "Pack@X.com"},
                          format="json")
    assert created.status_code == 201
    # Normalised on the way in, so the uniqueness constraint can see collisions.
    assert NotificationRecipient.objects.get().email == "pack@x.com"

    assert client.delete(f"{BASE}{created.data['id']}/").status_code == 204
    assert not NotificationRecipient.objects.exists()


def test_the_event_catalog_is_served_from_the_registry(owner):
    response = client_for(owner).get(f"{BASE}events/")
    assert response.status_code == 200
    codes = {row["code"] for row in response.data}
    assert {"order.paid", "order.awaiting_transfer",
            "inventory.low_stock", "delivery.gig_wallet_low"} <= codes
    assert all(row["label"] and row["description"] for row in response.data)


def test_the_staff_picker_offers_only_active_staff(owner):
    User.objects.create_user(email="shopper@x.com", is_staff=False)
    gone = in_role("gone@toke.test", "Manager")
    gone.is_active = False
    gone.save(update_fields=["is_active"])

    response = client_for(owner).get(f"{BASE}staff-options/")
    emails = {row["email"] for row in response.data}
    assert "owner@toke.test" in emails
    assert "shopper@x.com" not in emails
    assert "gone@toke.test" not in emails


def test_a_deactivated_staff_row_reports_no_address(owner):
    """Shown rather than hidden — a subscription that silently stops is how somebody
    concludes they are still subscribed when they are not."""
    person = in_role("later@toke.test", "Manager")
    NotificationRecipient.objects.create(event="order.paid", user=person)
    person.is_active = False
    person.save(update_fields=["is_active"])

    row = client_for(owner).get(BASE).data[0]
    assert row["address"] == ""
    assert row["is_external"] is False


# ── the test-send button ────────────────────────────────────────────────────────────

def test_test_send_mails_the_stored_row(owner, django_capture_on_commit_callbacks):
    row = confirmed()
    # The enqueue is an on_commit effect, so that a rolled-back request (a failed audit
    # write) cannot leave a sent email behind. No commit, no mail.
    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(owner).post(f"{BASE}test-send/", {"recipient_id": row.pk},
                                          format="json")
    assert response.status_code == 200
    assert response.data["sent_to"] == "pack@x.com"
    assert [m.to for m in mail.outbox] == [["pack@x.com"]]
    # Obviously fake, so a test landing beside real alerts is not acted on.
    assert "TC-000000" in mail.outbox[0].body


def test_test_send_ignores_any_address_in_the_body(owner, django_capture_on_commit_callbacks):
    """THE OPEN-RELAY GUARD. An endpoint that mails an address supplied by the caller
    would send our branded, authenticated mail anywhere a caller named, leaving no
    recipient row behind to show for it."""
    row = confirmed()
    with django_capture_on_commit_callbacks(execute=True):
        client_for(owner).post(
            f"{BASE}test-send/",
            {"recipient_id": row.pk, "email": "attacker@evil.test",
             "to": "attacker@evil.test", "address": "attacker@evil.test"},
            format="json",
        )
    assert [m.to for m in mail.outbox] == [["pack@x.com"]]


def test_test_send_on_a_missing_row_is_a_404(owner):
    response = client_for(owner).post(f"{BASE}test-send/", {"recipient_id": 999999},
                                      format="json")
    assert response.status_code == 404
    assert mail.outbox == []


def test_test_send_on_a_deactivated_account_says_so(owner):
    person = in_role("later@toke.test", "Manager")
    row = NotificationRecipient.objects.create(event="order.paid", user=person)
    person.is_active = False
    person.save(update_fields=["is_active"])

    response = client_for(owner).post(f"{BASE}test-send/", {"recipient_id": row.pk},
                                      format="json")
    assert response.status_code == 400
    assert mail.outbox == []


def test_test_send_is_refused_for_an_unconfirmed_address(owner):
    """Allowing it would put order-shaped content in an inbox that has not agreed to
    receive any — the exact delivery the confirmation gate exists to withhold — and would
    let the Owner satisfy themselves that a mistyped address "works" without the address
    ever having agreed."""
    row = NotificationRecipient.objects.create(event="order.paid", email="pack@x.com")

    response = client_for(owner).post(f"{BASE}test-send/", {"recipient_id": row.pk},
                                      format="json")

    assert response.status_code == 400
    assert "not confirmed" in str(response.data).lower()
    assert mail.outbox == []


def test_adding_an_external_address_mails_it_a_confirmation(
    owner, django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        created = client_for(owner).post(
            BASE, {"event": "order.paid", "email": "pack@x.com"}, format="json"
        )

    assert created.status_code == 201
    assert created.data["is_confirmed"] is False
    assert [m.to for m in mail.outbox] == [["pack@x.com"]]
    assert "Confirm" in mail.outbox[0].subject


def test_adding_a_staff_member_mails_no_confirmation(
    owner, django_capture_on_commit_callbacks,
):
    """Their address is already proven — they accepted an emailed invite at it."""
    with django_capture_on_commit_callbacks(execute=True):
        created = client_for(owner).post(
            BASE, {"event": "order.paid", "user": owner.pk}, format="json"
        )

    assert created.data["is_confirmed"] is True
    assert mail.outbox == []


def test_resend_is_refused_for_an_already_confirmed_address(owner):
    """A second confirmation email to someone already receiving alerts reads as a
    security incident to the person getting it."""
    row = confirmed()
    response = client_for(owner).post(f"{BASE}resend-confirmation/",
                                      {"recipient_id": row.pk}, format="json")
    assert response.status_code == 400


def test_resend_mails_a_pending_address_again(owner, django_capture_on_commit_callbacks):
    row = NotificationRecipient.objects.create(event="order.paid", email="pack@x.com")

    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(owner).post(f"{BASE}resend-confirmation/",
                                          {"recipient_id": row.pk}, format="json")

    assert response.status_code == 200
    assert [m.to for m in mail.outbox] == [["pack@x.com"]]


def test_a_manager_cannot_send_a_test():
    manager = in_role("manager@toke.test", "Manager")
    row = NotificationRecipient.objects.create(event="order.paid", email="pack@x.com")
    response = client_for(manager).post(f"{BASE}test-send/", {"recipient_id": row.pk},
                                        format="json")
    assert response.status_code == 403
    assert mail.outbox == []


# ── the audit trail ─────────────────────────────────────────────────────────────────
#
# Adding a recipient is exactly the kind of act `apps/core/audit.py` calls the "camera"
# case: a person who is already inside, quietly arranging for a copy of every order to
# reach an address of their choosing. The row has to name the address, or the log records
# that something was subscribed without recording what.

def test_adding_a_recipient_is_audited_with_the_address(owner):
    from apps.core.models import AuditLog

    client_for(owner).post(BASE, {"event": "order.paid", "email": "pack@x.com"},
                           format="json")

    row = AuditLog.objects.latest("id")
    assert row.actor_email == "owner@toke.test"
    assert row.action == "create"
    assert row.model_label == "notifications.notificationrecipient"
    assert row.changes["email"] == "pack@x.com"
    assert row.changes["event"] == "order.paid"


def test_removing_a_recipient_is_audited(owner):
    from apps.core.models import AuditLog

    row = NotificationRecipient.objects.create(event="order.paid", email="pack@x.com")
    client_for(owner).delete(f"{BASE}{row.pk}/")

    entry = AuditLog.objects.latest("id")
    assert entry.action == "destroy"
    assert entry.object_id == str(row.pk)


def test_a_test_send_is_distinguishable_from_adding_a_recipient(owner):
    """`resolve_action` prefers the DRF action name over the HTTP verb, so this is
    `test_send` and not a second `create` — the two are different acts and a log that
    conflated them would hide one behind the other."""
    from apps.core.models import AuditLog

    row = confirmed()
    client_for(owner).post(f"{BASE}test-send/", {"recipient_id": row.pk}, format="json")

    assert AuditLog.objects.latest("id").action == "test_send"


def test_a_test_send_never_logs_an_address_from_the_request(owner):
    """FOUND BY READING THE AUDIT TABLE, not by a failing assertion. `changes` is built
    from `request.data` against an allowlist, and the viewset's default allowlist has
    `email` on it — so a junk `email` key on a test-send was recorded as if it were the
    address used, for a send that went to the stored row and never read it.

    An audit row naming a value the action ignored is evidence for something that did not
    happen, in the one table whose whole job is to be believed."""
    from apps.core.models import AuditLog

    row = confirmed()
    client_for(owner).post(
        f"{BASE}test-send/",
        {"recipient_id": row.pk, "email": "attacker@evil.test"},
        format="json",
    )

    entry = AuditLog.objects.latest("id")
    assert entry.action == "test_send"
    assert entry.changes == {"recipient_id": row.pk}
    assert "attacker@evil.test" not in str(entry.changes)
