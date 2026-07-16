"""PayPal adapter: OAuth token caching, major-unit decimal strings, the APPROVED ->
capture -> COMPLETED path, and hosted webhook signature verification."""
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import GatewayNotConfigured, InvalidSignature
from apps.payments.gateways.paypal import PayPalGateway

pytestmark = pytest.mark.django_db

BASE = "https://api-m.sandbox.paypal.com"
SETTINGS = dict(
    PAYPAL_CLIENT_ID="cid", PAYPAL_CLIENT_SECRET="csec",
    PAYPAL_API_BASE=BASE, PAYPAL_WEBHOOK_ID="wh_1",
)


@pytest.fixture(autouse=True)
def _clear_token_cache():
    cache.delete("paypal:oauth_token")
    yield
    cache.delete("paypal:oauth_token")


def _mock_token():
    return respx.post(f"{BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    )


def _order_payment(ref="PAYPAL-ORDER-1", amount="10.99"):
    ng = Country.objects.get(code="NG")
    gbp = ng.currency  # any Currency row works; PayPal takes the code from payment.currency
    order = OrderFactory(number="TC-900001", country=ng, currency=gbp,
                         reservation_reference="TC-900001", grand_total=amount, email="b@x.com")
    payment = PaymentFactory(order=order, currency=gbp, gateway="paypal",
                             gateway_reference=ref, amount=amount)
    return order, payment


@override_settings(**SETTINGS)
@respx.mock
def test_initiate_sends_major_unit_string_and_returns_approval_link():
    order, payment = _order_payment()
    _mock_token()
    route = respx.post(f"{BASE}/v2/checkout/orders").mock(
        return_value=httpx.Response(201, json={
            "id": "PAYPAL-ORDER-1",
            "links": [{"rel": "self", "href": "x"},
                      {"rel": "approve", "href": "https://paypal.com/approve/1"}],
        })
    )
    result = PayPalGateway().initiate(payment, order, return_url="https://shop/ret")

    assert result.action == "redirect"
    assert result.reference == "PAYPAL-ORDER-1"
    assert result.data["redirect_url"] == "https://paypal.com/approve/1"
    sent = json.loads(route.calls.last.request.content)
    assert sent["intent"] == "CAPTURE"
    # Major-unit DECIMAL STRING — not an integer, not minor units.
    assert sent["purchase_units"][0]["amount"]["value"] == "10.99"


@override_settings(**SETTINGS)
@respx.mock
def test_oauth_token_is_cached_across_calls():
    order, payment = _order_payment()
    token_route = _mock_token()
    respx.get(f"{BASE}/v2/checkout/orders/{payment.gateway_reference}").mock(
        return_value=httpx.Response(200, json={
            "id": "PAYPAL-ORDER-1", "status": "COMPLETED",
            "purchase_units": [{"amount": {"value": "10.99", "currency_code": "NGN"}}],
        })
    )
    gw = PayPalGateway()
    gw.verify(payment)
    gw.verify(payment)

    assert token_route.call_count == 1  # second verify reused the cached token


@override_settings(**SETTINGS)
@respx.mock
def test_verify_completed():
    order, payment = _order_payment()
    _mock_token()
    respx.get(f"{BASE}/v2/checkout/orders/{payment.gateway_reference}").mock(
        return_value=httpx.Response(200, json={
            "id": "PAYPAL-ORDER-1", "status": "COMPLETED",
            "purchase_units": [{"amount": {"value": "10.99", "currency_code": "NGN"}}],
        })
    )
    result = PayPalGateway().verify(payment)
    assert result.status == "succeeded"
    assert result.amount == Decimal("10.99")
    assert result.currency == "NGN"


@override_settings(**SETTINGS)
@respx.mock
def test_verify_approved_triggers_capture_then_reports_completed():
    order, payment = _order_payment()
    _mock_token()
    state = {"n": 0}

    def _get(request):
        state["n"] += 1
        status = "APPROVED" if state["n"] == 1 else "COMPLETED"
        return httpx.Response(200, json={
            "id": "PAYPAL-ORDER-1", "status": status,
            "purchase_units": [{"amount": {"value": "10.99", "currency_code": "NGN"}}],
        })

    respx.get(f"{BASE}/v2/checkout/orders/{payment.gateway_reference}").mock(side_effect=_get)
    capture = respx.post(f"{BASE}/v2/checkout/orders/{payment.gateway_reference}/capture").mock(
        return_value=httpx.Response(201, json={"status": "COMPLETED"})
    )

    result = PayPalGateway().verify(payment)
    assert capture.called  # APPROVED money isn't ours until captured
    assert result.status == "succeeded"


@override_settings(**SETTINGS)
@respx.mock
def test_parse_webhook_valid_signature():
    _mock_token()
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").mock(
        return_value=httpx.Response(200, json={"verification_status": "SUCCESS"})
    )
    body = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "CAP-1",
                         "supplementary_data": {"related_ids": {"order_id": "PAYPAL-ORDER-1"}}}}
    request = SimpleNamespace(body=json.dumps(body).encode(), headers={})

    event = PayPalGateway().parse_webhook(request)
    assert event.event_id == "WH-1"
    assert event.event_type == "PAYMENT.CAPTURE.COMPLETED"
    assert event.gateway_reference == "PAYPAL-ORDER-1"  # not the capture id


@override_settings(**SETTINGS)
@respx.mock
def test_parse_webhook_failed_verification_raises():
    _mock_token()
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").mock(
        return_value=httpx.Response(200, json={"verification_status": "FAILURE"})
    )
    request = SimpleNamespace(body=json.dumps({"id": "WH-2"}).encode(), headers={})
    with pytest.raises(InvalidSignature):
        PayPalGateway().parse_webhook(request)


@override_settings(PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET="", PAYPAL_API_BASE=BASE)
def test_missing_creds_raises_not_configured():
    order, payment = _order_payment()
    with pytest.raises(GatewayNotConfigured):
        PayPalGateway().initiate(payment, order)
