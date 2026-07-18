"""Admin endpoints for the freight-quote lifecycle.

Mirrors the shape of apps/payments/views.py's admin views: staff-only, thin HTTP wrappers
over the services in apps/shipping/services.py. The services own every money-safety rule;
these views only translate ShippingError -> a coded 4xx and the duplicate-reference
IntegrityError -> a 409 the UI can act on.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.shipping.models import ShippingQuote
from apps.shipping.services import (
    ShippingError,
    cancel_quote,
    quote_freight,
    record_freight_receipt,
    waive_freight,
)


def _quote_payload(quote) -> dict:
    return {
        "order_number": quote.order.number,
        "status": quote.status,
        "amount": str(quote.amount) if quote.amount is not None else None,
        "currency": quote.currency_id,
        "order_status": quote.order.status,
        "is_shippable": quote.order.is_shippable,
    }


def _get_quote(number: str) -> ShippingQuote:
    order = get_object_or_404(Order, number=number)
    return get_object_or_404(ShippingQuote, order=order)


class _FreightView(APIView):
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC

    def _run(self, request, number, serializer_class, action):
        quote = _get_quote(number)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            action(quote, staff_user=request.user, **serializer.validated_data)
        except ShippingError as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=exc.http)
        except IntegrityError:
            # The (gateway, gateway_reference) unique constraint. One transfer quoted
            # against two orders means goods ship twice against money that arrived once.
            return Response(
                {"error": "duplicate_reference",
                 "detail": "That bank reference is already recorded against a payment."},
                status=409,
            )
        quote.refresh_from_db()
        quote.order.refresh_from_db()
        return Response(_quote_payload(quote))


class QuoteSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    note = serializers.CharField(required=False, allow_blank=True, default="")


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField()


class ReceiptSerializer(serializers.Serializer):
    amount_received = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class QuoteFreightView(_FreightView):
    """POST /api/v1/admin/orders/{number}/freight/quote/ — record what the forwarder quoted."""

    def post(self, request, number):
        return self._run(request, number, QuoteSerializer, quote_freight)


class WaiveFreightView(_FreightView):
    """POST .../freight/waive/ — merchant absorbs the freight. Requires a prior quote."""

    def post(self, request, number):
        return self._run(request, number, NoteSerializer, waive_freight)


class CancelQuoteView(_FreightView):
    """POST .../freight/cancel/ — customer declined or never answered."""

    def post(self, request, number):
        return self._run(request, number, NoteSerializer, cancel_quote)


class FreightReceiptView(_FreightView):
    """POST .../freight/receipt/ — the freight transfer landed."""

    def post(self, request, number):
        return self._run(request, number, ReceiptSerializer, record_freight_receipt)
