"""The holding period: when a commission becomes real money."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.referrals.models import Commission
from apps.referrals.services import accrue_for_order
from apps.referrals.tasks import mature_commissions
from apps.referrals.tests.factories import customer, make_order, mark_shipped, referrer


def _commission(django_user_model, **order_kwargs):
    _, profile = referrer(django_user_model)
    buyer = customer(django_user_model, "buyer@x.com")
    order = make_order(user=buyer, referral_code=profile.code, **order_kwargs)
    return accrue_for_order(order), order


@pytest.mark.django_db
def test_a_paid_but_unshipped_order_never_starts_its_clock(django_user_model):
    """"Fully paid AND shipped" is the published wording. Paid alone is not a sale yet."""
    commission, _order = _commission(django_user_model, status="processing")

    mature_commissions()

    commission.refresh_from_db()
    assert commission.matures_at is None
    assert commission.status == "pending"


@pytest.mark.django_db
def test_the_clock_runs_from_shipping_not_from_payment(django_user_model):
    commission, order = _commission(django_user_model)
    shipped_at = timezone.now() - timezone.timedelta(days=10)
    mark_shipped(order, when=shipped_at)

    mature_commissions()

    commission.refresh_from_db()
    assert commission.matures_at is not None
    # 60 days after SHIPPING. Accrual happened just now, so a payment-based clock would
    # land ~10 days later than this.
    expected = shipped_at + timezone.timedelta(days=60)
    assert abs((commission.matures_at - expected).total_seconds()) < 5
    assert commission.status == "pending", "10 days in, still holding"


@pytest.mark.django_db
def test_it_becomes_available_once_the_holding_period_has_passed(django_user_model):
    commission, order = _commission(django_user_model)
    mark_shipped(order, when=timezone.now() - timezone.timedelta(days=61))

    mature_commissions()

    commission.refresh_from_db()
    assert commission.status == "available"


@pytest.mark.django_db
def test_a_cancelled_order_is_reversed_rather_than_left_pending(django_user_model):
    commission, order = _commission(django_user_model)
    order.status = "cancelled"
    order.save(update_fields=["status"])

    mature_commissions()

    commission.refresh_from_db()
    assert commission.status == "reversed"
    assert "cancelled" in commission.reversed_reason
    # The amount survives so the referrer's history can explain itself.
    assert commission.amount > Decimal("0")


@pytest.mark.django_db
def test_shipped_without_a_timeline_event_is_left_unstamped_not_guessed(django_user_model):
    """A migrated order can be `shipped` with no `status:shipped` event.

    Inventing a date there would be inventing a payout date, so the sweep declines and
    the row simply waits. An unpaid commission is recoverable; an early payout is not.
    """
    commission, order = _commission(django_user_model)
    order.status = "shipped"
    order.save(update_fields=["status"])  # no OrderEvent written

    mature_commissions()

    commission.refresh_from_db()
    assert commission.matures_at is None
    assert commission.status == "pending"


@pytest.mark.django_db
def test_the_sweep_is_idempotent(django_user_model):
    commission, order = _commission(django_user_model)
    mark_shipped(order, when=timezone.now() - timezone.timedelta(days=61))

    first = mature_commissions()
    second = mature_commissions()

    assert first["released"] == 1
    assert second == {"stamped": 0, "recomputed": 0, "released": 0, "stalled": 0}
    assert Commission.objects.get(pk=commission.pk).status == "available"
