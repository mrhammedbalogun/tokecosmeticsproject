"""Inbound gateway webhooks: POST /api/v1/webhooks/{gateway}/

No auth — the signature IS the authentication (verified inside gateway.parse_webhook
over the RAW request bytes). CSRF-exempt (it's a server-to-server POST). Throttled
GENEROUSLY: gateways treat any non-2xx (including 429) as a delivery failure and retry
with backoff, so a tight throttle would turn a legit retry burst into a storm.

Flow (all fast — heavy work is deferred to the Celery task):
  verify signature -> upsert WebhookEvent(gateway,event_id) -> on duplicate return 200
  immediately -> enqueue process_webhook_event -> return 200.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.payments.gateways.base import InvalidSignature
from apps.payments.gateways.registry import UnknownGateway, get_gateway
from apps.payments.models import WebhookEvent
from apps.payments.tasks import process_webhook_event

logger = logging.getLogger(__name__)


class WebhookThrottle(SimpleRateThrottle):
    scope = "payment_webhooks"
    rate = "600/min"  # generous on purpose — signature is the real gate, not the throttle

    def get_cache_key(self, request, view):
        return f"webhook:{request.META.get('REMOTE_ADDR', '')}"


class GatewayWebhookView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [WebhookThrottle]
    parser_classes: list = []  # never let DRF consume the body — signatures sign raw bytes

    def post(self, request, gateway: str):
        try:
            gw = get_gateway(gateway)
        except UnknownGateway:
            return Response({"error": "unknown_gateway"}, status=status.HTTP_404_NOT_FOUND)

        try:
            event = gw.parse_webhook(request)
        except InvalidSignature:
            logger.warning("Rejected %s webhook: invalid signature", gateway)
            return Response({"error": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)
        except NotImplementedError:
            return Response({"error": "webhooks_unsupported"}, status=status.HTTP_400_BAD_REQUEST)

        # Idempotency ledger: the unique (gateway, event_id) row IS the dedupe.
        try:
            with transaction.atomic():
                record = WebhookEvent.objects.create(
                    gateway=gateway,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    gateway_reference=event.gateway_reference,
                    payload=event.raw,
                )
        except IntegrityError:
            # Duplicate delivery — already recorded. Ack fast; do NOT reprocess.
            return Response({"status": "duplicate"}, status=status.HTTP_200_OK)

        process_webhook_event.delay(record.pk)
        return Response({"status": "accepted"}, status=status.HTTP_200_OK)
