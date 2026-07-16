"""Stripe adapter. The Stripe SDK uses its own HTTP client (not httpx), so respx can't
intercept it — we monkeypatch the SDK surface instead, which is the conventional way to
test Stripe integrations. Includes the ZERO-DECIMAL currency path (Fable 5 ruling: prove
it regardless of whether the store sells in such a currency today)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from django.test import override_settings

from apps.core.models import Country, Currency
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import (
    GatewayError,
    GatewayNotConfigured,
    InvalidSignature,
)
from apps.payments.gateways.stripe_gateway import StripeGateway

pytestmark = pytest.mark.django_db

KEY = "sk_test_stripe"
WH_SECRET = "whsec_test"


def _order_payment(currency=None, amount="1000.00", ref="pi_123"):
    ng = Country.objects.get(code="NG")
    currency = currency or ng.currency
    order = OrderFactory(number="TC-600001", country=ng, currency=currency,
                         reservation_reference="TC-600001", grand_total=amount,
                         email="b@x.com")
    payment = PaymentFactory(order=order, currency=currency, gateway="stripe",
                             gateway_reference=ref, amount=amount,
                             idempotency_key="idem-stripe-1")
    return order, payment


@override_settings(STRIPE_SECRET_KEY=KEY)
def test_initiate_returns_client_secret_and_minor_units(monkeypatch):
    order, payment = _order_payment()
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="pi_123", client_secret="pi_123_secret")

    monkeypatch.setattr(stripe.PaymentIntent, "create", _create)
    result = StripeGateway().initiate(payment, order)

    assert result.action == "client_secret"
    assert result.reference == "pi_123"
    assert result.data["client_secret"] == "pi_123_secret"
    assert captured["amount"] == 100000  # 1000.00 NGN -> minor units
    assert captured["currency"] == "ngn"
    # Stripe's native idempotency mechanism is the header key, not the reference.
    assert captured["idempotency_key"] == "idem-stripe-1"


@override_settings(STRIPE_SECRET_KEY=KEY)
def test_initiate_zero_decimal_currency_sends_plain_integer(monkeypatch):
    jpy = Currency.objects.create(code="JPY", symbol="¥", decimal_places=0)
    order, payment = _order_payment(currency=jpy, amount="5000")
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="pi_jpy", client_secret="sec")

    monkeypatch.setattr(stripe.PaymentIntent, "create", _create)
    StripeGateway().initiate(payment, order)

    assert captured["amount"] == 5000  # NOT 500000 — JPY has no minor unit
    assert captured["currency"] == "jpy"


@override_settings(STRIPE_SECRET_KEY=KEY)
def test_verify_succeeded_maps_amount(monkeypatch):
    order, payment = _order_payment()
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", lambda *a, **k: SimpleNamespace(
        id="pi_123", status="succeeded", amount=100000, amount_received=100000, currency="ngn",
    ))
    result = StripeGateway().verify(payment)
    assert result.status == "succeeded"
    assert result.amount == Decimal("1000.00")
    assert result.currency == "NGN"


@override_settings(STRIPE_SECRET_KEY=KEY)
@pytest.mark.parametrize("intent_status,expected", [
    ("processing", "pending"),
    ("requires_action", "pending"),
    ("canceled", "failed"),
])
def test_verify_status_mapping(monkeypatch, intent_status, expected):
    order, payment = _order_payment()
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", lambda *a, **k: SimpleNamespace(
        id="pi_123", status=intent_status, amount=100000, amount_received=0, currency="ngn",
    ))
    assert StripeGateway().verify(payment).status == expected


@override_settings(STRIPE_SECRET_KEY=KEY)
def test_verify_stripe_error_raises_gateway_error(monkeypatch):
    order, payment = _order_payment()

    def _boom(*a, **k):
        raise stripe.APIConnectionError("down")

    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", _boom)
    with pytest.raises(GatewayError):
        StripeGateway().verify(payment)


@override_settings(STRIPE_SECRET_KEY=KEY)
def test_refund_succeeded(monkeypatch):
    order, payment = _order_payment()
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="re_1", status="succeeded")

    monkeypatch.setattr(stripe.Refund, "create", _create)
    result = StripeGateway().refund(payment, Decimal("250.00"), reason="partial")

    assert result.status == "succeeded"
    assert result.gateway_reference == "re_1"
    assert captured["amount"] == 25000  # partial, in minor units
    assert captured["payment_intent"] == "pi_123"


@override_settings(STRIPE_WEBHOOK_SECRET=WH_SECRET)
def test_parse_webhook_payment_intent_event(monkeypatch):
    event = {"id": "evt_1", "type": "payment_intent.succeeded",
             "data": {"object": {"object": "payment_intent", "id": "pi_123"}}}
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **k: event)
    request = SimpleNamespace(body=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})

    parsed = StripeGateway().parse_webhook(request)
    assert parsed.event_id == "evt_1"
    assert parsed.event_type == "payment_intent.succeeded"
    assert parsed.gateway_reference == "pi_123"


@override_settings(STRIPE_WEBHOOK_SECRET=WH_SECRET)
def test_parse_webhook_charge_event_uses_payment_intent_field(monkeypatch):
    event = {"id": "evt_2", "type": "charge.refunded",
             "data": {"object": {"object": "charge", "id": "ch_9", "payment_intent": "pi_123"}}}
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **k: event)
    request = SimpleNamespace(body=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})

    parsed = StripeGateway().parse_webhook(request)
    assert parsed.gateway_reference == "pi_123"  # not the charge id


@override_settings(STRIPE_WEBHOOK_SECRET=WH_SECRET)
def test_parse_webhook_bad_signature_raises(monkeypatch):
    def _boom(*a, **k):
        raise stripe.SignatureVerificationError("bad", "sig_header")

    monkeypatch.setattr(stripe.Webhook, "construct_event", _boom)
    request = SimpleNamespace(body=b"{}", headers={"Stripe-Signature": "bad"})
    with pytest.raises(InvalidSignature):
        StripeGateway().parse_webhook(request)


@override_settings(STRIPE_SECRET_KEY="")
def test_missing_key_raises_not_configured():
    order, payment = _order_payment()
    with pytest.raises(GatewayNotConfigured):
        StripeGateway().initiate(payment, order)
