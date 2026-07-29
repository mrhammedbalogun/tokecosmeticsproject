"""Inventory administration.

All four endpoints are `products.manage` — stock is part of the product record, and
the same reasoning as `apps/catalog/admin_views.py` applies to the two that only read
(`export.csv` and the movements ledger): there is no `products.view` scope yet, and
inventing one that reaches the read-only halves while `GET /admin/stock/` stays behind
`.manage` would be incoherent. See that module's docstring for the full argument.

`stock/movements/` deserves a note of its own. It is a pure read, but it is the audit
trail for every adjustment — the record that shows who wrote off what. Read access to
it is not more sensitive than the numbers themselves, so it is not elevated above the
rest; it is simply not lowered either.
"""
from django.http import StreamingHttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.inventory.admin_serializers import (
    StockAdjustSerializer,
    StockItemSerializer,
    StockMovementSerializer,
)
from apps.inventory.csv_io import export_stock_csv
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import adjust
from apps.inventory.tasks import import_stock_csv_task


class StockItemAdminViewSet(viewsets.ModelViewSet):
    # `adjust` writes the number that decides whether an order can be placed at all.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
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
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["reason", "reference"]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("stock_item__variant").all()
        variant = self.request.query_params.get("variant")
        if variant:
            qs = qs.filter(stock_item__variant_id=variant)
        return qs


class StockCSVExportView(APIView):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_stock_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=stock.csv"
        return resp


class StockCSVImportView(APIView):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager inline in dev/tests (PLAN-05c-async note applies for a real broker).
        result = import_stock_csv_task.delay(upload.read(), user_id=request.user.id)
        return Response(result.get(), status=200)
