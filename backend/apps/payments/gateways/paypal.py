"""PayPal — the architectural oddball, built last on purpose.

Differences from the other three, all encapsulated here:
  * OAuth: every call needs a client-credentials bearer token. Cached in Django's cache
    (Redis in prod) with a safety buffer before expiry.
  * Amounts are MAJOR-unit decimal STRINGS ("10.99"), not integers.
  * Orders v2 with intent=CAPTURE: initiate() creates the order and returns the approval
    link; the money is captured server-side on return/webhook.
  * Signature: verified by POSTing to PayPal's hosted verify-webhook-signature endpoint
    rather than doing local cert-chain verification (Fable 5 ruling). One HTTPS call,
    officially supported, dramatically less code to hold wrong. Safe because verify()
    (GET the order, authenticated as us) is the real money gate — a weak webhook check
    cannot fulfil an order by itself.

The official SDKs are deprecated/archived/young, so this uses raw httpx over the five
REST endpoints we actually need.
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

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

_TOKEN_CACHE_KEY = "paypal:oauth_token"
_TOKEN_BUFFER_SECONDS = 60  # refresh a minute before PayPal says it expires

# PayPal Orders v2 status -> our normalized status.
_STATUS_MAP = {
    "COMPLETED": "succeeded",
    "APPROVED": "pending",   # approved by the buyer but not captured yet
    "CREATED": "pending",
    "SAVED": "pending",
    "PAYER_ACTION_REQUIRED": "pending",
    "VOIDED": "failed",
}


class PayPalGateway(PaymentGateway):
    code = "paypal"
    supported_currencies = {"GBP", "USD", "CAD", "EUR"}

    # --- config + auth (lazy: never read keys at import) --------------------

    def _creds(self) -> tuple[str, str]:
        client_id = settings.PAYPAL_CLIENT_ID
        secret = settings.PAYPAL_CLIENT_SECRET
        if not client_id or not secret:
            raise GatewayNotConfigured("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set")
        return client_id, secret

    def _base(self) -> str:
        return settings.PAYPAL_API_BASE.rstrip("/")

    def _token(self) -> str:
        cached = cache.get(_TOKEN_CACHE_KEY)
        if cached:
            return cached
        client_id, secret = self._creds()
        resp = _http.request(
            "POST", f"{self._base()}/v1/oauth2/token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise GatewayError(f"PayPal OAuth failed: {resp.status_code}")
        body = resp.json()
        token = body["access_token"]
        ttl = max(int(body.get("expires_in", 3600)) - _TOKEN_BUFFER_SECONDS, 60)
        cache.set(_TOKEN_CACHE_KEY, token, ttl)
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # --- API -----------------------------------------------------------------

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": order.number,
                "custom_id": order.reservation_reference,
                "amount": {
                    "currency_code": payment.currency_id,
                    "value": str(payment.amount),  # MAJOR-unit decimal string
                },
            }],
        }
        if return_url:
            payload["application_context"] = {"return_url": return_url, "cancel_url": return_url}
        resp = _http.request("POST", f"{self._base()}/v2/checkout/orders",
                             headers=self._headers(), json=payload)
        if resp.status_code >= 500:
            raise GatewayError(f"PayPal create order {resp.status_code}")
        if resp.status_code not in (200, 201):
            raise GatewayError(f"PayPal rejected create order: {resp.text}")
        body = resp.json()
        approve = next(
            (link["href"] for link in body.get("links", []) if link.get("rel") == "approve"), ""
        )
        return InitiateResult(action="redirect", reference=body["id"],
                              data={"redirect_url": approve})

    def capture(self, payment) -> dict:
        """Capture an approved order. Called on customer return / APPROVED webhook.
        PayPal treats a repeat capture of an already-captured order as an error, which
        verify() then reports as COMPLETED anyway — so this stays safe to retry."""
        resp = _http.request(
            "POST", f"{self._base()}/v2/checkout/orders/{payment.gateway_reference}/capture",
            headers=self._headers(), json={},
        )
        if resp.status_code >= 500:
            raise GatewayError(f"PayPal capture {resp.status_code}")
        return resp.json()

    def verify(self, payment) -> VerifyResult:
        resp = _http.request("GET", f"{self._base()}/v2/checkout/orders/{payment.gateway_reference}",
                             headers=self._headers())
        if resp.status_code >= 500:
            raise GatewayError(f"PayPal verify {resp.status_code}")
        body = resp.json()
        status = _STATUS_MAP.get(body.get("status"), "pending")

        # An APPROVED-but-uncaptured order needs a capture before the money is ours.
        if body.get("status") == "APPROVED":
            self.capture(payment)
            resp = _http.request(
                "GET", f"{self._base()}/v2/checkout/orders/{payment.gateway_reference}",
                headers=self._headers(),
            )
            body = resp.json()
            status = _STATUS_MAP.get(body.get("status"), "pending")

        unit = (body.get("purchase_units") or [{}])[0]
        amount_obj = unit.get("amount") or {}
        return VerifyResult(
            status=status,
            amount=Decimal(str(amount_obj.get("value", "0"))),
            currency=amount_obj.get("currency_code", payment.currency_id),
            raw={"id": body.get("id"), "status": body.get("status")},
        )

    def refund(self, payment, amount, reason: str = "") -> RefundResult:
        capture_id = (payment.raw_response or {}).get("capture_id")
        if not capture_id:
            capture_id = self._find_capture_id(payment)
        if not capture_id:
            raise GatewayError("PayPal capture id unknown — cannot refund")
        payload = {"amount": {"value": str(amount), "currency_code": payment.currency_id}}
        if reason:
            payload["note_to_payer"] = reason[:255]
        resp = _http.request("POST", f"{self._base()}/v2/payments/captures/{capture_id}/refund",
                             headers=self._headers(), json=payload)
        if resp.status_code >= 500:
            raise GatewayError(f"PayPal refund {resp.status_code}")
        if resp.status_code not in (200, 201):
            return RefundResult(status="failed", raw={"body": resp.text})
        body = resp.json()
        status = {"COMPLETED": "succeeded", "FAILED": "failed"}.get(body.get("status"), "pending")
        return RefundResult(status=status, gateway_reference=body.get("id", ""),
                            raw={"id": body.get("id"), "status": body.get("status")})

    def _find_capture_id(self, payment) -> str:
        """Dig the capture id out of the order — needed for refunds."""
        resp = _http.request("GET", f"{self._base()}/v2/checkout/orders/{payment.gateway_reference}",
                             headers=self._headers())
        if resp.status_code != 200:
            return ""
        unit = (resp.json().get("purchase_units") or [{}])[0]
        captures = (unit.get("payments") or {}).get("captures") or []
        return captures[0].get("id", "") if captures else ""

    def parse_webhook(self, request) -> ParsedEvent:
        webhook_id = settings.PAYPAL_WEBHOOK_ID
        if not webhook_id:
            raise GatewayNotConfigured("PAYPAL_WEBHOOK_ID is not set")
        body = json.loads(request.body)
        verification = {
            "auth_algo": request.headers.get("Paypal-Auth-Algo", ""),
            "cert_url": request.headers.get("Paypal-Cert-Url", ""),
            "transmission_id": request.headers.get("Paypal-Transmission-Id", ""),
            "transmission_sig": request.headers.get("Paypal-Transmission-Sig", ""),
            "transmission_time": request.headers.get("Paypal-Transmission-Time", ""),
            "webhook_id": webhook_id,
            "webhook_event": body,
        }
        resp = _http.request("POST", f"{self._base()}/v1/notifications/verify-webhook-signature",
                             headers=self._headers(), json=verification)
        if resp.status_code != 200 or resp.json().get("verification_status") != "SUCCESS":
            raise InvalidSignature("PayPal webhook signature verification failed")

        resource = body.get("resource") or {}
        # Payment-capture events carry the order id in supplementary_data; order events
        # carry it as the resource id itself.
        reference = (
            ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
            or resource.get("id", "")
        )
        return ParsedEvent(
            event_id=body.get("id", ""),
            event_type=body.get("event_type", ""),
            gateway_reference=reference,
            raw={"id": body.get("id"), "event_type": body.get("event_type")},
        )
