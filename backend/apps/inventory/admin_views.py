from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.admin_serializers import (
    StockAdjustSerializer,
    StockItemSerializer,
    StockMovementSerializer,
)
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import adjust


class StockItemAdminViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = StockItemSerializer
    queryset = StockItem.objects.select_related("variant", "warehouse").order_by(
        "warehouse__name", "variant__sku"
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["warehouse", "variant"]
    http_method_names = ["get", "post", "head", "options"]  # no direct PUT/PATCH of numbers

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        item = self.get_object()
        serializer = StockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjust(
            item,
            new_quantity=serializer.validated_data["quantity"],
            reason=serializer.validated_data["reason"],
            note=serializer.validated_data["note"],
            user=request.user,
        )
        item.refresh_from_db()
        return Response(StockItemSerializer(item).data, status=200)


class StockMovementListView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["reason", "reference"]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("stock_item__variant").all()
        variant = self.request.query_params.get("variant")
        if variant:
            qs = qs.filter(stock_item__variant_id=variant)
        return qs
