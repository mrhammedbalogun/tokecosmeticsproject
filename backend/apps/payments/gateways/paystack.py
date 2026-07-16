"""Paystack — the Nigeria revenue path and the first networked gateway.

Amounts are in KOBO (minor units). Idempotency on initiate is the transaction
`reference` itself: Paystack dedupes on it, so a retry after a 5xx with the same
attempt-suffixed reference returns the same transaction rather than double-charging.
Webhook auth is HMAC-SHA512 of the RAW body with the secret key (x-paystack-signature).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings

from apps.payments.gateways import _http
from apps.payments.gateways.base import (
    GatewayError,
    GatewayNotConfigured,
    InitiateResult,
    InvalidSignature,
    ParsedEvent,
    PaymentGateway,
    RefundResult,
    VerifyResult,
)
from apps.payments.money import from_minor, to_minor

API_BASE = "https://api.paystack.co"


class PaystackGateway(PaymentGateway):
    code = "paystack"
    supported_currencies = {"NGN", "USD", "GHS", "ZAR", "KES"}

    # --- config (lazy: never read keys at import) ---------------------------

    def _secret(self) -> str:
        key = settings.PAYSTACK_SECRET_KEY
        if not key:
            raise GatewayNotConfigured("PAYSTACK_SECRET_KEY is not set")
        return key

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._secret()}", "Content-Type": "application/json"}

    # --- API -----------------------------------------------------------------

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        payload = {
            "email": order.email,
            "amount": to_minor(payment.amount, payment.currency),  # kobo
            "currency": payment.currency_id,
            "reference": order.reservation_reference,  # our attempt-suffixed idempotency key
        }
        if return_url:
            payload["callback_url"] = return_url
        resp = _http.request("POST", f"{API_BASE}/transaction/initialize",
                             headers=self._headers(), json=payload)
        if resp.status_code >= 500:
            raise GatewayError(f"Paystack initialize {resp.status_code}")
        body = resp.json()
        if not body.get("status"):
            raise GatewayError(f"Paystack initialize rejected: {body.get('message')}")
        data = body["data"]
        return InitiateResult(
            action="redirect",
            reference=data["reference"],
            data={"redirect_url": data["authorization_url"], "access_code": data["access_code"]},
        )

    def verify(self, payment) -> VerifyResult:
        ref = payment.gateway_reference
        resp = _http.request("GET", f"{API_BASE}/transaction/verify/{ref}", headers=self._headers())
        if resp.status_code >= 500:
            raise GatewayError(f"Paystack verify {resp.status_code}")
        data = resp.json().get("data") or {}
        status = {"success": "succeeded", "failed": "failed"}.get(data.get("status"), "pending")
        currency = data.get("currency", payment.currency_id)
        amount = from_minor(data.get("amount", 0), payment.currency)
        return VerifyResult(status=status, amount=amount, currency=currency, raw=data)

    def refund(self, payment, amount, reason: str = "") -> RefundResult:
        payload = {
            "transaction": payment.gateway_reference,
            "amount": to_minor(amount, payment.currency),  # kobo; omit for full refund
        }
        if reason:
            payload["merchant_note"] = reason
        resp = _http.request("POST", f"{API_BASE}/refund", headers=self._headers(), json=payload)
        if resp.status_code >= 500:
            raise GatewayError(f"Paystack refund {resp.status_code}")
        body = resp.json()
        data = body.get("data") or {}
        # Paystack refunds are asynchronous: created as pending, completed via webhook.
        status = "succeeded" if data.get("status") in {"processed", "success"} else "pending"
        if not body.get("status"):
            status = "failed"
        return RefundResult(status=status, gateway_reference=str(data.get("id", "")), raw=data)

    def parse_webhook(self, request) -> ParsedEvent:
        raw = request.body  # RAW bytes — signature is over exactly these
        signature = request.headers.get("x-paystack-signature", "")
        expected = hmac.new(self._secret().encode(), raw, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignature("Paystack signature mismatch")
        body = json.loads(raw)
        event_type = body.get("event", "")
        data = body.get("data") or {}
        # Paystack sends no event-id header; (event_type, transaction id) is unique+stable.
        event_id = f"{event_type}:{data.get('id', '')}"
        if event_type.startswith("refund."):
            kind, refund_reference = "refund", str(data.get("id", ""))
            # Refund payloads nest the original transaction under `transaction`.
            reference = (data.get("transaction") or {}).get("reference", "") or data.get(
                "transaction_reference", ""
            )
        elif event_type.startswith("charge."):
            kind, refund_reference = "payment", ""
            reference = data.get("reference", "")
        else:
            kind, refund_reference = "other", ""
            reference = data.get("reference", "")
        return ParsedEvent(
            event_id=event_id,
            event_type=event_type,
            gateway_reference=reference,
            raw=body,
            kind=kind,
            refund_reference=refund_reference,
        )
