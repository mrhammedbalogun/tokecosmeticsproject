"""Deploy-time visibility for the two ways a live gateway can be unusable in practice:
a networked one missing its keys (W001), and bank transfer missing its account (W002).

W002 is the one that bites at launch. Bank transfer is the only live method, and checkout
refuses an order for a manual gateway with no account rather than reserving stock and
503ing — so a market in that state cannot sell at all, silently. Better known at deploy
than from the customer who couldn't buy.
"""
import pytest

from apps.core.models import Country
from apps.payments.checks import gateway_configuration_check
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db

MARKETS = ["NG", "GB", "US", "CA", "ZZ"]


def _ids():
    return [w.id for w in gateway_configuration_check(None)]


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
