"""Paystack adapter — HTTP mocked with respx, webhook signature COMPUTED in-test (never
a pasted hex string) so re-serializing the body can't silently invalidate the fixture."""
import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import respx
from django.test import override_settings

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import (
    GatewayError,
    GatewayNotConfigured,
    InvalidSignature,
)
from apps.payments.gateways.paystack import API_BASE, PaystackGateway

pytestmark = pytest.mark.django_db

SECRET = "sk_test_secret"


def _order_payment(ref="TC-400001"):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    order = OrderFactory(number=ref, country=ng, currency=ngn, reservation_reference=ref,
                         grand_total="1000.00", email="buyer@x.com")
    payment = PaymentFactory(order=order, currency=ngn, gateway="paystack",
                             gateway_reference=ref, amount="1000.00")
    return order, payment


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_initiate_returns_redirect_and_sends_kobo():
    order, payment = _order_payment()
    route = respx.post(f"{API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(200, json={
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/abc",
                     "access_code": "ac_1", "reference": order.reservation_reference},
        })
    )
    result = PaystackGateway().initiate(payment, order, return_url="https://shop/return")

    assert result.action == "redirect"
    assert result.data["redirect_url"] == "https://checkout.paystack.com/abc"
    sent = json.loads(route.calls.last.request.content)
    assert sent["amount"] == 100000  # 1000.00 NGN -> kobo
    assert sent["reference"] == order.reservation_reference
    assert sent["callback_url"] == "https://shop/return"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_initiate_5xx_raises_gateway_error():
    order, payment = _order_payment()
    respx.post(f"{API_BASE}/transaction/initialize").mock(return_value=httpx.Response(502))
    with pytest.raises(GatewayError):
        PaystackGateway().initiate(payment, order)


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_verify_success_maps_amount_and_currency():
    order, payment = _order_payment()
    respx.get(f"{API_BASE}/transaction/verify/{payment.gateway_reference}").mock(
        return_value=httpx.Response(200, json={
            "status": True,
            "data": {"status": "success", "amount": 100000, "currency": "NGN"},
        })
    )
    result = PaystackGateway().verify(payment)
    assert result.status == "succeeded"
    assert result.amount == Decimal("1000.00")
    assert result.currency == "NGN"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_verify_failed_maps_failed():
    order, payment = _order_payment()
    respx.get(f"{API_BASE}/transaction/verify/{payment.gateway_reference}").mock(
        return_value=httpx.Response(200, json={"status": True, "data": {"status": "failed"}})
    )
    assert PaystackGateway().verify(payment).status == "failed"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_refund_is_pending_until_webhook():
    order, payment = _order_payment()
    respx.post(f"{API_BASE}/refund").mock(
        return_value=httpx.Response(200, json={
            "status": True, "data": {"id": 77, "status": "pending"},
        })
    )
    result = PaystackGateway().refund(payment, Decimal("1000.00"), reason="oops")
    assert result.status == "pending"
    assert result.gateway_reference == "77"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
def test_parse_webhook_valid_signature():
    body = {"event": "charge.success",
            "data": {"id": 123, "reference": "TC-400001", "amount": 100000}}
    raw = json.dumps(body).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
    request = SimpleNamespace(body=raw, headers={"x-paystack-signature": sig})

    event = PaystackGateway().parse_webhook(request)
    assert event.event_type == "charge.success"
    assert event.event_id == "charge.success:123"
    assert event.gateway_reference == "TC-400001"


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
def test_parse_webhook_bad_signature_raises():
    raw = json.dumps({"event": "charge.success", "data": {}}).encode()
    request = SimpleNamespace(body=raw, headers={"x-paystack-signature": "deadbeef"})
    with pytest.raises(InvalidSignature):
        PaystackGateway().parse_webhook(request)


@override_settings(PAYSTACK_SECRET_KEY="")
def test_missing_key_raises_not_configured():
    order, payment = _order_payment()
    with pytest.raises(GatewayNotConfigured):
        PaystackGateway().initiate(payment, order)
