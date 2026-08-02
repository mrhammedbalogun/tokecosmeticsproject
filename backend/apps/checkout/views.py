from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.carts.serializers import serialize_cart
from apps.carts.services import add_item, get_or_create_cart
from apps.catalog.models import ProductVariant
from apps.checkout.serializers import QuoteRequestSerializer
from apps.checkout.services.checkout import CheckoutError, place_order, retry_payment
from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    clear,
    finish,
    hash_payload,
)
from apps.checkout.services.quote import quote as quote_service
from apps.payments.gateways.base import GatewayError, GatewayNotConfigured
from apps.checkout.services.totals import compute_totals
from apps.core.country_context import resolve_country
from apps.delivery.carriers import priced_options_for_address
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
        return Response(priced_options_for_address(address, lines, totals.subtotal, request.country))


class QuoteView(APIView):
    """Read-only totals + coupon preview (Plan-14). Never mutates."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = QuoteRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        cart = get_object_or_404(Cart, pk=v["cart_id"], user=request.user, status="active")
        delivery_amount = Decimal("0.00")
        if v.get("address_id") and v.get("delivery_option_id"):
            address = get_object_or_404(Address, pk=v["address_id"], user=request.user)
            lines = _cart_lines(cart)
            totals = compute_totals(lines, request.country)
            opts = priced_options_for_address(address, lines, totals.subtotal, request.country)
            chosen = next((o for o in opts if o["id"] == v["delivery_option_id"] and o["price"] is not None), None)
            # Intentional silent fallback: an option id that doesn't match this address
            # (or is quote_required) just leaves delivery at 0.00 rather than erroring —
            # this is a non-authoritative preview, not a place_order. place_order does
            # its own server-side re-match and is the authoritative check.
            if chosen:
                delivery_amount = Decimal(chosen["price"])
        return Response(quote_service(
            cart, request.country, user=request.user,
            coupon_code=v.get("coupon_code", ""), delivery_amount=delivery_amount,
        ))


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

        body = _payment_envelope(result)
        finish(request.user.id, key, request_hash, status.HTTP_201_CREATED, body)
        return Response(body, status=status.HTTP_201_CREATED)


def _payment_envelope(result) -> dict:
    """The payment block the storefront drives its launcher from. Shared by place_order
    and retry so the client has exactly one shape to understand."""
    init = getattr(result.order, "_initiate", None)
    return {
        "order_number": result.order.number,
        "payment": {
            "gateway": result.payment.gateway,
            "action": init.action if init else "",
            "reference": result.payment.gateway_reference,
            "data": init.data if init else {},
        },
    }


class OrderPayView(APIView):
    """POST /api/v1/orders/{number}/pay/ — re-open payment on an order that is still
    awaiting it, optionally switching gateway. The customer-facing escape hatch for a
    declined card: placement already converted the cart, so there is no checkout to redo.

    Not idempotency-tracked through begin()/finish() like CheckoutView: there is no cart
    to convert and no order to duplicate here, so the Payment row's unique idempotency_key
    is protection enough — a repeated key replays the same attempt (see retry_payment).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, number: str):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response({"error": "idempotency_key_required"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = retry_payment(
                user=request.user, order_number=number,
                payment_gateway=request.data.get("payment_gateway"), key=key,
            )
        except CheckoutError as exc:
            return Response({"error": exc.code, "detail": exc.detail, **exc.extra},
                            status=exc.http)
        except GatewayNotConfigured:
            return Response({"error": "gateway_not_configured",
                             "detail": "Payment method is not available right now."}, status=503)
        except GatewayError:
            # The attempt exists but never got a reference. Retrying with the SAME key
            # resumes it rather than opening yet another attempt.
            return Response({"error": "gateway_error",
                             "detail": "Payment provider is temporarily unavailable. Please retry."},
                            status=502)
        return Response(_payment_envelope(result), status=status.HTTP_200_OK)


class BuyNowView(APIView):
    """Buy Now = add to the shopper's ordinary cart; the client then navigates to
    checkout, which reads that same cart. Never clears existing lines — this cart is
    the shopper's bag, and clearing it here would silently destroy it. (Originally a
    separate `kind="express"` cart per Plan-08 D14, retired 2026-07-28: nothing ever
    read an express cart, so Buy Now produced an empty checkout. The Cart.kind field
    stays for the inert historical rows.)"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant_id"), is_active=True)
        qty = int(request.data.get("quantity", 1))
        cart = get_or_create_cart(request)
        add_item(cart, variant, qty, request.country)
        return Response(serialize_cart(cart, request.country))
