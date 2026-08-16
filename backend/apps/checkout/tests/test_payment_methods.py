import pytest
from rest_framework.test import APIClient

from apps.core.models import Country, Currency
from apps.payments.models import BankAccount, CountryPaymentGateway

pytestmark = pytest.mark.django_db


def test_payment_methods_for_country(settings):
    # Use a FRESH, unseeded country (Togo). The payments 0002 seed pre-populates NG/GB/
    # US/CA/ZZ, so asserting an exact gateway list on NG would fight the seeded rows.
    # Togo has no seeded rows, so the list is exactly what this test sets — keeping the
    # original intent: active gateways returned in sort order, inactive excluded.
    # KES rather than Togo's real XOF: active_gateways_for also filters on currency
    # support (2026-08-12) and Paystack cannot charge XOF — this test is about sort
    # order and the inactive filter, so the currency must be one every row can charge.
    kes = Currency.objects.create(code="KES", symbol="KSh")
    tg = Country.objects.create(code="TG", name="Togo", currency=kes)
    CountryPaymentGateway.objects.create(country=tg, gateway="paystack", sort_order=1)
    CountryPaymentGateway.objects.create(country=tg, gateway="bank_transfer", sort_order=3)
    CountryPaymentGateway.objects.create(country=tg, gateway="off", is_active=False, sort_order=9)
    # Being switched on is no longer sufficient — active_gateways_for also requires the
    # gateway to be usable, so give each one what it needs to take a payment. Without
    # this the endpoint correctly returns nothing and the sort-order intent goes untested.
    settings.PAYSTACK_SECRET_KEY = "sk_test_configured"
    BankAccount.objects.create(
        country=tg, currency=kes, bank_name="Ecobank",
        account_name="Toke Cosmetics", account_number="0123456789",
    )

    r = APIClient().get("/api/v1/checkout/payment-methods/?country=TG")
    gateways = [row["gateway"] for row in r.data]
    assert gateways == ["paystack", "bank_transfer"]  # sorted; inactive excluded


def test_payment_methods_omits_a_gateway_that_cannot_take_a_payment(settings):
    """The endpoint must not advertise what checkout would refuse: a switched-on
    gateway with no keys, and bank transfer with no account, are both absent."""
    xof = Currency.objects.create(code="XOF", symbol="CFA")
    tg = Country.objects.create(code="TG", name="Togo", currency=xof)
    CountryPaymentGateway.objects.create(country=tg, gateway="paystack", sort_order=1)
    CountryPaymentGateway.objects.create(country=tg, gateway="bank_transfer", sort_order=3)
    settings.PAYSTACK_SECRET_KEY = ""

    r = APIClient().get("/api/v1/checkout/payment-methods/?country=TG")
    assert [row["gateway"] for row in r.data] == []


def test_bank_transfer_carries_the_markets_payment_instructions():
    """The admin-authored instructions (rich HTML, sanitised on write) ride the
    payment-methods response — the storefront shows them behind a "Read payment
    instructions" link on the method card. Other gateways answer "" (no link)."""
    ngn = Currency.objects.create(code="TGX", symbol="T")
    tg = Country.objects.create(code="TG", name="Togo", currency=ngn)
    CountryPaymentGateway.objects.create(country=tg, gateway="bank_transfer", sort_order=1)
    BankAccount.objects.create(
        country=tg, currency=ngn, bank_name="Ecobank",
        account_name="Toke Cosmetics", account_number="0123456789",
        instructions="<h3>Payment Instructions</h3><p>Delivery takes <strong>3-5 working days</strong>.</p>",
    )

    r = APIClient().get("/api/v1/checkout/payment-methods/?country=TG")
    assert r.data == [{
        "gateway": "bank_transfer",
        "sort_order": 1,
        "instructions": "<h3>Payment Instructions</h3><p>Delivery takes <strong>3-5 working days</strong>.</p>",
    }]
