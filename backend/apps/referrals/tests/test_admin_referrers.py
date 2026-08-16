"""Blocking a referrer, and moving a balance by hand.

The two admin actions with no customer-visible receipt: nobody is emailed when they are
blocked, and nobody is emailed when ₦2,500 leaves their balance. What stops those being
silent is the reason each one forces somebody to type, plus the audit row — which is why
several tests here are about the refusals rather than the happy path.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.referrals.models import ReferralAdjustment
from apps.core.models import Currency
from apps.referrals.services import (
    ReferralError,
    accrue_for_order,
    add_adjustment,
    attribution_code_for_order,
    balances,
    request_payout,
    save_payout_method,
    set_referrer_blocked,
)
from apps.referrals.tests.factories import customer, make_order, ngn, referrer

pytestmark = pytest.mark.django_db

REFERRERS = "/api/v1/admin/referrers/"


def staff(django_user_model, role: str = "Owner"):
    user = django_user_model.objects.create_user(
        email=f"{role.lower()}-ref@toke.test", password=None, is_staff=True,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


def admin_client(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(user)['access']}")
    return client


def available(user, code: str = "NGN") -> Decimal:
    wallet = next((w for w in balances(user) if w.currency.code == code), None)
    return wallet.available if wallet else Decimal("0.00")


def earn(django_user_model, profile, subtotal="300000.00"):
    from apps.referrals.models import Commission

    buyer = customer(django_user_model, "buyer-ref@x.com")
    order = make_order(user=buyer, subtotal=subtotal, referral_code=profile.code)
    commission = accrue_for_order(order)
    Commission.objects.filter(pk=commission.pk).update(status="available")
    return commission


# --- blocking -------------------------------------------------------------------------


def test_blocking_stops_new_earnings_without_touching_money_already_earned(
    django_user_model,
):
    """THE WHOLE POINT OF THE RESTRAINT. A block is an abuse response, not a
    confiscation: taking earned money back is an adjustment, which forces a reason and
    leaves a signed row. A block that silently zeroed a balance would be the same
    destructive act with no audit trail and no way back."""
    ref_user, profile = referrer(django_user_model)
    earn(django_user_model, profile)
    assert available(ref_user) == Decimal("30000.00")

    set_referrer_blocked(ref_user, blocked=True, reason="Ordering through their own link",
                         staff_user=staff(django_user_model))

    profile.refresh_from_db()
    assert profile.is_blocked
    assert available(ref_user) == Decimal("30000.00"), "earned money is untouched"


def test_a_blocked_code_earns_nothing_on_a_NEW_order(django_user_model):
    """Refusal happens at CHECKOUT, in `attribution_code_for_order`, which is the only
    place that decides whether an order carries a code at all. Asserted here from the
    admin action's side so the two halves cannot drift apart silently."""
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "later-buyer@x.com")
    assert attribution_code_for_order(profile.code, buyer) == profile.code

    set_referrer_blocked(ref_user, blocked=True, reason="abuse",
                         staff_user=staff(django_user_model))

    assert attribution_code_for_order(profile.code, buyer) == "", (
        "a blocked referrer's code must not be stamped on a new order"
    )


def test_an_order_already_placed_before_the_block_still_pays(django_user_model):
    """THE WINDOW, asserted so nobody 'fixes' it by accident. Accrual does NOT re-check
    the block: it runs in the payment path against a code already stamped at placement.

    So an order placed while the referrer was in good standing and paid an hour after
    they were blocked still earns. That is the right answer — the sale was genuinely
    referred, and the alternative is confiscating a commission for a customer's
    unrelated purchase. Taking that money back, if it is warranted, is an adjustment
    with a reason attached.
    """
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "already-placed@x.com")
    order = make_order(user=buyer, subtotal="100000.00", referral_code=profile.code)

    set_referrer_blocked(ref_user, blocked=True, reason="abuse",
                         staff_user=staff(django_user_model))

    assert accrue_for_order(order) is not None


def test_blocking_requires_a_reason_but_unblocking_does_not(django_user_model):
    """"Why is this person blocked" is asked months later by somebody else. Unblocking
    restores the default and needs no justification."""
    ref_user, _ = referrer(django_user_model)
    boss = staff(django_user_model)

    with pytest.raises(ReferralError) as exc:
        set_referrer_blocked(ref_user, blocked=True, reason="   ", staff_user=boss)
    assert exc.value.code == "reason_required"

    set_referrer_blocked(ref_user, blocked=True, reason="Self-referral ring", staff_user=boss)
    profile = set_referrer_blocked(ref_user, blocked=False, reason="", staff_user=boss)
    assert not profile.is_blocked
    assert profile.blocked_reason == "", "a stale reason on an active referrer misleads"


def test_blocking_leaves_an_open_payout_for_a_human_to_decide(django_user_model):
    """Deliberate: auto-rejecting here would bury a money decision inside an abuse
    action. The request stays in the queue and one click releases or refuses it."""
    ref_user, profile = referrer(django_user_model)
    earn(django_user_model, profile)
    save_payout_method(ref_user, currency=ngn(), bank_name="GTBank",
                       account_name="A O", account_number="0123456789")
    payout = request_payout(ref_user, "NGN", accept_terms=True)

    set_referrer_blocked(ref_user, blocked=True, reason="abuse",
                         staff_user=staff(django_user_model))

    payout.refresh_from_db()
    assert payout.status == "requested"


def test_block_and_unblock_over_http(django_user_model):
    ref_user, _ = referrer(django_user_model)
    client = admin_client(staff(django_user_model))

    blocked = client.post(f"{REFERRERS}{ref_user.pk}/block/",
                          {"blocked": True, "reason": "Self-referral ring"}, format="json")
    assert blocked.status_code == 200
    assert blocked.json()["is_blocked"] is True
    assert blocked.json()["blocked_reason"] == "Self-referral ring"

    unblocked = client.post(f"{REFERRERS}{ref_user.pk}/block/", {"blocked": False},
                            format="json")
    assert unblocked.status_code == 200
    assert unblocked.json()["is_blocked"] is False


def test_blocking_without_a_reason_is_refused_over_http(django_user_model):
    ref_user, _ = referrer(django_user_model)
    client = admin_client(staff(django_user_model))
    response = client.post(f"{REFERRERS}{ref_user.pk}/block/",
                           {"blocked": True, "reason": ""}, format="json")
    assert response.status_code == 400
    assert response.json()["error"] == "reason_required"


# --- manual adjustments ----------------------------------------------------------------


def test_a_negative_adjustment_moves_the_balance_down(django_user_model):
    ref_user, profile = referrer(django_user_model)
    earn(django_user_model, profile)

    add_adjustment(ref_user, currency=ngn(), amount=Decimal("-2500.00"), kind="clawback",
                   reason="Refund landed after the payout went",
                   staff_user=staff(django_user_model))

    assert available(ref_user) == Decimal("27500.00")


def test_an_adjustment_may_take_a_balance_negative(django_user_model):
    """NOT clamped, on purpose. The balance is allowed below zero — that is what a
    clawback after a payout does — and `request_payout` already refuses while it is.
    Clamping would silently forgive the remainder, the one direction of this bug that
    costs the shop money."""
    ref_user, _ = referrer(django_user_model)

    add_adjustment(ref_user, currency=ngn(), amount=Decimal("-5000.00"), kind="clawback",
                   reason="Chargeback on a paid-out order",
                   staff_user=staff(django_user_model))

    assert available(ref_user) == Decimal("-5000.00")


def test_an_adjustment_of_zero_is_refused(django_user_model):
    """A row that changes nothing but implies something happened."""
    ref_user, _ = referrer(django_user_model)
    with pytest.raises(ReferralError) as exc:
        add_adjustment(ref_user, currency=ngn(), amount=Decimal("0.00"), kind="correction",
                       reason="oops", staff_user=staff(django_user_model))
    assert exc.value.code == "amount_required"


def test_an_adjustment_without_a_reason_is_refused(django_user_model):
    ref_user, _ = referrer(django_user_model)
    with pytest.raises(ReferralError) as exc:
        add_adjustment(ref_user, currency=ngn(), amount=Decimal("100.00"), kind="bonus",
                       reason="  ", staff_user=staff(django_user_model))
    assert exc.value.code == "reason_required"


def test_crediting_a_currency_the_shop_cannot_pay_out_is_refused(django_user_model):
    """Money the referrer can see and never receive. Every currency with a configured
    threshold is payable; one without cannot be withdrawn at all."""
    from django.test import override_settings

    ref_user, _ = referrer(django_user_model)
    with override_settings(REFERRAL_PAYOUT_THRESHOLDS={"NGN": Decimal("20000.00")}):
        with pytest.raises(ReferralError) as exc:
            gbp = Currency.objects.get(code="GBP")
            add_adjustment(ref_user, currency=gbp, amount=Decimal("50.00"), kind="bonus",
                           reason="₦200k Club retainer",
                           staff_user=staff(django_user_model))
    assert exc.value.code == "currency_not_payable"


def test_writing_an_adjustment_over_http_records_who_and_why(django_user_model):
    ref_user, _ = referrer(django_user_model)
    boss = staff(django_user_model)
    client = admin_client(boss)

    response = client.post(
        f"{REFERRERS}{ref_user.pk}/adjust/",
        {"currency": "NGN", "amount": "-2500.00", "kind": "clawback",
         "reason": "Refund landed after the payout went."}, format="json",
    )

    assert response.status_code == 201
    row = ReferralAdjustment.objects.get(pk=response.json()["id"])
    assert row.amount == Decimal("-2500.00")
    assert row.created_by_id == boss.pk
    assert row.reason == "Refund landed after the payout went."


def test_an_unsettled_adjustment_is_marked_as_still_moving_the_balance(django_user_model):
    """A settled adjustment is history; an unsettled one is changing what the referrer
    can request right now, and the screen has to tell them apart."""
    ref_user, _ = referrer(django_user_model)
    add_adjustment(ref_user, currency=ngn(), amount=Decimal("500.00"), kind="bonus",
                   reason="Goodwill", staff_user=staff(django_user_model))
    client = admin_client(staff(django_user_model, "Manager"))

    rows = client.get(f"{REFERRERS}{ref_user.pk}/adjustments/").json()["results"]

    assert len(rows) == 1
    assert rows[0]["settled"] is False
    assert rows[0]["kind"] == "bonus"


# --- the list ---------------------------------------------------------------------------


def test_the_referrer_list_shows_balances_and_puts_blocked_people_first(django_user_model):
    ref_user, profile = referrer(django_user_model)
    earn(django_user_model, profile)
    blocked_user, _ = referrer(django_user_model, email="blocked@x.com")
    set_referrer_blocked(blocked_user, blocked=True, reason="abuse",
                         staff_user=staff(django_user_model))
    client = admin_client(staff(django_user_model, "Support"))

    rows = client.get(REFERRERS).json()["results"]

    assert rows[0]["email"] == "blocked@x.com", "blocked first — that is why you open this"
    earner = next(r for r in rows if r["email"] == ref_user.email)
    ngn_balance = next(b for b in earner["balances"] if b["currency"] == "NGN")
    assert ngn_balance["available"] == "30000.00"


def test_the_referrer_list_is_searchable_by_code_and_email(django_user_model):
    ref_user, profile = referrer(django_user_model)
    referrer(django_user_model, email="someone-else@x.com")
    client = admin_client(staff(django_user_model))

    by_code = client.get(f"{REFERRERS}?search={profile.code}").json()["results"]
    assert [r["email"] for r in by_code] == [ref_user.email]

    by_email = client.get(f"{REFERRERS}?search=someone-else").json()["results"]
    assert [r["email"] for r in by_email] == ["someone-else@x.com"]
