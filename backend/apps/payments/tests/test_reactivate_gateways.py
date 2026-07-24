"""Reactivation (0009) turns on the three hybrid gateways with correct per-country sort,
leaves bank transfer active as the fallback, leaves Stripe off, and its reverse switches
the online gateways back off (reactivation is a human checkpoint, never a rollback side
effect).

Numbering note: the plan that specced this task assumed 0007_launch_bank_transfer_only was
the latest payments migration and this would be 0008. By the time this task ran,
0008_payment_purpose (adding Payment.purpose) had already landed on top of 0007. This
migration is therefore 0009_reactivate_online_gateways, depending on 0008_payment_purpose.
"""
import pytest

pytestmark = pytest.mark.django_db


def _offered(country):
    from apps.payments.gateways.registry import active_gateways_for
    return [(g["gateway"], g["sort_order"]) for g in active_gateways_for(country)]


def test_ng_menu_after_reactivation():
    from apps.core.models import Country
    ng = Country.objects.get(code="NG")
    assert _offered(ng) == [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)]


@pytest.mark.parametrize("code", ["GB", "US", "CA", "ZZ"])
def test_international_menu_after_reactivation(code):
    from apps.core.models import Country
    country = Country.objects.get(code=code)
    assert _offered(country) == [("paypal", 1), ("bank_transfer", 2)]


def test_stripe_stays_inactive():
    from apps.payments.models import CountryPaymentGateway
    assert not CountryPaymentGateway.objects.filter(gateway="stripe", is_active=True).exists()


def test_reverse_switches_online_gateways_off(db):
    """Uses the plain `db` fixture, not `transactional_db` — see the comment on
    test_reverse_does_not_reactivate_the_networked_gateways in test_launch_gateway_state.py
    for why: `transactional_db`'s post-test flush wipes the baseline Country/
    CountryPaymentGateway seed data session-wide, which breaks whichever migration-exercising
    test runs second. `db` rolls back cleanly (Postgres supports transactional DDL)."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from apps.payments.models import CountryPaymentGateway

    MigrationExecutor(connection).migrate([("payments", "0008_payment_purpose")])
    try:
        assert not CountryPaymentGateway.objects.filter(
            gateway__in=["paystack", "flutterwave", "paypal"], is_active=True
        ).exists()
        assert CountryPaymentGateway.objects.filter(
            gateway="bank_transfer", is_active=True).count() >= 5
    finally:
        MigrationExecutor(connection).migrate([("payments", "0009_reactivate_online_gateways")])
