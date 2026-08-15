"""The HTTP surface: what a customer can see, and what they must never see."""
from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.referrals.models import Commission, PayoutMethod
from apps.referrals.services import accrue_for_order, save_payout_method
from apps.referrals.tests.factories import customer, make_order, ngn, referrer

OVERVIEW = "/api/v1/me/referrals/"
COMMISSIONS = "/api/v1/me/referrals/commissions/"
METHODS = "/api/v1/me/referrals/payout-methods/"
PAYOUTS = "/api/v1/me/referrals/payouts/"


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_every_referral_endpoint_requires_auth():
    anon = APIClient()
    for url in (OVERVIEW, COMMISSIONS, METHODS, PAYOUTS):
        assert anon.get(url).status_code in (401, 403), url


@pytest.mark.django_db
def test_the_overview_mints_a_code_on_first_visit(django_user_model):
    """Auto-enrolment, in one assertion: a customer who has never heard of the
    programme opens the page and already has a working link."""
    user = customer(django_user_model, "amina@x.com", first_name="Amina")

    body = _client(user).get(OVERVIEW).json()

    assert body["code"].startswith("AMINA")
    assert body["share_url"].endswith(f"?ref={body['code']}")
    assert body["commission_percent"] == "10.00"
    assert body["cookie_days"] == 30
    assert body["hold_days"] == 60
    assert body["wallets"] == []
    assert body["has_payout_method"] is False


@pytest.mark.django_db
def test_the_overview_publishes_wallets_with_display_strings(django_user_model):
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, subtotal="300000.00", referral_code=profile.code)
    commission = accrue_for_order(order)
    Commission.objects.filter(pk=commission.pk).update(status="available")

    body = _client(ref_user).get(OVERVIEW).json()
    wallet = body["wallets"][0]

    assert wallet["currency"] == "NGN"
    assert wallet["available"] == "30000.00"
    # format_money, not a client-side template: currency precision has one source of truth.
    assert wallet["available_display"] == "₦30,000.00"
    assert wallet["threshold_display"] == "₦20,000.00"
    assert wallet["can_request"] is True
    assert wallet["remaining_to_threshold_display"] == "₦0.00"
    assert body["referred_customers"] == 1


@pytest.mark.django_db
def test_the_activity_feed_names_the_buyer_only_by_first_name_and_initial(django_user_model):
    """A referrer is entitled to know their link worked. They are not entitled to a
    customer's email address."""
    ref_user, profile = referrer(django_user_model)
    buyer = customer(
        django_user_model, "someone.private@x.com", first_name="Chidi", last_name="Okafor"
    )
    order = make_order(user=buyer, referral_code=profile.code)
    accrue_for_order(order)

    body = _client(ref_user).get(COMMISSIONS).json()
    row = body["results"][0]

    assert row["customer_label"] == "Chidi O."
    assert row["status_label"] == "In holding period"
    assert row["order_number"] == order.number
    assert "someone.private@x.com" not in str(body)


@pytest.mark.django_db
def test_a_referrer_sees_only_their_own_commissions(django_user_model):
    _, mine = referrer(django_user_model, "me@x.com")
    other_user, theirs = referrer(django_user_model, "other@x.com")
    buyer = customer(django_user_model, "buyer@x.com")
    accrue_for_order(make_order(user=buyer, referral_code=theirs.code))

    body = _client(django_user_model.objects.get(email="me@x.com")).get(COMMISSIONS).json()
    assert body["count"] == 0
    assert _client(other_user).get(COMMISSIONS).json()["count"] == 1


@pytest.mark.django_db
def test_saving_a_payout_method_never_reads_the_account_number_back(django_user_model):
    user = customer(django_user_model, "a@x.com")
    c = _client(user)

    r = c.put(METHODS, {
        "currency": "NGN", "bank_name": "GTBank",
        "account_name": "AMINA OKORO", "account_number": "0123 456 789",
    }, format="json")

    assert r.status_code == 200
    assert r.json()["account_number_masked"] == "•••• 6789"
    assert "account_number" not in r.json()
    # Spaces stripped on the way in, so the stored value is what a bank would accept.
    assert PayoutMethod.objects.get(user=user).account_number == "0123456789"

    listed = c.get(METHODS).json()
    assert listed[0]["account_number_masked"] == "•••• 6789"
    assert "0123456789" not in str(listed)


@pytest.mark.django_db
def test_a_payout_method_is_refused_for_a_currency_that_cannot_be_paid_out(
    django_user_model, settings
):
    settings.REFERRAL_PAYOUT_THRESHOLDS = {"NGN": Decimal("20000.00")}
    user = customer(django_user_model, "a@x.com")

    r = _client(user).put(METHODS, {
        "currency": "GBP", "bank_name": "Monzo",
        "account_name": "A OKORO", "account_number": "12345678",
    }, format="json")

    assert r.status_code == 400
    assert r.json()["error"] == "currency_not_payable"


@pytest.mark.django_db
def test_requesting_a_payout_surfaces_the_refusal_code_the_storefront_switches_on(
    django_user_model,
):
    ref_user, profile = referrer(django_user_model)
    c = _client(ref_user)

    # No bank account yet.
    r = c.post(PAYOUTS, {"currency": "NGN", "accept_terms": True}, format="json")
    assert r.status_code == 400
    assert r.json()["error"] == "payout_method_required"

    save_payout_method(
        ref_user, currency=ngn(), bank_name="GTBank",
        account_name="A OKORO", account_number="0123456789",
    )

    # Terms not accepted.
    r = c.post(PAYOUTS, {"currency": "NGN"}, format="json")
    assert r.json()["error"] == "terms_required"

    # Nothing earned.
    r = c.post(PAYOUTS, {"currency": "NGN", "accept_terms": True}, format="json")
    assert r.json()["error"] == "nothing_to_pay"

    # Enough earned.
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, subtotal="300000.00", referral_code=profile.code)
    Commission.objects.filter(pk=accrue_for_order(order).pk).update(status="available")

    r = c.post(PAYOUTS, {"currency": "NGN", "accept_terms": True}, format="json")
    assert r.status_code == 201
    assert r.json()["amount_display"] == "₦30,000.00"
    assert r.json()["status_label"] == "Being reviewed"
    assert r.json()["account_masked"] == "•••• 6789"


LOOKUP = "/api/v1/referrals/lookup/"


@pytest.mark.django_db
def test_code_lookup_is_public_and_names_the_referrer(django_user_model):
    """The bare code has to be redeemable, or the share card advertises a dead end."""
    ref_user, profile = referrer(django_user_model, "amina@x.com", first_name="Amina")

    body = APIClient().get(LOOKUP, {"code": profile.code.lower()}).json()

    assert body["valid"] is True
    assert body["referrer_name"] == "Amina"
    # A first name is the whole disclosure. Nothing else about the referrer leaks.
    assert ref_user.email not in str(body)
    assert "last_name" not in body and "email" not in body


@pytest.mark.django_db
def test_an_unknown_or_blocked_code_looks_identical(django_user_model):
    """"That code is suspended" would tell an abuser their block landed."""
    _ref, profile = referrer(django_user_model)
    profile.is_blocked = True
    profile.save(update_fields=["is_blocked"])
    c = APIClient()

    blocked = c.get(LOOKUP, {"code": profile.code}).json()
    missing = c.get(LOOKUP, {"code": "NOSUCHCODE"}).json()

    assert blocked == missing == {"valid": False, "reason": "not_found"}


@pytest.mark.django_db
def test_applying_your_own_code_is_refused_with_a_reason(django_user_model):
    """Attribution silently drops a self-referral from a COOKIE, which the customer never
    chose. Someone who TYPES their own code is owed an explanation instead."""
    ref_user, profile = referrer(django_user_model)
    c = APIClient()
    c.force_authenticate(ref_user)

    assert c.get(LOOKUP, {"code": profile.code}).json() == {"valid": False, "reason": "self"}

    # Anonymous, the same request is a normal valid lookup — we cannot know it is them.
    assert APIClient().get(LOOKUP, {"code": profile.code}).json()["valid"] is True


@pytest.mark.django_db
def test_lookup_handles_an_empty_or_missing_code_without_erroring(django_user_model):
    c = APIClient()
    assert c.get(LOOKUP).json() == {"valid": False, "reason": "empty"}
    assert c.get(LOOKUP, {"code": "   "}).json() == {"valid": False, "reason": "empty"}


@pytest.mark.django_db
def test_a_referrer_with_no_first_name_still_reads_as_a_sentence(django_user_model):
    _ref, profile = referrer(django_user_model, "noname@x.com")

    body = APIClient().get(LOOKUP, {"code": profile.code}).json()

    assert body["referrer_name"] == "a friend"
