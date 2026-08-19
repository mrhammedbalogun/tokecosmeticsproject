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
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.orders.models import Order
from apps.payments.gateways.base import GatewayError
from apps.payments.gateways.registry import get_gateway
from apps.payments.models import Payment
from apps.payments.refunds import (
    RefundError,
    create_refund,
    record_manual_refund,
    refundable_amount,
)
from apps.payments.services import (
    AmountDiscrepancy,
    DuplicateBankReference,
    confirm_manual_receipt,
    confirm_payment,
)

logger = logging.getLogger(__name__)


class PaymentStatusView(APIView):
    """POST /api/v1/payments/{reference}/verify/ — re-verify with the gateway and return
    the current order + payment state. Scoped to the requesting user's own orders, OR
    (Plan-38) to the single order a signed guest-order token names: without that path a
    guest returning from Paystack/Flutterwave literally could not verify the payment
    they just made. The token names the order and the reference is looked up WITHIN it
    — a guessed reference reaches nobody else's payment, same property as the authed
    scope. No user filter on the token path on purpose: a mid-payment claim (the
    account verifying its email while the guest tab polls) must not 404 the customer's
    own confirmation."""

    permission_classes = [AllowAny]

    def post(self, request, reference: str):
        if request.user.is_authenticated:
            payment = get_object_or_404(
                Payment.objects.select_related("order"),
                gateway_reference=reference,
                order__user=request.user,
            )
        else:
            from apps.orders.tokens import TrackingTokenError, read_guest_order_token

            data = request.data
            token = data.get("guest_token") if hasattr(data, "get") else None
            if not isinstance(token, str) or not token:
                return Response({"error": "authentication_required"}, status=403)
            try:
                number = read_guest_order_token(token)
            except TrackingTokenError:
                # Indistinguishable from "no such payment" — an expired token must not
                # confirm that a probed reference exists.
                return Response({"error": "not_found"}, status=404)
            payment = get_object_or_404(
                Payment.objects.select_related("order"),
                gateway_reference=reference,
                order__number=number,
            )
        # A manual gateway has no machine to ask — skip straight to reporting state.
        # Branching on `confirmation` rather than relying on ManualVerificationOnly being
        # caught below makes the intent explicit; the except stays as belt-and-braces.
        if get_gateway(payment.gateway).confirmation != "manual":
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


class OrderRefundView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/refunds/ — staff-initiated refund.

    Body: {amount, reason?, restock?, payment_id?}. `payment_id` disambiguates an order
    with more than one payment (e.g. a double charge being unwound); by default the
    collected payment is used.

    `orders.manage`: money leaving the merchant account through the gateway. This is the
    endpoint Amendment 7 named first, and the one Support must not hold.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    # No serializer: this view parses `request.data` by hand, so the allowlist lives on
    # the view. Money leaving the merchant account is the single row somebody will most
    # want to read back, so every key that shapes the amount is on it.
    audit_action = "refund"
    audit_model_label = "orders.order"
    audit_allowlist = ("amount", "reason", "restock", "payment_id")

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
        # purpose="goods": a freight receipt is not what a refund of this order means,
        # and it must never be picked implicitly. An explicit payment_id can still
        # reach it — that is a deliberate staff choice, not a default.
        payments = order.payments.filter(purpose="goods")
        if payment_id:
            return order.payments.filter(pk=payment_id).first()
        return payments.filter(status__in=["succeeded", "partially_refunded"]).first()


class ManualRefundSerializer(serializers.Serializer):
    audit_allowlist = ("amount", "bank_reference", "note", "restock", "payment_id")

    amount = serializers.DecimalField(max_digits=12, decimal_places=2,
                                      min_value=Decimal("0.01"))
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    restock = serializers.BooleanField(required=False, default=False)


class ManualRefundView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/manual-refund/ — staff record a refund they have
    already wired from the bank. The only refund path for a manual gateway, and the one
    the review flags that say "refund it" are telling staff to use.

    `orders.manage`, and if anything more strongly than the gateway refund above: this
    one is an unverified ASSERTION that money was wired, with no gateway to contradict
    it. The only check on it is the person allowed to make it.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    # An UNVERIFIED assertion that money was wired, with no gateway to contradict it —
    # the docstring above says the only check on it is the person allowed to make it.
    # The audit row is the second check: it records which person, and which session.
    audit_action = "manual_refund"
    audit_model_label = "orders.order"
    audit_serializers = (ManualRefundSerializer,)

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        payment = self._pick_payment(order, request.data.get("payment_id"))
        if payment is None:
            return Response({"error": "no_refundable_payment",
                             "detail": "This order has no collected payment to refund."},
                            status=400)

        serializer = ManualRefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            refund = record_manual_refund(
                payment=payment, staff_user=request.user, **serializer.validated_data
            )
        except RefundError as exc:
            return Response({"error": exc.code, "detail": exc.detail, **exc.extra},
                            status=exc.http)

        payment.refresh_from_db()
        return Response({
            "refund_id": refund.pk,
            "status": refund.status,
            "amount": str(refund.amount),
            "bank_reference": refund.gateway_reference,
            "payment_status": payment.status,
            "remaining": str(refundable_amount(payment)),
        }, status=201)

    @staticmethod
    def _pick_payment(order, payment_id):
        # purpose="goods": a freight receipt is not what a refund of this order means,
        # and it must never be picked implicitly. An explicit payment_id can still
        # reach it — that is a deliberate staff choice, not a default.
        payments = order.payments.filter(purpose="goods")
        if payment_id:
            return order.payments.filter(pk=payment_id).first()
        return payments.filter(status__in=["succeeded", "partially_refunded"]).first()


class ConfirmManualReceiptSerializer(serializers.Serializer):
    # `accept_discrepancy` and `allow_duplicate_reference` are the two overrides that
    # switch OFF the guards stopping goods shipping twice against one transfer. They
    # are the most important keys on this endpoint to have on the record.
    audit_allowlist = (
        "amount_received", "bank_reference", "note", "accept_discrepancy",
        "allow_duplicate_reference",
    )

    amount_received = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    accept_discrepancy = serializers.BooleanField(required=False, default=False)
    allow_duplicate_reference = serializers.BooleanField(required=False, default=False)


class ConfirmManualReceiptView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/confirm-payment/ — staff confirm a bank transfer
    landed. This is the ONLY way a bank-transfer order can ever be fulfilled.

    `orders.manage`, named explicitly by Amendment 7. Bank transfer is the live gateway
    for this store, so this endpoint is the point at which goods are released against
    money nobody has verified but the person clicking. It can also override an amount
    discrepancy and a duplicate bank reference — the two guards that stop goods shipping
    twice against one transfer.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    audit_action = "confirm_bank_transfer"
    audit_model_label = "orders.order"
    audit_serializers = (ConfirmManualReceiptSerializer,)

    def post(self, request, number: str):
        order = get_object_or_404(Order, number=number)
        payment = (
            order.payments.filter(gateway="bank_transfer", purpose="goods")
            .order_by("-id").first()
        )
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
