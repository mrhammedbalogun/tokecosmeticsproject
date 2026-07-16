from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.carts.models import Cart, CartItem
from apps.carts.serializers import serialize_cart
from apps.carts.services import get_or_create_cart, set_quantity
from apps.catalog.models import ProductVariant
from apps.checkout.services.checkout import CheckoutError, place_order
from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    clear,
    finish,
    hash_payload,
)
from apps.payments.gateways.base import GatewayError, GatewayNotConfigured
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


class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response({"error": "idempotency_key_required"}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "cart_id": str(request.data.get("cart_id")),
            "address_id": request.data.get("address_id"),
            "billing_address_id": request.data.get("billing_address_id"),
            "delivery_option_id": request.data.get("delivery_option_id"),
            "coupon_code": request.data.get("coupon_code", ""),
            "payment_gateway": request.data.get("payment_gateway"),
        }
        request_hash = hash_payload(payload)
        try:
            replay = begin(request.user.id, key, request_hash)
        except IdempotencyKeyReused:
            return Response({"error": "idempotency_key_reused"}, status=422)
        except IdempotencyConflict:
            return Response({"error": "idempotency_in_progress"}, status=409, headers={"Retry-After": "2"})
        if replay is not None:
            return Response(replay[1], status=replay[0])

        try:
            result = place_order(
                user=request.user, country=request.country, key=key,
                cart_id=payload["cart_id"], address_id=payload["address_id"],
                billing_address_id=payload["billing_address_id"],
                delivery_option_id=payload["delivery_option_id"],
                payment_gateway=payload["payment_gateway"],
                coupon_code=payload["coupon_code"],
                notes=request.data.get("notes", ""),
                expected_total=request.data.get("expected_total"),
            )
        except CheckoutError as exc:
            body = {"error": exc.code, "detail": exc.detail, **exc.extra}
            return Response(body, status=exc.http)
        except GatewayNotConfigured:
            clear(request.user.id, key)
            return Response({"error": "gateway_not_configured",
                             "detail": "Payment method is not available right now."}, status=503)
        except GatewayError:
            # Gateway 5xx/timeout on initiate. Order stays pending; clearing the inflight
            # marker lets the customer retry with the SAME Idempotency-Key (resumes it).
            # NOTE: distinct from the 400 "gateway_unavailable" above, which means the
            # method isn't offered in this country. This one means the provider is down.
            clear(request.user.id, key)
            return Response({"error": "gateway_error",
                             "detail": "Payment provider is temporarily unavailable. Please retry."},
                            status=502)

        init = getattr(result.order, "_initiate", None)
        body = {
            "order_number": result.order.number,
            "payment": {
                "gateway": result.payment.gateway,
                "action": init.action if init else "",
                "data": init.data if init else {},
            },
        }
        finish(request.user.id, key, request_hash, status.HTTP_201_CREATED, body)
        return Response(body, status=status.HTTP_201_CREATED)


class BuyNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant_id"), is_active=True)
        qty = int(request.data.get("quantity", 1))
        cart = get_or_create_cart(request, kind="express")
        # Express cart holds exactly the Buy-Now item — clear then set.
        CartItem.objects.filter(cart=cart).delete()
        set_quantity(cart, variant, qty, request.country)
        return Response(serialize_cart(cart, request.country))
