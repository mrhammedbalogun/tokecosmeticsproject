"""bank_transfer is the only live method at launch and its initiate() IS the payment
page. Four markets are live, so the details must come from the order's own country — and
when there is no account to show, the customer must see an error, never a blank field
they would wire real money into."""
import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import GatewayNotConfigured
from apps.payments.gateways.registry import get_gateway
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db


def _make_account(code, **kw):
    country = Country.objects.get(code=code)
    defaults = dict(
        country=country, currency=country.currency, bank_name=f"{code} Bank",
        account_name="Toke Cosmetics Ltd", account_number=f"{code}-0001",
    )
    return BankAccount.objects.create(**{**defaults, **kw})


def _order_payment(code, number):
    # Seed migration already created NG/GB/US/CA — fetch, don't re-create (PK collision).
    country = Country.objects.get(code=code)
    order = OrderFactory(number=number, country=country, currency=country.currency,
                         reservation_reference=number, grand_total="5000.00")
    payment = PaymentFactory(order=order, currency=country.currency, gateway="bank_transfer")
    return payment, order


def test_initiate_returns_the_account_for_the_orders_country():
    _make_account("NG")
    _make_account("GB", extra={"sort_code": "04-00-04"})
    payment, order = _order_payment("GB", "TC-100001")

    result = get_gateway("bank_transfer").initiate(payment, order)

    assert result.action == "bank_details"
    assert result.data["account_number"] == "GB-0001"      # NOT the NG account
    assert result.data["sort_code"] == "04-00-04"          # per-market field carried through
    assert result.data["reference"] == "TC-100001"


def test_initiate_refuses_when_the_country_has_no_account():
    _make_account("NG")
    payment, order = _order_payment("CA", "TC-100002")

    with pytest.raises(GatewayNotConfigured):
        get_gateway("bank_transfer").initiate(payment, order)


def test_initiate_refuses_when_the_account_is_deactivated():
    _make_account("NG", is_active=False)
    payment, order = _order_payment("NG", "TC-100003")

    # Never render a blank account number — the customer would wire into nowhere.
    with pytest.raises(GatewayNotConfigured):
        get_gateway("bank_transfer").initiate(payment, order)
