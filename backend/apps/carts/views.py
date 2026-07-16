from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.carts.serializers import serialize_cart
from apps.carts.services import add_item, get_or_create_cart, remove_item, set_quantity
from apps.catalog.models import ProductVariant


class _CartBase(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "cart"

    def _respond(self, cart, request):
        return Response(serialize_cart(cart, request.country))


class CartView(_CartBase):
    def get(self, request):
        cart = get_or_create_cart(request)
        return self._respond(cart, request)


class CartItemsView(_CartBase):
    def post(self, request):
        variant = get_object_or_404(
            ProductVariant, pk=request.data.get("variant_id"), is_active=True
        )
        qty = int(request.data.get("quantity", 1))
        if qty <= 0:
            return Response({"quantity": ["Must be positive."]}, status=status.HTTP_400_BAD_REQUEST)
        cart = get_or_create_cart(request)
        add_item(cart, variant, qty, request.country)
        return self._respond(cart, request)


class CartItemDetailView(_CartBase):
    def patch(self, request, variant_id):
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        cart = get_or_create_cart(request)
        set_quantity(cart, variant, int(request.data.get("quantity", 0)), request.country)
        return self._respond(cart, request)

    def delete(self, request, variant_id):
        variant = get_object_or_404(ProductVariant, pk=variant_id)
        cart = get_or_create_cart(request)
        remove_item(cart, variant, request.country)
        return self._respond(cart, request)
