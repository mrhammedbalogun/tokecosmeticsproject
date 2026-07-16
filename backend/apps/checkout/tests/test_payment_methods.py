import pytest
from rest_framework.test import APIClient

from apps.core.models import Country, Currency
from apps.payments.models import CountryPaymentGateway

pytestmark = pytest.mark.django_db


def test_payment_methods_for_country():
    # Use a FRESH, unseeded country (Togo). The payments 0002 seed pre-populates NG/GB/
    # US/CA/ZZ, so asserting an exact gateway list on NG would fight the seeded rows.
    # Togo has no seeded rows, so the list is exactly what this test sets — keeping the
    # original intent: active gateways returned in sort order, inactive excluded.
    xof = Currency.objects.create(code="XOF", symbol="CFA")
    tg = Country.objects.create(code="TG", name="Togo", currency=xof)
    CountryPaymentGateway.objects.create(country=tg, gateway="paystack", sort_order=1)
    CountryPaymentGateway.objects.create(country=tg, gateway="bank_transfer", sort_order=3)
    CountryPaymentGateway.objects.create(country=tg, gateway="off", is_active=False, sort_order=9)

    r = APIClient().get("/api/v1/checkout/payment-methods/?country=TG")
    gateways = [row["gateway"] for row in r.data]
    assert gateways == ["paystack", "bank_transfer"]  # sorted; inactive excluded
