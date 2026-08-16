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


# --- dynamic per-market gateways (2026-08-12) -------------------------------------------
#
# "What if we decide to enable Flutterwave in the UK?" — the model always allowed it; the
# admin surface now makes it a two-click act with honest warnings instead of a DB edit.


def test_a_gateway_can_be_added_to_any_market(owner):
    """Flutterwave in GB: the exact future case the dynamic settings exist for."""
    gb = Country.objects.get(code="GB")
    CountryPaymentGateway.objects.filter(country=gb, gateway="flutterwave").delete()

    response = owner.post(
        "/api/v1/admin/payment-gateways/",
        {"country": gb.pk, "gateway": "flutterwave", "is_active": False, "sort_order": 5},
        format="json",
    )

    assert response.status_code == 201, response.data
    row = CountryPaymentGateway.objects.get(country=gb, gateway="flutterwave")
    assert row.is_active is False  # adding never silently goes live


def test_adding_the_same_gateway_twice_is_refused(owner):
    ng = Country.objects.get(code="NG")

    response = owner.post(
        "/api/v1/admin/payment-gateways/",
        {"country": ng.pk, "gateway": "paystack", "sort_order": 9},
        format="json",
    )

    assert response.status_code == 400  # unique (country, gateway)


def test_a_market_row_can_be_removed(owner):
    """DELETE means "this market never offered this" — allowed here, unlike the account."""
    gb = Country.objects.get(code="GB")
    row, _ = CountryPaymentGateway.objects.get_or_create(
        country=gb, gateway="flutterwave", defaults={"is_active": False, "sort_order": 5}
    )

    response = owner.delete(f"/api/v1/admin/payment-gateways/{row.pk}/")

    assert response.status_code == 204
    assert not CountryPaymentGateway.objects.filter(pk=row.pk).exists()


def test_rows_report_configuredness_and_currency_support(owner, settings):
    """The toggle must not lie: `is_active` is intent, and the storefront intersects it
    with configuredness — the row says which keys are missing and which currencies the
    adapter can charge, so "on but dark" is visible instead of a mystery."""
    settings.FLUTTERWAVE_SECRET_KEY = ""
    settings.FLUTTERWAVE_SECRET_HASH = ""

    response = owner.get("/api/v1/admin/payment-gateways/", {"gateway": "flutterwave"})

    assert response.status_code == 200
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    row = next(r for r in rows if r["country_name"] == "Nigeria")
    assert row["configured"] is False
    assert "FLUTTERWAVE_SECRET_KEY" in row["missing_settings"]
    assert row["country_currency"] == "NGN"
    assert "NGN" in row["supported_currencies"]


def test_the_catalog_lists_every_adapter(owner):
    """The add-to-market menu comes from the registry, never a hardcoded UI list."""
    response = owner.get("/api/v1/admin/payment-gateways/catalog/")

    assert response.status_code == 200
    by_code = {entry["code"]: entry for entry in response.data}
    assert {"bank_transfer", "paystack", "flutterwave", "paypal", "stripe"} <= set(by_code)
    assert "GBP" in by_code["flutterwave"]["supported_currencies"]  # the FW-in-UK future
    assert by_code["bank_transfer"]["needs"] == "bank_account"
    assert by_code["paystack"]["needs"] == "api_keys"


def test_the_catalog_is_owner_only():
    assert APIClient().get("/api/v1/admin/payment-gateways/catalog/").status_code in (401, 403)



# --- creating an account from the admin (2026-08-16) ------------------------------------
#
# Enabling bank transfer for a market was one click; entering WHAT customers pay into was
# impossible — the screen only edited rows that already existed, so a new market (the
# CA/US state payments.W002 warns about) stayed stranded. POST was always allowed on the
# viewset; these pin the create path the UI now uses.


def test_an_account_can_be_created_for_a_stranded_market(owner):
    """The exact W002 case: bank transfer on, no account, no way in. Now: POST."""
    us = Country.objects.get(code="US")
    BankAccount.objects.filter(country=us).delete()

    response = owner.post(
        "/api/v1/admin/bank-accounts/",
        {
            "country": us.pk, "currency": us.currency_id, "bank_name": "Chase",
            "account_name": "Toke Cosmetics LLC", "account_number": "000123456789",
            "extra": {"Routing number": "021000021"},
            "instructions": "<p>Quote your order number as the wire reference.</p>",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    account = BankAccount.objects.get(country=us)
    assert account.extra == {"Routing number": "021000021"}
    assert account.instructions == "<p>Quote your order number as the wire reference.</p>"


def test_a_second_account_for_the_same_market_is_refused(owner):
    """OneToOne on country: the market's account is edited, never duplicated."""
    ng = Country.objects.get(code="NG")
    BankAccount.objects.get_or_create(
        country=ng, defaults=dict(
            currency=ng.currency, bank_name="GTBank",
            account_name="Toke", account_number="0123456789",
        ),
    )

    response = owner.post(
        "/api/v1/admin/bank-accounts/",
        {"country": ng.pk, "currency": ng.currency_id, "bank_name": "Zenith",
         "account_name": "Toke", "account_number": "1224748585"},
        format="json",
    )

    assert response.status_code == 400


def test_extra_fields_must_be_flat_text(owner):
    """Keys are the labels customers read; values go into banking apps. A nested blob
    would render as [object Object] on the payment page."""
    us = Country.objects.get(code="US")
    BankAccount.objects.filter(country=us).delete()

    response = owner.post(
        "/api/v1/admin/bank-accounts/",
        {"country": us.pk, "currency": us.currency_id, "bank_name": "Chase",
         "account_name": "Toke", "account_number": "1",
         "extra": {"routing": {"aba": "021000021"}}},
        format="json",
    )

    assert response.status_code == 400
    assert "extra" in response.data


def test_instructions_are_sanitised_on_write(owner):
    """Instructions are admin-authored HTML rendered on the checkout origin via
    dangerouslySetInnerHTML — the write path must strip anything scriptable so the
    database only ever holds safe HTML (apps/cms/sanitize.py, product-prose contract)."""
    us = Country.objects.get(code="US")
    BankAccount.objects.filter(country=us).delete()

    response = owner.post(
        "/api/v1/admin/bank-accounts/",
        {"country": us.pk, "currency": us.currency_id, "bank_name": "Chase",
         "account_name": "Toke", "account_number": "1",
         "instructions": '<h3>Pay us</h3><script>steal()</script>'
                         '<p onclick="x()">Send <strong>receipt</strong> via '
                         '<a href="javascript:bad()">this link</a>.</p>'},
        format="json",
    )

    assert response.status_code == 201, response.data
    saved = BankAccount.objects.get(country=us).instructions
    assert "<script" not in saved and "onclick" not in saved and "javascript:" not in saved
    assert "<h3>Pay us</h3>" in saved and "<strong>receipt</strong>" in saved
