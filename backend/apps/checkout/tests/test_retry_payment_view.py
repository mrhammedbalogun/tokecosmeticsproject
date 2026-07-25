"""POST /api/v1/orders/{number}/pay/ — the customer-facing re-pay endpoint.

Returns the SAME payment envelope as the checkout 201 so the storefront's PaymentLauncher
can drive it without a second code path.
"""
import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import GatewayError, InitiateResult, PaymentGateway
from apps.payments.models import CountryPaymentGateway

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    code = "fakeview"
    supported_currencies = {"NGN"}
    fail = False

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        if type(self).fail:
            raise GatewayError("provider down")
        return InitiateResult(action="redirect", reference="FV-1",
                              data={"access_code": "ac_retry"})


@pytest.fixture
def fakeview(monkeypatch):
    _FakeGateway.fail = False
    monkeypatch.setitem(registry._REGISTRY, "fakeview", _FakeGateway())
    ng = Country.objects.get(code="NG")
    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="fakeview", defaults={"is_active": True, "sort_order": 9})
    return _FakeGateway


@pytest.fixture
def order_and_client(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="v@x.com", password="pw")
    order = OrderFactory(number="TC-810001", user=user, country=ng, currency=ng.currency,
                         reservation_reference="TC-810001", grand_total="5000.00",
                         status="pending_payment", email="v@x.com",
                         reservation_expires_at=timezone.now() + timedelta(minutes=15))
    PaymentFactory(order=order, currency=ng.currency, gateway="paystack",
                   amount="5000.00", gateway_reference="PS-OLD", status="initiated")
    client = APIClient()
    client.force_authenticate(user)
    return order, client, user


URL = "/api/v1/orders/TC-810001/pay/"


def test_returns_the_checkout_payment_envelope(order_and_client, fakeview):
    _, client, _ = order_and_client
    resp = client.post(URL, {"payment_gateway": "fakeview"}, format="json",
                       HTTP_IDEMPOTENCY_KEY="v-1")

    assert resp.status_code == 200, resp.data
    assert resp.data["order_number"] == "TC-810001"
    assert resp.data["payment"] == {
        "gateway": "fakeview", "action": "redirect", "reference": "FV-1",
        "data": {"access_code": "ac_retry"},
    }


def test_requires_an_idempotency_key(order_and_client, fakeview):
    _, client, _ = order_and_client
    resp = client.post(URL, {"payment_gateway": "fakeview"}, format="json")
    assert resp.status_code == 400
    assert resp.data["error"] == "idempotency_key_required"


def test_requires_authentication(order_and_client, fakeview):
    resp = APIClient().post(URL, {"payment_gateway": "fakeview"}, format="json",
                            HTTP_IDEMPOTENCY_KEY="v-2")
    assert resp.status_code in (401, 403)


def test_another_customer_gets_404_not_a_leak(order_and_client, fakeview, django_user_model):
    other = django_user_model.objects.create_user(email="nosy@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(other)

    resp = client.post(URL, {"payment_gateway": "fakeview"}, format="json",
                       HTTP_IDEMPOTENCY_KEY="v-3")
    assert resp.status_code == 404
    assert resp.data["error"] == "order_not_found"


def test_unavailable_gateway_is_a_400(order_and_client, fakeview):
    _, client, _ = order_and_client
    resp = client.post(URL, {"payment_gateway": "stripe"}, format="json",
                       HTTP_IDEMPOTENCY_KEY="v-4")
    assert resp.status_code == 400
    assert resp.data["error"] == "gateway_unavailable"


def test_already_paid_order_is_a_409(order_and_client, fakeview):
    order, client, _ = order_and_client
    order.status = "processing"
    order.save(update_fields=["status"])

    resp = client.post(URL, {"payment_gateway": "fakeview"}, format="json",
                       HTTP_IDEMPOTENCY_KEY="v-5")
    assert resp.status_code == 409
    assert resp.data["error"] == "order_not_payable"


def test_gateway_outage_is_a_502_and_stays_retryable(order_and_client, fakeview):
    """The order must remain payable after a provider outage — the customer retries with
    the same key, which resumes the attempt that never got a reference."""
    order, client, _ = order_and_client
    fakeview.fail = True

    resp = client.post(URL, {"payment_gateway": "fakeview"}, format="json",
                       HTTP_IDEMPOTENCY_KEY="v-6")
    assert resp.status_code == 502
    assert resp.data["error"] == "gateway_error"

    order.refresh_from_db()
    assert order.status == "pending_payment"

    fakeview.fail = False
    again = client.post(URL, {"payment_gateway": "fakeview"}, format="json",
                        HTTP_IDEMPOTENCY_KEY="v-6")
    assert again.status_code == 200
    assert again.data["payment"]["reference"] == "FV-1"
    assert order.payments.count() == 2  # the failed attempt was resumed, not duplicated
