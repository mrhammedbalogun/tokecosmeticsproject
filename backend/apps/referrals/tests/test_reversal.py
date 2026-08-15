"""Returns and refunds: un-earning commission, including after it has been paid out."""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.referrals.models import Commission, ReferralAdjustment
from apps.referrals.services import accrue_for_order, balances, reverse_for_refund
from apps.referrals.tests.factories import customer, make_order, referrer


def _accrued(django_user_model, **kwargs):
    ref_user, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(
        user=buyer, subtotal="10000.00", shipping="1500.00",
        referral_code=profile.code, **kwargs,
    )
    return ref_user, order, accrue_for_order(order)


@pytest.mark.django_db
def test_a_full_refund_reverses_the_commission(django_user_model):
    _ref, order, commission = _accrued(django_user_model)
    assert commission.amount == Decimal("1000.00")

    reverse_for_refund(order, Decimal("11500.00"))  # goods + shipping

    commission.refresh_from_db()
    assert commission.status == "reversed"
    assert commission.reversed_at is not None
    # The amount is KEPT, not zeroed: `reversed` already excludes it from every balance,
    # and the referrer's history should say what the order had been worth.
    assert commission.amount == Decimal("1000.00")
    assert commission.base_amount == Decimal("10000.00")


@pytest.mark.django_db
def test_a_partial_refund_reduces_the_commission_proportionally(django_user_model):
    _ref, order, commission = _accrued(django_user_model)

    reverse_for_refund(order, Decimal("4000.00"))

    commission.refresh_from_db()
    assert commission.status == "pending", "still live — only part came back"
    assert commission.base_amount == Decimal("6000.00")
    assert commission.amount == Decimal("600.00")


@pytest.mark.django_db
def test_reversal_takes_the_running_total_so_replays_do_not_deduct_twice(django_user_model):
    """Gateways redeliver refund webhooks. A decrementing implementation would silently
    halve the commission on every replay and nobody would notice until a referrer
    complained about a balance that only went down."""
    _ref, order, commission = _accrued(django_user_model)

    reverse_for_refund(order, Decimal("4000.00"))
    reverse_for_refund(order, Decimal("4000.00"))  # the same webhook again
    reverse_for_refund(order, Decimal("4000.00"))

    commission.refresh_from_db()
    assert commission.amount == Decimal("600.00")


@pytest.mark.django_db
def test_two_partial_refunds_settle_at_the_combined_total(django_user_model):
    _ref, order, commission = _accrued(django_user_model)

    reverse_for_refund(order, Decimal("2000.00"))
    reverse_for_refund(order, Decimal("5000.00"))  # running total, not a second delta

    commission.refresh_from_db()
    assert commission.base_amount == Decimal("5000.00")
    assert commission.amount == Decimal("500.00")


@pytest.mark.django_db
def test_a_refund_after_payout_becomes_a_negative_adjustment(django_user_model):
    """THE case ReferralAdjustment exists for. The money is in someone's bank account;
    it cannot be recalled, so it nets against what they earn next."""
    ref_user, order, commission = _accrued(django_user_model)
    commission.status = "paid"
    commission.save(update_fields=["status"])

    reverse_for_refund(order, Decimal("11500.00"))

    commission.refresh_from_db()
    assert commission.status == "paid", "a paid row is never rewritten"
    assert commission.amount == Decimal("1000.00")

    clawback = ReferralAdjustment.objects.get(referrer=ref_user, order=order)
    assert clawback.kind == "clawback"
    assert clawback.amount == Decimal("-1000.00")

    # And the wallet is now in the red, which is exactly what should stop a payout.
    wallet = next(w for w in balances(ref_user) if w.currency.code == "NGN")
    assert wallet.available == Decimal("-1000.00")
    assert wallet.can_request is False


@pytest.mark.django_db
def test_a_replayed_refund_does_not_stack_clawbacks(django_user_model):
    ref_user, order, commission = _accrued(django_user_model)
    commission.status = "paid"
    commission.save(update_fields=["status"])

    reverse_for_refund(order, Decimal("4000.00"))
    reverse_for_refund(order, Decimal("4000.00"))
    reverse_for_refund(order, Decimal("11500.00"))  # then the rest came back too

    rows = ReferralAdjustment.objects.filter(referrer=ref_user, order=order)
    assert rows.count() == 1
    assert rows.first().amount == Decimal("-1000.00")


@pytest.mark.django_db
def test_reversal_never_raises(django_user_model, monkeypatch):
    """It runs inside the refund transaction. A referral bug must not stop a customer
    being refunded."""
    _ref, order, _commission = _accrued(django_user_model)
    monkeypatch.setattr(
        "apps.referrals.services.commission_base",
        lambda _o: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    reverse_for_refund(order, Decimal("11500.00"))  # must not raise

    assert Commission.objects.get(order=order).status == "pending"
