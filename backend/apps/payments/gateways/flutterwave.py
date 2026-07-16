"""Flutterwave — the second Nigerian rail (fallback/alternative to Paystack).

Two traps this adapter exists to encapsulate:

1. Amounts are MAJOR units (plain NGN), NOT kobo — the opposite of Paystack. This is the
   single easiest way to charge a customer 100x too much, so it is asserted in tests.
2. Flutterwave sends NO reliable webhook event id. Our WebhookEvent dedupe ledger needs
   one, so we DERIVE a deterministic id: sha256(tx_ref:event:status). Same event
   redelivered => same id => the unique constraint dedupes it.

Webhook auth is a simple shared-secret equality check on the `verif-hash` header (not an
HMAC over the body) — that's Flutterwave's design, not an oversight here. It's compared
with compare_digest to avoid a timing oracle, and the money truth still comes from
verify(), so the weak webhook auth can't fulfil an order on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

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

API_BASE = "https://api.flutterwave.com/v3"


class FlutterwaveGateway(PaymentGateway):
    code = "flutterwave"
    supported_currencies = {"NGN", "USD", "GBP", "GHS", "KES"}

    # --- config (lazy: never read keys at import) ---------------------------

    def _secret(self) -> str:
        key = settings.FLUTTERWAVE_SECRET_KEY
        if not key:
            raise GatewayNotConfigured("FLUTTERWAVE_SECRET_KEY is not set")
        return key

    def _secret_hash(self) -> str:
        value = settings.FLUTTERWAVE_SECRET_HASH
        if not value:
            raise GatewayNotConfigured("FLUTTERWAVE_SECRET_HASH is not set")
        return value

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._secret()}", "Content-Type": "application/json"}

    # --- API -----------------------------------------------------------------

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        # Flutterwave renders a HOSTED payment page — brand it so the customer doesn't
        # land on an unbranded form mid-checkout. `logo` must be a public URL.
        customizations = {"title": settings.BRAND_NAME}
        if settings.BRAND_LOGO_URL:
            customizations["logo"] = settings.BRAND_LOGO_URL
        payload = {
            "tx_ref": order.reservation_reference,  # our idempotency handle
            "amount": str(payment.amount),  # MAJOR units — not to_minor()
            "currency": payment.currency_id,
            "customer": {"email": order.email},
            "customizations": customizations,
        }
        if return_url:
            payload["redirect_url"] = return_url
        resp = _http.request("POST", f"{API_BASE}/payments", headers=self._headers(),
                             json=payload)
        if resp.status_code >= 500:
            raise GatewayError(f"Flutterwave payments {resp.status_code}")
        body = resp.json()
        if body.get("status") != "success":
            raise GatewayError(f"Flutterwave rejected: {body.get('message')}")
        return InitiateResult(
            action="redirect",
            reference=order.reservation_reference,
            data={"redirect_url": body["data"]["link"]},
        )

    def verify(self, payment) -> VerifyResult:
        resp = _http.request(
            "GET", f"{API_BASE}/transactions/verify_by_reference",
            headers=self._headers(), params={"tx_ref": payment.gateway_reference},
        )
        if resp.status_code >= 500:
            raise GatewayError(f"Flutterwave verify {resp.status_code}")
        data = resp.json().get("data") or {}
        status = {"successful": "succeeded", "failed": "failed"}.get(data.get("status"), "pending")
        return VerifyResult(
            status=status,
            amount=Decimal(str(data.get("amount", "0"))),  # MAJOR units
            currency=data.get("currency", payment.currency_id),
            raw=data,
        )

    def refund(self, payment, amount, reason: str = "") -> RefundResult:
        # Refunds address Flutterwave's own transaction id, not our tx_ref. verify()
        # stores it on the Payment; without it we cannot refund.
        flw_id = (payment.raw_response or {}).get("verify", {}).get("id")
        if not flw_id:
            raise GatewayError(
                "Flutterwave transaction id unknown (verify the payment before refunding)"
            )
        resp = _http.request("POST", f"{API_BASE}/transactions/{flw_id}/refund",
                             headers=self._headers(), json={"amount": str(amount)})
        if resp.status_code >= 500:
            raise GatewayError(f"Flutterwave refund {resp.status_code}")
        body = resp.json()
        data = body.get("data") or {}
        if body.get("status") != "success":
            return RefundResult(status="failed", raw=data)
        # Flutterwave refunds settle asynchronously — completed via webhook.
        status = "succeeded" if data.get("status") == "completed" else "pending"
        return RefundResult(status=status, gateway_reference=str(data.get("id", "")), raw=data)

    def parse_webhook(self, request) -> ParsedEvent:
        raw = request.body
        supplied = request.headers.get("verif-hash", "")
        if not hmac.compare_digest(supplied, self._secret_hash()):
            raise InvalidSignature("Flutterwave verif-hash mismatch")
        body = json.loads(raw)
        data = body.get("data") or {}
        event_type = body.get("event", "")
        tx_ref = data.get("tx_ref", "")
        # DERIVED event id — Flutterwave gives us none. Deterministic so a redelivery of
        # the same event collapses onto the same WebhookEvent row.
        event_id = hashlib.sha256(
            f"{tx_ref}:{event_type}:{data.get('status', '')}".encode()
        ).hexdigest()
        if "refund" in event_type:
            kind, refund_reference = "refund", str(data.get("id", ""))
        elif event_type.startswith("charge."):
            kind, refund_reference = "payment", ""
        else:
            kind, refund_reference = "other", ""
        return ParsedEvent(event_id=event_id, event_type=event_type,
                           gateway_reference=tx_ref, raw=body,
                           kind=kind, refund_reference=refund_reference)
