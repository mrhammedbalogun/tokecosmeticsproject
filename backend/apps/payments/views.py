"""Customer-facing payment status / return endpoint.

The customer comes back from the gateway redirect BEFORE the webhook lands. This endpoint
runs the SAME confirm_payment() the webhook does, so the UI can show a fulfilled order
without waiting 5–30s for the webhook. Idempotency makes webhook-vs-return a benign race:
whichever verifies first fulfils, the other is a no-op.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.gateways.base import GatewayError
from apps.payments.models import Payment
from apps.payments.services import confirm_payment

logger = logging.getLogger(__name__)


class PaymentStatusView(APIView):
    """POST /api/v1/payments/{reference}/verify/ — re-verify with the gateway and return
    the current order + payment state. Scoped to the requesting user's own orders."""

    permission_classes = [IsAuthenticated]

    def post(self, request, reference: str):
        payment = get_object_or_404(
            Payment.objects.select_related("order"),
            gateway_reference=reference,
            order__user=request.user,
        )
        try:
            confirm_payment(payment)
        except GatewayError:
            # Verification couldn't complete right now (gateway down / not configured).
            # Report current state; the webhook will reconcile when it lands.
            logger.warning("Return-verify for %s could not reach gateway", reference)

        payment.refresh_from_db()
        payment.order.refresh_from_db()
        return Response({
            "order_number": payment.order.number,
            "order_status": payment.order.status,
            "payment_status": payment.status,
        })
