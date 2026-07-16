"""Flutterwave adapter. The headline assertion: amounts go out in MAJOR units (plain
NGN), the opposite of Paystack's kobo — getting this wrong charges 100x. Also proves the
DERIVED deterministic webhook event id, since Flutterwave sends none."""
import hashlib
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
from apps.payments.gateways.flutterwave import API_BASE, FlutterwaveGateway

pytestmark = pytest.mark.django_db

SECRET = "FLWSECK_TEST-x"
HASH = "my-secret-hash"


def _order_payment(ref="TC-800001", amount="1000.00"):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    order = OrderFactory(number=ref, country=ng, currency=ngn, reservation_reference=ref,
                         grand_total=amount, email="b@x.com")
    payment = PaymentFactory(order=order, currency=ngn, gateway="flutterwave",
                             gateway_reference=ref, amount=amount)
    return order, payment


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET)
@respx.mock
def test_initiate_sends_major_units_not_minor():
    order, payment = _order_payment()
    route = respx.post(f"{API_BASE}/payments").mock(
        return_value=httpx.Response(200, json={
            "status": "success", "data": {"link": "https://checkout.flutterwave.com/x"},
        })
    )
    result = FlutterwaveGateway().initiate(payment, order, return_url="https://shop/ret")

    assert result.action == "redirect"
    assert result.data["redirect_url"] == "https://checkout.flutterwave.com/x"
    sent = json.loads(route.calls.last.request.content)
    assert sent["amount"] == "1000.00"  # MAJOR units — NOT 100000 kobo
    assert sent["tx_ref"] == order.reservation_reference
    assert sent["redirect_url"] == "https://shop/ret"


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET, BRAND_NAME="Toké Cosmetics",
                   BRAND_LOGO_URL="https://tokecosmetics.com/logo.png")
@respx.mock
def test_initiate_brands_the_hosted_page():
    order, payment = _order_payment()
    route = respx.post(f"{API_BASE}/payments").mock(
        return_value=httpx.Response(200, json={
            "status": "success", "data": {"link": "https://checkout.flutterwave.com/x"},
        })
    )
    FlutterwaveGateway().initiate(payment, order)

    sent = json.loads(route.calls.last.request.content)
    assert sent["customizations"]["title"] == "Toké Cosmetics"
    assert sent["customizations"]["logo"] == "https://tokecosmetics.com/logo.png"


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET, BRAND_LOGO_URL="")
@respx.mock
def test_initiate_omits_logo_when_unset():
    order, payment = _order_payment()
    route = respx.post(f"{API_BASE}/payments").mock(
        return_value=httpx.Response(200, json={
            "status": "success", "data": {"link": "https://x"},
        })
    )
    FlutterwaveGateway().initiate(payment, order)
    assert "logo" not in json.loads(route.calls.last.request.content)["customizations"]


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET)
@respx.mock
def test_verify_successful_maps_major_amount():
    order, payment = _order_payment()
    respx.get(f"{API_BASE}/transactions/verify_by_reference").mock(
        return_value=httpx.Response(200, json={
            "status": "success",
            "data": {"id": 55, "status": "successful", "amount": 1000, "currency": "NGN"},
        })
    )
    result = FlutterwaveGateway().verify(payment)
    assert result.status == "succeeded"
    assert result.amount == Decimal("1000")  # already major units
    assert result.currency == "NGN"
    assert result.raw["id"] == 55  # stored so refund() can address the transaction


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET)
@respx.mock
def test_initiate_5xx_raises():
    order, payment = _order_payment()
    respx.post(f"{API_BASE}/payments").mock(return_value=httpx.Response(503))
    with pytest.raises(GatewayError):
        FlutterwaveGateway().initiate(payment, order)


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET)
@respx.mock
def test_refund_uses_flw_transaction_id_from_verify():
    order, payment = _order_payment()
    payment.raw_response = {"verify": {"id": 55}}
    payment.save(update_fields=["raw_response"])
    route = respx.post(f"{API_BASE}/transactions/55/refund").mock(
        return_value=httpx.Response(200, json={
            "status": "success", "data": {"id": 9, "status": "completed"},
        })
    )
    result = FlutterwaveGateway().refund(payment, Decimal("250.00"))
    assert result.status == "succeeded"
    assert json.loads(route.calls.last.request.content)["amount"] == "250.00"


@override_settings(FLUTTERWAVE_SECRET_KEY=SECRET)
def test_refund_without_verify_id_raises():
    order, payment = _order_payment()
    with pytest.raises(GatewayError):
        FlutterwaveGateway().refund(payment, Decimal("100.00"))


@override_settings(FLUTTERWAVE_SECRET_HASH=HASH)
def test_parse_webhook_derives_deterministic_event_id():
    body = {"event": "charge.completed",
            "data": {"tx_ref": "TC-800001", "status": "successful", "id": 55}}
    raw = json.dumps(body).encode()
    request = SimpleNamespace(body=raw, headers={"verif-hash": HASH})

    event = FlutterwaveGateway().parse_webhook(request)
    expected = hashlib.sha256(b"TC-800001:charge.completed:successful").hexdigest()
    assert event.event_id == expected
    assert event.gateway_reference == "TC-800001"
    # Deterministic: a redelivery of the same event collapses onto the same id.
    assert FlutterwaveGateway().parse_webhook(request).event_id == expected


@override_settings(FLUTTERWAVE_SECRET_HASH=HASH)
def test_parse_webhook_bad_hash_raises():
    raw = json.dumps({"event": "charge.completed", "data": {}}).encode()
    request = SimpleNamespace(body=raw, headers={"verif-hash": "wrong"})
    with pytest.raises(InvalidSignature):
        FlutterwaveGateway().parse_webhook(request)


@override_settings(FLUTTERWAVE_SECRET_KEY="")
def test_missing_key_raises_not_configured():
    order, payment = _order_payment()
    with pytest.raises(GatewayNotConfigured):
        FlutterwaveGateway().initiate(payment, order)
