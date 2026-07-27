"""Uncertified and unconfigured gateways must never reach a customer.

Two independent layers, because a human toggle must not be the last line of
defence:

  * migration 0010 deactivates the rows 0009 switched on without certification
    (Plan-09b's rule: a gateway does not reactivate without a driven test-mode
    payment; only Paystack has earned it);
  * `active_gateways_for` filters on configuredness at REQUEST time, so an
    unconfigured gateway cannot be offered even if someone flips is_active back
    on or a deploy loses an env var.

Layer 1 says what we intend. Layer 2 makes being wrong harmless.
"""
import pytest

pytestmark = pytest.mark.django_db


def _offered(country):
    from apps.payments.gateways.registry import active_gateways_for
    return [g["gateway"] for g in active_gateways_for(country)]


def _country(code):
    from apps.core.models import Country
    return Country.objects.get(code=code)


@pytest.fixture
def ng_bank_account():
    """bank_transfer is only offerable where an active BankAccount exists."""
    from apps.core.models import Country, Currency
    from apps.payments.models import BankAccount
    ng = Country.objects.get(code="NG")
    return BankAccount.objects.create(
        country=ng,
        currency=Currency.objects.get(pk="NGN"),
        bank_name="Test Bank",
        account_name="Toke Cosmetics Ltd",
        account_number="0123456789",
    )


def test_flutterwave_is_deactivated_by_migration():
    from apps.payments.models import CountryPaymentGateway
    assert not CountryPaymentGateway.objects.filter(
        gateway="flutterwave", is_active=True
    ).exists()


def test_paypal_is_deactivated_by_migration():
    from apps.payments.models import CountryPaymentGateway
    assert not CountryPaymentGateway.objects.filter(gateway="paypal", is_active=True).exists()


def test_paystack_stays_active_it_is_the_one_certified_gateway():
    from apps.payments.models import CountryPaymentGateway
    assert CountryPaymentGateway.objects.filter(gateway="paystack", is_active=True).exists()


def test_ng_offers_paystack_and_bank_transfer(ng_bank_account):
    assert _offered(_country("NG")) == ["paystack", "bank_transfer"]


def test_unconfigured_gateway_is_not_offered_even_when_switched_on(settings):
    """The durable guarantee: is_active is merchandising intent, not permission.

    Someone re-enables flutterwave in the DB but its keys are absent — the
    customer must still never be handed a gateway that 503s at initiate.
    """
    from apps.payments.models import CountryPaymentGateway
    settings.FLUTTERWAVE_SECRET_KEY = ""
    settings.FLUTTERWAVE_SECRET_HASH = ""
    CountryPaymentGateway.objects.filter(gateway="flutterwave").update(is_active=True)

    assert "flutterwave" not in _offered(_country("NG"))


def test_configured_gateway_is_offered_when_switched_on(settings):
    """The other half: the filter must not suppress a gateway that IS ready."""
    from apps.payments.models import CountryPaymentGateway
    settings.FLUTTERWAVE_SECRET_KEY = "sk_test_x"
    settings.FLUTTERWAVE_SECRET_HASH = "hash_x"
    CountryPaymentGateway.objects.filter(gateway="flutterwave").update(is_active=True)

    assert "flutterwave" in _offered(_country("NG"))


def test_bank_transfer_is_not_offered_without_a_bank_account():
    """W002's failure made structural: no account means checkout refuses the
    order at initiate, so the method must not appear in the menu either."""
    assert "bank_transfer" not in _offered(_country("GB"))


def test_bank_transfer_is_offered_once_an_account_exists(ng_bank_account):
    assert "bank_transfer" in _offered(_country("NG"))


def test_inactive_bank_account_does_not_count(ng_bank_account):
    ng_bank_account.is_active = False
    ng_bank_account.save()
    assert "bank_transfer" not in _offered(_country("NG"))
