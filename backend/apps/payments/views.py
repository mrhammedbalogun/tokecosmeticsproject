"""Customer-facing payment status / return endpoint.

The customer comes back from the gateway redirect BEFORE the webhook lands. This endpoint
runs the SAME confirm_payment() the webhook does, so the UI can show a fulfilled order
without waiting 5–30s for the webhook. Idempotency makes webhook-vs-return a benign race:
whichever verifies first fulfils, the other is a no-op.
"""
from __future__ import annotations

import logging

from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.payments.gateways.base import GatewayError
from apps.payments.models import Payment
from apps.payments.refunds import RefundError, create_refund, refundable_amount
from apps.payments.services import (
    AmountDiscrepancy,
    DuplicateBankReference,
    confirm_manual_receipt,
    confirm_payment,
)

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


class OrderRefundView(APIView):
    """POST /api/v1/admin/orders/{number}/refunds/ — staff-initiated refund.

    Body: {amount, reason?, restock?, payment_id?}. `payment_id` disambiguates an order
    with more than one payment (e.g. a double charge being unwound); by default the
    collected payment is used.
    """

    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        payment = self._pick_payment(order, request.data.get("payment_id"))
        if payment is None:
            return Response({"error": "no_refundable_payment",
                             "detail": "This order has no collected payment to refund."},
                            status=400)
        try:
            amount = Decimal(str(request.data.get("amount")))
        except (InvalidOperation, TypeError):
            return Response({"error": "invalid_amount", "detail": "amount must be a number."},
                            status=400)

        try:
            refund = create_refund(
                payment=payment, amount=amount,
                reason=request.data.get("reason", ""),
                user=request.user,
                restock=bool(request.data.get("restock", False)),
            )
        except RefundError as exc:
            return Response({"error": exc.code, "detail": exc.detail, **exc.extra},
                            status=exc.http)
        except GatewayError as exc:
            return Response({"error": "gateway_error", "detail": str(exc)}, status=502)

        payment.refresh_from_db()
        return Response({
            "refund_id": refund.pk,
            "status": refund.status,
            "amount": str(refund.amount),
            "payment_status": payment.status,
            "remaining": str(refundable_amount(payment)),
        }, status=201)

    @staticmethod
    def _pick_payment(order, payment_id):
        payments = order.payments.all()
        if payment_id:
            return payments.filter(pk=payment_id).first()
        return payments.filter(status__in=["succeeded", "partially_refunded"]).first()


class ConfirmManualReceiptSerializer(serializers.Serializer):
    amount_received = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    accept_discrepancy = serializers.BooleanField(required=False, default=False)
    allow_duplicate_reference = serializers.BooleanField(required=False, default=False)


class ConfirmManualReceiptView(APIView):
    """POST /api/v1/admin/orders/{number}/confirm-payment/ — staff confirm a bank transfer
    landed. This is the ONLY way a bank-transfer order can ever be fulfilled."""

    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        payment = order.payments.filter(gateway="bank_transfer").order_by("-id").first()
        if payment is None:
            return Response({"detail": "This order has no bank transfer payment to confirm."},
                            status=400)

        serializer = ConfirmManualReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            confirm_manual_receipt(payment, staff_user=request.user, **serializer.validated_data)
        except AmountDiscrepancy as exc:
            # Not a system error — a decision the human must make. Return the numbers so the
            # UI can offer "accept and fulfil" rather than just failing.
            return Response(
                {"detail": str(exc), "code": "amount_discrepancy",
                 "expected": str(exc.expected), "received": str(exc.received)},
                status=400,
            )
        except DuplicateBankReference as exc:
            return Response({"detail": str(exc), "code": "duplicate_bank_reference"}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc), "code": "invalid_confirmation"}, status=400)

        order.refresh_from_db()
        return Response({"status": order.status, "review_reason": order.review_reason})
