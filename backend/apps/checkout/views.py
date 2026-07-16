from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.checkout.services.totals import compute_totals
from apps.core.country_context import resolve_country
from apps.delivery.services import options_for_address
from apps.payments.gateways.registry import active_gateways_for


class PaymentMethodsView(APIView):
    """GET /api/v1/checkout/payment-methods/?country=NG — active gateways for a country."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        country = resolve_country(request.query_params.get("country") or request.headers.get("X-Country"))
        return Response(active_gateways_for(country))


def _cart_lines(cart):
    """[(variant, qty)] for a cart, prefetching variants."""
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


class DeliveryOptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        address = get_object_or_404(Address, pk=request.query_params.get("address_id"), user=request.user)
        cart = get_object_or_404(Cart, pk=request.query_params.get("cart_id"), user=request.user, status="active")
        lines = _cart_lines(cart)
        if not lines:
            raise ValidationError("Cart is empty.")
        totals = compute_totals(lines, request.country)
        return Response(options_for_address(address, lines, totals.subtotal))
