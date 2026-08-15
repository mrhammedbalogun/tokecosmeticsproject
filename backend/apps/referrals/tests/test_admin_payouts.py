"""The admin payout queue, over real HTTP.

`test_admin_role_matrix.py` owns who may reach these endpoints. This file owns what they
DO — and, mostly, the edge cases around the money: what a rejection releases, what a
bounced transfer can be walked back to, and the three states that used to have no way out
before this queue existed.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.referrals.models import Commission, PayoutRequest
from apps.referrals.services import (
    accrue_for_order,
    balances,
    fraud_flags,
    request_payout,
    save_payout_method,
)
from apps.referrals.tests.factories import customer, make_order, ngn, referrer

pytestmark = pytest.mark.django_db

QUEUE = "/api/v1/admin/referral-payouts/"


def staff(django_user_model, role: str = "Owner"):
    user = django_user_model.objects.create_user(
        email=f"{role.lower()}-payouts@toke.test", password=None, is_staff=True,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


def admin_client(user) -> APIClient:
    """Minted the way the real ceremony mints it, so `AdminJWTAuthentication`'s audience
    claim is actually exercised — same reasoning as `test_admin_role_matrix._admin_client`."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(user)['access']}")
    return client


def earn(django_user_model, profile, subtotal: str, *, buyer_email="buyer@x.com"):
    """One available commission, the state a payout can actually be requested from."""
    buyer = customer(django_user_model, buyer_email)
    order = make_order(user=buyer, subtotal=subtotal, referral_code=profile.code)
    commission = accrue_for_order(order)
    Commission.objects.filter(pk=commission.pk).update(status="available")
    commission.refresh_from_db()
    return commission


def open_request(django_user_model, subtotal="300000.00", *, tag=""):
    """A referrer with a bank account on file and one payout awaiting review.

    `tag` keeps the emails unique when a test needs more than one referrer — both the
    referrer and the buyer factories default to fixed addresses, and a second call
    without it hits the unique-email constraint.
    """
    ref_user, profile = referrer(django_user_model, email=f"ref{tag}@x.com")
    earn(django_user_model, profile, subtotal, buyer_email=f"buyer{tag}@x.com")
    save_payout_method(
        ref_user, currency=ngn(), bank_name="GTBank", account_name="AMINA OKORO",
        account_number="0123456789",
    )
    payout = request_payout(ref_user, "NGN", accept_terms=True)
    return ref_user, profile, payout


def available(user) -> Decimal:
    return next(w for w in balances(user) if w.currency.code == "NGN").available


# --- reading the queue ----------------------------------------------------------------


def test_the_queue_publishes_the_full_account_number_and_the_flags(django_user_model):
    """The one screen that unmasks a bank account, because a person cannot transfer money
    to `•••• 6789`. Also the fraud flags, which is the whole reason a human looks."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    body = client.get(QUEUE).json()
    row = body["results"][0]

    assert row["id"] == payout.pk
    assert row["account_number"] == "0123456789", "staff must see what to type into the bank"
    assert row["bank_name"] == "GTBank"
    assert row["account_name"] == "AMINA OKORO"
    assert row["status"] == "requested"
    assert row["commission_count"] == 1
    assert row["days_open"] == 0
    assert isinstance(row["flags"], list)


def test_days_open_is_only_reported_while_the_customer_is_still_waiting(django_user_model):
    """It is the number the queue sorts and shouts on. Once decided it means nothing, and
    a stale "43 days" beside a paid row reads as a problem that is not there."""
    _, _, payout = open_request(django_user_model)
    PayoutRequest.objects.filter(pk=payout.pk).update(
        created_at=timezone.now() - timedelta(days=9)
    )
    client = admin_client(staff(django_user_model))

    assert client.get(QUEUE).json()["results"][0]["days_open"] == 9

    client.post(f"{QUEUE}{payout.pk}/mark-paid/", {"reference": "TRF-1"}, format="json")
    assert client.get(QUEUE).json()["results"][0]["days_open"] is None


def test_the_commissions_behind_a_payout_are_listed(django_user_model):
    """What the reviewer is actually approving. Most fraud is visible in the orders, not
    in the request."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    rows = client.get(f"{QUEUE}{payout.pk}/commissions/").json()
    assert len(rows) == 1
    assert rows[0]["amount"] == "30000.00"
    assert rows[0]["order_number"]


def test_work_sorts_above_history_and_the_longest_wait_sorts_first(django_user_model):
    """THE BUG THIS PINS: ordering by the status column sorts it alphabetically —
    approved, paid, rejected, requested — which puts the only rows needing a human at the
    very bottom. Found by looking at the screen, so the test exists to keep it found.
    """
    _, _, old_open = open_request(django_user_model, tag="-old")
    PayoutRequest.objects.filter(pk=old_open.pk).update(
        created_at=timezone.now() - timedelta(days=20)
    )
    _, _, recent_open = open_request(django_user_model, tag="-recent")
    _, _, settled = open_request(django_user_model, tag="-settled")
    PayoutRequest.objects.filter(pk=settled.pk).update(status="paid")

    client = admin_client(staff(django_user_model))
    order = [r["id"] for r in client.get(QUEUE).json()["results"]]

    assert order == [old_open.pk, recent_open.pk, settled.pk], (
        "awaiting review first, oldest of those first, settled history last"
    )


# --- the basic flow Hammed asked for: requested -> paid ---------------------------------


def test_a_payout_can_go_straight_from_requested_to_paid(django_user_model):
    """The one-person-shop path. Approve exists for shops where the checker and the payer
    are different people; requiring it here would be ceremony with no second pair of eyes
    behind it."""
    ref_user, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    response = client.post(
        f"{QUEUE}{payout.pk}/mark-paid/", {"reference": "GTB/2026/0042"}, format="json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert response.json()["reference"] == "GTB/2026/0042"
    payout.refresh_from_db()
    assert payout.paid_at is not None
    assert payout.decided_by is not None, "paying decides it, even with no approve step"


def test_marking_paid_without_a_bank_reference_is_refused(django_user_model):
    """The reference is the only artefact that answers "I never got it"."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    response = client.post(f"{QUEUE}{payout.pk}/mark-paid/", {"reference": ""}, format="json")

    assert response.status_code == 400
    payout.refresh_from_db()
    assert payout.status == "requested"


def test_two_staff_deciding_the_same_row_get_a_conflict_not_a_double_payment(
    django_user_model,
):
    """Two people working the queue on the last day of the month is the normal case, not
    the exotic one. The second click must be refused by code rather than by luck."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    first = client.post(f"{QUEUE}{payout.pk}/mark-paid/", {"reference": "TRF-1"}, format="json")
    second = client.post(f"{QUEUE}{payout.pk}/mark-paid/", {"reference": "TRF-2"}, format="json")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"] == "payout_not_open"
    payout.refresh_from_db()
    assert payout.reference == "TRF-1", "the second attempt must not overwrite the first"


# --- rejection, and the ways back -------------------------------------------------------


def test_rejecting_releases_the_money_back_to_the_referrer(django_user_model):
    """The property that matters: a refused request must not strand a balance. The
    customer's money goes back to `available` and they can ask again."""
    ref_user, _, payout = open_request(django_user_model)
    assert available(ref_user) == Decimal("0.00"), "claimed by the open request"
    client = admin_client(staff(django_user_model))

    response = client.post(
        f"{QUEUE}{payout.pk}/reject/",
        {"customer_message": "We could not match this account name."}, format="json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert available(ref_user) == Decimal("30000.00"), "released, not stranded"


def test_rejecting_requires_a_message_the_customer_will_see(django_user_model):
    """A rejection with no reason generates a support ticket every single time, and the
    reviewer is the only person who knows why."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))

    response = client.post(f"{QUEUE}{payout.pk}/reject/", {}, format="json")

    assert response.status_code == 400
    assert "customer_message" in response.json()


def test_an_approved_payout_can_still_be_rejected(django_user_model):
    """THE BOUNCED-TRANSFER CASE. Approval only means "we mean to send this"; the money
    leaves by hand days later. Before this, an approved row could only ever go to `paid`,
    so a transfer the bank refused had no way back except hand-written SQL."""
    ref_user, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))
    assert client.post(f"{QUEUE}{payout.pk}/approve/", {}, format="json").status_code == 200

    response = client.post(
        f"{QUEUE}{payout.pk}/reject/",
        {"customer_message": "The transfer was returned by your bank."}, format="json",
    )

    assert response.status_code == 200
    assert available(ref_user) == Decimal("30000.00")


def test_a_paid_payout_cannot_be_rejected(django_user_model):
    """Money has left. Reversing that is a clawback with a reason attached, not a status
    change — otherwise rejection becomes a button that silently re-credits cash the shop
    already sent."""
    _, _, payout = open_request(django_user_model)
    client = admin_client(staff(django_user_model))
    client.post(f"{QUEUE}{payout.pk}/mark-paid/", {"reference": "TRF-1"}, format="json")

    response = client.post(
        f"{QUEUE}{payout.pk}/reject/", {"customer_message": "oops"}, format="json",
    )

    assert response.status_code == 409


# --- the account-takeover flag ----------------------------------------------------------


def test_changing_the_bank_account_after_requesting_raises_a_flag(django_user_model):
    """The hijack shape: take the account over, repoint the bank details, wait for payday.

    `mark_payout_paid` pays the SNAPSHOT, so the money does not follow the change — this
    flag is the other half, putting the change in front of a human. The innocent version
    (customer fixed their own typo) looks identical in the data, which is exactly why it
    is a flag for a person and not an automatic block.
    """
    ref_user, _, payout = open_request(django_user_model)
    save_payout_method(
        ref_user, currency=ngn(), bank_name="Kuda", account_name="AMINA OKORO",
        account_number="9999999999",
    )

    flags = fraud_flags(PayoutRequest.objects.get(pk=payout.pk))

    assert any("CHANGED after this request" in f for f in flags), flags
    client = admin_client(staff(django_user_model))
    row = client.get(QUEUE).json()["results"][0]
    assert row["account_number"] == "0123456789", "still the snapshot, not the new account"


def test_an_unchanged_account_raises_no_flag(django_user_model):
    """The flag has to be quiet in the normal case or nobody will read it."""
    _, _, payout = open_request(django_user_model)
    assert not any("CHANGED" in f for f in fraud_flags(PayoutRequest.objects.get(pk=payout.pk)))


# --- the two background guards ----------------------------------------------------------


def test_a_forgotten_payout_request_is_alerted_on(django_user_model):
    """The failure this programme is most likely to actually suffer. Everything else is
    automatic; this is the one step waiting on a human remembering, and the customer's
    screen says "we're reviewing it" whether they asked yesterday or in March."""
    from apps.referrals.tasks import PAYOUT_AGING_DAYS, _alert_on_aging_payouts

    _, _, payout = open_request(django_user_model)
    assert _alert_on_aging_payouts() == 0

    PayoutRequest.objects.filter(pk=payout.pk).update(
        created_at=timezone.now() - timedelta(days=PAYOUT_AGING_DAYS + 1)
    )
    assert _alert_on_aging_payouts() == 1

    PayoutRequest.objects.filter(pk=payout.pk).update(status="paid")
    assert _alert_on_aging_payouts() == 0, "only unanswered requests are anyone's problem"


def test_account_deletion_waits_for_an_open_payout(django_user_model):
    """Anonymisation redacts payout snapshots to the last four digits. Doing that to a
    request still waiting to be paid would leave the shop owing a debt it can no longer
    transfer, to a customer whose email is now a sentinel. Deferred, not refused: the task
    runs daily and completes once the payout is settled or rejected.
    """
    from apps.accounts.tasks import _anonymize_one

    ref_user, _, payout = open_request(django_user_model)
    ref_user.is_active = False
    ref_user.deletion_requested_at = timezone.now() - timedelta(days=40)
    ref_user.save(update_fields=["is_active", "deletion_requested_at"])

    assert _anonymize_one(ref_user.pk) is False, "money owed blocks the scrub"
    ref_user.refresh_from_db()
    assert not ref_user.email.startswith("deleted-")

    PayoutRequest.objects.filter(pk=payout.pk).update(status="paid")
    assert _anonymize_one(ref_user.pk) is True, "settled — deletion proceeds"
