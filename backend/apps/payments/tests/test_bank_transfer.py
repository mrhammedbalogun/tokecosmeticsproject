import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.registry import get_gateway
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db


def test_bank_transfer_initiate_returns_details():
    # Seed migration already created NG + NGN — fetch, don't re-create (avoids PK collision).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    order = OrderFactory(number="TC-100001", country=ng, currency=ngn,
                         reservation_reference="TC-100001", grand_total="5000.00")
    payment = PaymentFactory(order=order, currency=ngn, gateway="bank_transfer")

    result = get_gateway("bank_transfer").initiate(payment, order)

    assert result.action == "bank_details"
    assert result.data["account_number"] == "0123456789"
    assert result.data["reference"] == "TC-100001"
