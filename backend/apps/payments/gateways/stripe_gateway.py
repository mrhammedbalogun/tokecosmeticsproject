"""Stripe — the international card path. Second gateway, deliberately: it exercises a
DIFFERENT InitiateResult action ("client_secret" rather than "redirect"), which proves
the ABC generalizes before we transcribe the remaining two.

Named stripe_gateway.py, NOT stripe.py, so the module never shadows the `stripe` SDK
package (absolute imports make stripe.py technically safe, but it's a needless footgun).

Uses the official stripe-python SDK on purpose: stripe.Webhook.construct_event does the
signature scheme correctly (timestamp tolerance, multiple v1 signatures) — hand-rolling
it is a classic place to introduce a subtle verification bypass. Amounts are minor units,
zero-decimal-currency aware via money.to_minor (which reads Currency.decimal_places).
"""
from __future__ import annotations

import stripe
from django.conf import settings

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

# PaymentIntent.status -> our normalized status. Anything still in flight is "pending";
# only an explicit terminal failure is "failed".
_STATUS_MAP = {
    "succeeded": "succeeded",
    "processing": "pending",
    "requires_action": "pending",
    "requires_confirmation": "pending",
    "requires_payment_method": "pending",
    "requires_capture": "pending",
    "canceled": "failed",
}


class StripeGateway(PaymentGateway):
    code = "stripe"
    supported_currencies = {"GBP", "USD", "CAD", "EUR", "NGN"}

    # --- config (lazy: never read keys at import) ---------------------------

    def _api_key(self) -> str:
        key = settings.STRIPE_SECRET_KEY
        if not key:
            raise GatewayNotConfigured("STRIPE_SECRET_KEY is not set")
        return key

    def _webhook_secret(self) -> str:
        secret = settings.STRIPE_WEBHOOK_SECRET
        if not secret:
            raise GatewayNotConfigured("STRIPE_WEBHOOK_SECRET is not set")
        return secret

    # --- API -----------------------------------------------------------------

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        try:
            intent = stripe.PaymentIntent.create(
                api_key=self._api_key(),
                amount=to_minor(payment.amount, payment.currency),
                currency=payment.currency_id.lower(),
                metadata={"order_number": order.number, "payment_id": str(payment.pk)},
                automatic_payment_methods={"enabled": True},
                # Stripe's native idempotency: a retry with the same key returns the SAME
                # intent instead of creating a second one / double-charging.
                idempotency_key=payment.idempotency_key,
            )
        except stripe.StripeError as exc:
            raise GatewayError(f"Stripe create intent failed: {exc}") from exc
        return InitiateResult(
            action="client_secret",
            reference=intent.id,
            data={"client_secret": intent.client_secret},
        )

    def verify(self, payment) -> VerifyResult:
        try:
            intent = stripe.PaymentIntent.retrieve(
                payment.gateway_reference, api_key=self._api_key()
            )
        except stripe.StripeError as exc:
            raise GatewayError(f"Stripe verify failed: {exc}") from exc
        status = _STATUS_MAP.get(intent.status, "pending")
        minor = intent.amount_received if status == "succeeded" else intent.amount
        return VerifyResult(
            status=status,
            amount=from_minor(minor or 0, payment.currency),
            currency=(intent.currency or "").upper(),
            raw={"id": intent.id, "status": intent.status, "amount": minor},
        )

    def refund(self, payment, amount, reason: str = "") -> RefundResult:
        try:
            refund = stripe.Refund.create(
                api_key=self._api_key(),
                payment_intent=payment.gateway_reference,
                amount=to_minor(amount, payment.currency),
                metadata={"reason": reason} if reason else {},
            )
        except stripe.StripeError as exc:
            raise GatewayError(f"Stripe refund failed: {exc}") from exc
        status = {"succeeded": "succeeded", "failed": "failed"}.get(refund.status, "pending")
        return RefundResult(status=status, gateway_reference=refund.id,
                            raw={"id": refund.id, "status": refund.status})

    def parse_webhook(self, request) -> ParsedEvent:
        try:
            event = stripe.Webhook.construct_event(
                request.body,  # RAW bytes — the signature is over exactly these
                request.headers.get("Stripe-Signature", ""),
                self._webhook_secret(),
            )
        except stripe.SignatureVerificationError as exc:
            raise InvalidSignature(f"Stripe signature mismatch: {exc}") from exc
        except ValueError as exc:  # malformed payload
            raise InvalidSignature(f"Stripe payload unparseable: {exc}") from exc

        obj = event["data"]["object"]
        event_type = event["type"]
        # payment_intent.* events carry the intent itself; charge.*/refund.* events carry a
        # Charge whose payment_intent field is the reference we stored on the Payment.
        if obj.get("object") == "payment_intent":
            reference = obj.get("id", "")
        else:
            reference = obj.get("payment_intent") or obj.get("id", "")

        if event_type.startswith("charge.refund") or event_type.startswith("refund."):
            kind = "refund"
            refund_reference = obj.get("id", "") if obj.get("object") == "refund" else ""
        elif event_type.startswith("payment_intent.") or event_type.startswith("charge."):
            kind, refund_reference = "payment", ""
        else:
            kind, refund_reference = "other", ""

        return ParsedEvent(
            event_id=event["id"],
            event_type=event_type,
            gateway_reference=reference or "",
            raw={"id": event["id"], "type": event_type},
            kind=kind,
            refund_reference=refund_reference,
        )
