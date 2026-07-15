import pytest
from django.db.utils import IntegrityError

from apps.core.models import Country, Currency


@pytest.mark.django_db
def test_currency_and_country_basic():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(
        code="NG", name="Nigeria", currency=ngn, is_default=True,
        tax_rate_percent="7.50", prices_include_tax=True,
    )
    assert ng.currency.code == "NGN"
    assert ngn.decimal_places == 2  # default
    assert str(ng) == "Nigeria (NG)"
    assert str(ngn) == "NGN"


@pytest.mark.django_db
def test_currency_protected_from_delete_while_country_uses_it():
    gbp = Currency.objects.create(code="GBP", symbol="£")
    Country.objects.create(code="GB", name="United Kingdom", currency=gbp)
    with pytest.raises(IntegrityError):
        gbp.delete()  # on_delete=PROTECT
