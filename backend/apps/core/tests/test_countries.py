import pytest
from django.db.utils import IntegrityError

from apps.core.models import Country, Currency


# Use synthetic codes (XT*) in these unit tests so they don't collide with the
# seed migration's real rows (NGN/NG/GBP/GB) that exist in every test DB.


@pytest.mark.django_db
def test_currency_and_country_basic():
    cur = Currency.objects.create(code="XTS", symbol="✱")
    c = Country.objects.create(
        code="XT", name="Testland", currency=cur, is_default=False,
        tax_rate_percent="5.00", prices_include_tax=True,
    )
    assert c.currency.code == "XTS"
    assert cur.decimal_places == 2  # default
    assert str(c) == "Testland (XT)"
    assert str(cur) == "XTS"


@pytest.mark.django_db
def test_currency_protected_from_delete_while_country_uses_it():
    cur = Currency.objects.create(code="XTP", symbol="✚")
    Country.objects.create(code="XP", name="Protectland", currency=cur)
    with pytest.raises(IntegrityError):
        cur.delete()  # on_delete=PROTECT


@pytest.mark.django_db
def test_seed_data_present():
    # Seeded by migration 0003 — available in every test DB.
    assert Currency.objects.filter(is_active=True).count() >= 4
    ng = Country.objects.get(code="NG")
    assert ng.is_default is True
    assert ng.currency.code == "NGN"
    assert str(ng.tax_rate_percent) == "7.50"

    zz = Country.objects.get(code="ZZ")
    assert zz.is_rest_of_world is True
    assert zz.currency.code == "USD"
    assert zz.is_default is False

    # Exactly one default market, exactly one rest-of-world context.
    assert Country.objects.filter(is_default=True).count() == 1
    assert Country.objects.filter(is_rest_of_world=True).count() == 1
