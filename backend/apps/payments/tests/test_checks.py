"""Deploy-time visibility for the two ways a live gateway can be unusable in practice:
a networked one missing its keys (W001), and bank transfer missing its account (W002).

W002 is the one that bites at launch. Bank transfer is the only live method, and checkout
refuses an order for a manual gateway with no account rather than reserving stock and
503ing — so a market in that state cannot sell at all, silently. Better known at deploy
than from the customer who couldn't buy.
"""
import pytest
from django.test import override_settings

from apps.core.models import Country
from apps.payments.checks import gateway_configuration_check
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db

MARKETS = ["NG", "GB", "US", "CA", "ZZ"]

# W001 is a function of the SETTINGS, so every test about it must pin them. Reading whatever
# happens to be in the developer's .env made these tests pass only while the gateways were
# unconfigured: the day real keys landed (Plan-14b, Paystack) the suite went red without a
# line of source changing — and it would have gone red again at launch, for each gateway.
NO_KEYS = override_settings(
    PAYSTACK_SECRET_KEY="", FLUTTERWAVE_SECRET_KEY="", FLUTTERWAVE_SECRET_HASH="",
    PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET="", PAYPAL_WEBHOOK_ID="",
    STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="",
)


def _ids():
    return [w.id for w in gateway_configuration_check(None)]


def _w001():
    return [w for w in gateway_configuration_check(None) if w.id == "payments.W001"]


@NO_KEYS
def test_no_key_warning_for_a_gateway_that_is_switched_off_everywhere():
    """Stripe was dropped in Plan-14 and 0009 leaves it inactive in every market. Warning
    that its keys are missing is noise, and noise is what hides the warning that matters
    while someone is configuring the OTHER gateways."""
    assert not any("stripe" in w.msg for w in _w001())


@NO_KEYS
def test_warns_for_a_live_gateway_missing_its_keys_and_names_the_markets():
    # 0009 activates paystack + flutterwave on NG and paypal internationally; with the keys
    # blanked, each live gateway is unusable where it is offered.
    warnings = {w.msg.split("'")[1]: w.msg for w in _w001()}
    assert {"paystack", "flutterwave", "paypal"} <= set(warnings)
    # Naming the affected markets is the difference between "go look" and "go fix NG".
    assert "NG" in warnings["paystack"]
    assert "NG" not in warnings["paypal"]
    assert "GB" in warnings["paypal"]


@override_settings(PAYSTACK_SECRET_KEY="sk_test_configured")
def test_no_key_warning_once_the_gateway_is_configured():
    """The half W001 exists to report and nothing covered: the warning has to GO AWAY once
    the key lands, or it cannot be used to confirm that it did."""
    assert not any("paystack" in w.msg for w in _w001())


@NO_KEYS
def test_no_key_warning_once_the_gateway_is_deactivated_in_every_market():
    from apps.payments.models import CountryPaymentGateway

    CountryPaymentGateway.objects.filter(gateway="paystack").update(is_active=False)
    assert not any("paystack" in w.msg for w in _w001())


def test_warns_when_a_market_has_bank_transfer_live_but_no_account():
    # Migration 0007 leaves bank_transfer active in all five markets; no BankAccount rows
    # exist in a fresh DB, so every one of them is stranded.
    assert "payments.W002" in _ids()


def test_no_warning_once_every_market_has_an_account():
    for code in MARKETS:
        country = Country.objects.get(code=code)
        BankAccount.objects.create(
            country=country, currency=country.currency, bank_name="GTBank",
            account_name="Toke Cosmetics Ltd", account_number="0123456789",
        )
    assert "payments.W002" not in _ids()


def test_an_inactive_account_does_not_count_as_funded():
    """is_active=False is how staff take an account out of service — a row that exists but
    is switched off leaves the market exactly as unable to sell as no row at all."""
    for code in MARKETS:
        country = Country.objects.get(code=code)
        BankAccount.objects.create(
            country=country, currency=country.currency, bank_name="GTBank",
            account_name="Toke Cosmetics Ltd", account_number="0123456789",
            is_active=(code != "NG"),
        )
    warnings = [w for w in gateway_configuration_check(None) if w.id == "payments.W002"]
    assert len(warnings) == 1
    # Naming the stranded market is the whole value of the warning — "some market is
    # broken" sends staff hunting through five of them.
    assert "NG" in warnings[0].msg
    assert not {"GB", "US", "CA", "ZZ"} & set(warnings[0].msg.replace(",", "").split())
