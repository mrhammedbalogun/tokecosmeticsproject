"""Guest checkout earns a referrer commission, and buys the guest their discount.

Until 2026-08-28 `_refuse_attribution` turned away any buyer who was not authenticated,
so a guest who typed a referral code got nothing and paid for nobody. The storefront did
not know that: `POST /api/referral` is a public lookup with no idea who is asking, so it
answered "✓ that's 5% off for you" and the checkout then charged full price. Guest
checkout is how a large share of first orders arrive, so that was the programme's biggest
leak AND a promise the shop was visibly failing to keep.

The rule now: a guest is attributed on the same terms as anybody else, identified by the
email and phone they type at checkout instead of by an account row. Everything that
already disqualified an attribution still disqualifies it.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.referrals.services import (
    attribution_code_for_order,
    customer_discount_percent,
)
from apps.referrals.tests.factories import referrer


@pytest.mark.django_db
def test_a_guest_is_attributed(django_user_model):
    """The whole point. `buyer=None` is the guest checkout path (place_order passes the
    user through as None), and it now earns the referrer a commission."""
    _, profile = referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    assert attribution_code_for_order(
        profile.code, None, email="shopper@x.com", phone="+2348099999999"
    ) == profile.code


@pytest.mark.django_db
def test_a_guest_is_attributed_before_they_have_typed_anything(django_user_model):
    """The /cart preview: a guest quoting a total has no email yet.

    Attributing here is deliberate. The alternative — refusing until an identity exists —
    would show no discount on the cart page and then produce one at the review step,
    which reads as a pricing glitch. The cost is that a self-referring guest sees a
    discount on /cart that the review step quietly withdraws once they type their email;
    that is the correct place for it to go away, and it is BEFORE the pay button rather
    than a `cart_changed` refusal at it.
    """
    _, profile = referrer(django_user_model, "amina@x.com")

    assert attribution_code_for_order(profile.code, None) == profile.code


@pytest.mark.django_db
def test_a_guest_cannot_refer_themselves_by_email_or_phone(django_user_model):
    """The dodge the account path already closes, closed on the guest path too: log out,
    check out as a guest, type your own code. Matched on the contact details the guest
    submits, which is the only identity a guest has."""
    _, profile = referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    assert attribution_code_for_order(
        profile.code, None, email="AMINA@X.COM", phone="+2340000000000"
    ) == "", "same email as the referrer, cased differently"

    assert attribution_code_for_order(
        profile.code, None, email="someone.else@x.com", phone="+2348012345678"
    ) == "", "same phone as the referrer"


@pytest.mark.django_db
def test_a_blank_guest_phone_never_matches_a_referrer_without_one(django_user_model):
    """Mirrors the account rule: blank does not match blank. Two people with no phone on
    file are not evidence that they are the same person."""
    _, profile = referrer(django_user_model, "amina@x.com")  # no phone

    assert attribution_code_for_order(
        profile.code, None, email="shopper@x.com", phone=""
    ) == profile.code


@pytest.mark.django_db
def test_every_other_refusal_still_applies_to_a_guest(django_user_model):
    _, profile = referrer(django_user_model, "amina@x.com")

    assert attribution_code_for_order("NOSUCHCODE", None, email="shopper@x.com") == ""

    profile.is_blocked = True
    profile.save(update_fields=["is_blocked"])
    assert attribution_code_for_order(profile.code, None, email="shopper@x.com") == ""


@pytest.mark.django_db
def test_an_account_holders_own_details_still_win_over_the_guest_kwargs(django_user_model):
    """The email/phone kwargs describe a GUEST. When a real user is checking out, their
    account is the identity — a caller passing both must not be able to talk the
    self-referral guard out of a refusal by supplying innocent-looking contact details."""
    ref_user, profile = referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    assert attribution_code_for_order(
        profile.code, ref_user, email="notamina@x.com", phone="+2340000000000"
    ) == "", "the account is the identity, not the kwargs"


@pytest.mark.django_db
def test_a_guest_gets_the_customer_discount(django_user_model):
    """The other half of the programme, which was already written for this and simply
    never reached — see `customer_discount_percent`'s docstring."""
    _, profile = referrer(django_user_model, "amina@x.com")

    attributed = attribution_code_for_order(profile.code, None, email="shopper@x.com")
    assert customer_discount_percent(attributed, None, email="shopper@x.com") == Decimal("5.00")


@pytest.mark.django_db
def test_a_self_referring_guest_gets_no_discount_either(django_user_model):
    """The two halves stay in step: the refusal that costs the referrer their commission
    is the same one that costs the buyer their 5%, because the discount is computed from
    the ATTRIBUTED code and a refusal collapses it to ""."""
    _, profile = referrer(django_user_model, "amina@x.com")

    attributed = attribution_code_for_order(profile.code, None, email="amina@x.com")
    assert attributed == ""
    assert customer_discount_percent(attributed, None, email="amina@x.com") == Decimal("0.00")


@pytest.mark.django_db
def test_a_guest_order_accrues_a_real_commission(django_user_model):
    """End to end past attribution: the stamp on the order is all accrual needs, and it
    never reads `order.user` — so a guest order pays exactly like an account order."""
    from apps.referrals.services import accrue_for_order
    from apps.referrals.tests.factories import make_order

    ref_user, profile = referrer(django_user_model, "amina@x.com")
    code = attribution_code_for_order(profile.code, None, email="shopper@x.com")
    order = make_order(user=None, subtotal="10000.00", referral_code=code)

    commission = accrue_for_order(order)

    assert commission is not None, "a guest order must pay the referrer"
    assert commission.referrer_id == ref_user.pk
    assert commission.amount == Decimal("1000.00")  # 10% of 10,000


@pytest.mark.django_db
def test_guest_orders_from_different_people_are_not_one_customer(django_user_model):
    """A fraud flag that guest attribution would otherwise break.

    `fraud_flags` grouped buyers by `order.user_id`, which is NULL for every guest — so
    three guest orders from three unrelated shoppers collapsed to one key and tripped
    "all 3 orders came from a single customer" on an honest referrer. Guests are keyed by
    email instead, which is the identity they actually have.
    """
    from apps.referrals.models import Commission, PayoutRequest
    from apps.referrals.services import fraud_flags
    from apps.referrals.tests.factories import make_order, ng

    ref_user, profile = referrer(django_user_model, "amina@x.com")
    request = PayoutRequest.objects.create(
        referrer=ref_user, currency=ng().currency, amount=Decimal("3000.00"),
        net_amount=Decimal("3000.00"), status="requested",
    )
    for email in ("one@x.com", "two@x.com", "three@x.com"):
        order = make_order(user=None, referral_code=profile.code, email=email)
        Commission.objects.create(
            order=order, referrer=ref_user, currency=ng().currency,
            base_amount=Decimal("10000.00"), rate_percent=Decimal("10.00"),
            amount=Decimal("1000.00"), status="paid", payout=request,
        )

    flags = fraud_flags(request)

    assert not any("single customer" in f for f in flags), flags


@pytest.mark.django_db
def test_repeated_guest_orders_from_one_email_still_flag(django_user_model):
    """The other side of the same change: keying guests by email does not just silence
    the flag, it makes it MEAN something on the guest path — the same person ordering
    three times through their own code is exactly what a reviewer wants to see."""
    from apps.referrals.models import Commission, PayoutRequest
    from apps.referrals.services import fraud_flags
    from apps.referrals.tests.factories import make_order, ng

    ref_user, profile = referrer(django_user_model, "amina@x.com")
    request = PayoutRequest.objects.create(
        referrer=ref_user, currency=ng().currency, amount=Decimal("3000.00"),
        net_amount=Decimal("3000.00"), status="requested",
    )
    for _ in range(3):
        order = make_order(user=None, referral_code=profile.code, email="same.person@x.com")
        Commission.objects.create(
            order=order, referrer=ref_user, currency=ng().currency,
            base_amount=Decimal("10000.00"), rate_percent=Decimal("10.00"),
            amount=Decimal("1000.00"), status="paid", payout=request,
        )

    flags = fraud_flags(request)

    assert any("single customer" in f for f in flags), flags
