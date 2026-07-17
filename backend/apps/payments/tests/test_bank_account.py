import pytest
from django.core.exceptions import ValidationError

from apps.core.models import Country, Currency
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db


def _account(country, **kw):
    defaults = dict(
        country=country, currency=country.currency, bank_name="GTBank",
        account_name="Toke Cosmetics Ltd", account_number="0123456789",
    )
    return BankAccount(**{**defaults, **kw})


def test_currency_must_match_the_countrys_currency():
    # A GBP account under Nigeria would show a Lagos customer an account they cannot pay
    # into in NGN. The order's currency comes from its country, so these must agree.
    account = _account(Country.objects.get(code="NG"), currency=Currency.objects.get(code="GBP"))
    with pytest.raises(ValidationError) as exc:
        account.full_clean()
    assert "currency" in exc.value.error_dict


def test_matching_currency_is_accepted():
    ng = Country.objects.get(code="NG")
    account = _account(ng)
    account.full_clean()
    account.save()
    assert ng.bank_account == account
