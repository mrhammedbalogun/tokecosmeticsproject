"""Plan-19b: the money-config surfaces that had no UI path at all.

`BankAccount` is the sharp one. Its own docstring says "this row IS the payment page for
that country", Plan-09b deferred its screen to `/django-admin/`, and that path is denied
outright at the Apache vhost — so until now the account number every Nigerian customer
wires money to could only be changed with a database client.
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.rbac import scopes_for_role
from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country
from apps.payments.models import BankAccount, CountryPaymentGateway

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_the_payout_account_is_owner_only_by_design():
    """Not an accident of routing: `rbac.py` put the payout account behind
    `settings.manage` before any screen existed, and Manager does not hold it."""
    assert "settings.manage" in scopes_for_role("Owner")
    assert "settings.manage" not in scopes_for_role("Manager")
    assert "settings.manage" not in scopes_for_role("Support")


def test_bank_accounts_require_staff():
    assert APIClient().get("/api/v1/admin/bank-accounts/").status_code in (401, 403)


def test_the_account_number_can_finally_be_changed(owner):
    country = Country.objects.get(code="NG")
    account = BankAccount.objects.create(
        country=country, currency=country.currency, bank_name="GTBank",
        account_name="Toke Cosmetics Ltd", account_number="0123456789",
    )

    response = owner.patch(
        f"/api/v1/admin/bank-accounts/{account.pk}/",
        {"account_number": "9876543210"},
        format="json",
    )

    assert response.status_code == 200, response.data
    account.refresh_from_db()
    assert account.account_number == "9876543210"


def test_A_BANK_ACCOUNT_CANNOT_BE_DELETED(owner):
    """Deleting it does not disable bank transfer — it makes `initiate()` fail for every
    customer in that market with nothing to read. Deactivating is the switch."""
    country = Country.objects.get(code="NG")
    account = BankAccount.objects.create(
        country=country, currency=country.currency, bank_name="GTBank",
        account_name="Toke", account_number="0123456789",
    )

    response = owner.delete(f"/api/v1/admin/bank-accounts/{account.pk}/")

    assert response.status_code == 405
    assert BankAccount.objects.filter(pk=account.pk).exists()


def test_the_gateway_switch_works(owner):
    """The one Plan-09 left as a production DB edit: turning a payment method on."""
    gateway = CountryPaymentGateway.objects.filter(gateway="paystack").first()
    assert gateway is not None

    response = owner.patch(
        f"/api/v1/admin/payment-gateways/{gateway.pk}/", {"is_active": False}, format="json"
    )

    assert response.status_code == 200
    gateway.refresh_from_db()
    assert gateway.is_active is False
