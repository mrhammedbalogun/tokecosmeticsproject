from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductVariant
from apps.wishlist.models import WishlistItem
from apps.wishlist.serializers import WishlistItemSerializer


class _AddSerializer(serializers.Serializer):
    sku = serializers.CharField()


class WishlistView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        items = (
            request.user.wishlist_items.select_related("variant__product__brand")
            .prefetch_related("variant__product__images")
        )
        return Response(WishlistItemSerializer(items, many=True,
                                               context={"request": request}).data)

    def post(self, request):
        s = _AddSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        variant = get_object_or_404(ProductVariant, sku=s.validated_data["sku"])
        item, created = WishlistItem.objects.get_or_create(
            user=request.user, variant=variant
        )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(
            WishlistItemSerializer(item, context={"request": request}).data, status=code
        )


class WishlistItemDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, sku):
        item = get_object_or_404(request.user.wishlist_items, variant__sku=sku)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
