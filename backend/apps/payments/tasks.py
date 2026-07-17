"""Async webhook processing. The webhook endpoint records the (signature-verified)
event and returns 200 fast; the real work happens here so a slow gateway.verify() or a
DB hiccup never makes us look "down" to the gateway (which would trigger its retries).

Matching a Payment by (gateway, gateway_reference) is safe because of the partial-unique
constraint on Payment — the reference is unambiguous within a gateway. confirm_payment
does the server-side re-verification; the webhook body is never trusted for money.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_webhook_event(event_pk: int) -> str:
    from apps.payments.models import Payment, WebhookEvent
    from apps.payments.refunds import advance_refund_from_event
    from apps.payments.services import confirm_payment

    event = WebhookEvent.objects.get(pk=event_pk)
    if event.processed_at:
        return "already_processed"

    outcome = "ignored"
    try:
        payment = None
        if event.gateway_reference:
            payment = (
                Payment.objects.filter(
                    gateway=event.gateway, gateway_reference=event.gateway_reference
                )
                .order_by("-created_at")
                .first()
            )
        if payment is None:
            # Unknown/unmatched reference — log and mark processed so we don't retry
            # forever (the endpoint already returned 200; the gateway won't resend).
            logger.warning(
                "Webhook %s:%s references unknown payment %r",
                event.gateway, event.event_id, event.gateway_reference,
            )
            outcome = "unmatched"
        elif event.kind == "refund":
            # NEVER send a refund event through confirm_payment: it would re-verify an
            # already-refunded payment and mis-flag it as a double payment.
            outcome = advance_refund_from_event(
                payment, event_type=event.event_type,
                refund_reference=event.refund_reference,
            )
        elif event.kind == "payment":
            confirm_payment(payment)
            outcome = "confirmed"
    except Exception as exc:  # noqa: BLE001 - record the error, don't crash the worker
        event.error = f"{type(exc).__name__}: {exc}"
        event.save(update_fields=["error"])
        logger.exception("Webhook %s:%s processing failed", event.gateway, event.event_id)
        raise

    event.processed_at = timezone.now()
    event.save(update_fields=["processed_at"])
    return outcome
