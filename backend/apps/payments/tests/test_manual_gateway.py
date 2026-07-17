"""bank_transfer is a MANUAL gateway: there is no machine to ask whether the money
landed. It must say so in the gateway vocabulary rather than exploding."""
import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import GatewayError, ManualVerificationOnly
from apps.payments.gateways.registry import get_gateway

pytestmark = pytest.mark.django_db


def test_manual_verification_only_is_a_gateway_error():
    """So every existing caller that already degrades gracefully on GatewayError keeps
    doing so, instead of each one growing a special case."""
    assert issubclass(ManualVerificationOnly, GatewayError)


def test_bank_transfer_verify_declines_instead_of_raising_notimplementederror():
    with pytest.raises(ManualVerificationOnly):
        get_gateway("bank_transfer").verify(payment=None)


def test_customer_verifying_a_bank_transfer_gets_a_status_not_a_500(django_user_model):
    """The customer returning to the site and hitting "check my payment" must get their
    order's current state. NotImplementedError is not a GatewayError, so it escaped the
    view's handler and 500'd."""
    user = django_user_model.objects.create_user(email="bt@x.com", password="pw12345!")
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number="TC-950001", country=ng, currency=ng.currency,
                         user=user, email=user.email, status="pending_payment",
                         grand_total="1000.00")
    PaymentFactory(order=order, currency=ng.currency, gateway="bank_transfer",
                   gateway_reference="TC-950001", amount="1000.00", status="initiated")

    client = APIClient()
    client.force_authenticate(user)
    resp = client.post("/api/v1/payments/TC-950001/verify/")

    assert resp.status_code == 200
    assert resp.data["order_status"] == "pending_payment"
    assert resp.data["payment_status"] == "initiated"  # unchanged — nothing was verified
