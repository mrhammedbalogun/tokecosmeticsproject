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
from apps.core.audit import AdminAuditMixin
from apps.inventory.admin_serializers import (
    StockAdjustSerializer,
    StockItemSerializer,
    StockMovementSerializer,
    WarehouseAdminSerializer,
)
from apps.inventory.csv_io import export_stock_csv
from apps.inventory.models import StockItem, StockMovement, Warehouse
from apps.inventory.services import adjust
from apps.inventory.tasks import import_stock_csv_task


class WarehouseAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Plan-17c Task 1. `products.manage`, consistent with the rest of inventory.

    ── DELETE IS NOT OFFERED, AND THAT IS THE POINT ────────────────────────────────

    `StockItem.warehouse` is `on_delete=CASCADE`. Deleting a warehouse would silently
    destroy every stock row it holds and strip the context from every movement those rows
    ever recorded — the ledger that says who wrote off what would start pointing at
    nothing. Deactivating (`is_active=False`) takes the warehouse out of `reserve()`
    without touching a single row of history, which is what "remove this warehouse"
    actually means when somebody asks for it.

    So `http_method_names` omits `delete` and the route answers 405. That is a deliberate
    refusal rather than an unimplemented feature.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = WarehouseAdminSerializer
    audit_serializers = (WarehouseAdminSerializer,)
    queryset = Warehouse.objects.prefetch_related("serves_countries").all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "location_country"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]


class StockItemAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    # `adjust` writes the number that decides whether an order can be placed at all —
    # which is also why its audit row must not read as an ordinary "create". The mixin
    # prefers the DRF action name over the HTTP verb for exactly this case.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = StockItemSerializer
    audit_serializers = (StockItemSerializer, StockAdjustSerializer)
    queryset = StockItem.objects.select_related("variant", "warehouse").order_by(
        "warehouse__name", "variant__sku"
    )
    filter_backends = [DjangoFilterBackend]
    # `variant__product` added in Plan-17a Task 6: the editor's Variants tab shows stock
    # per warehouse for every variant of one product, and `variant` is an exact match — so
    # without it the page would issue one request per variant.
    filterset_fields = ["warehouse", "variant", "variant__product"]
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


class StockMovementListView(AdminAuditMixin, generics.ListAPIView):
    # NOT read-audited. This IS the ledger of every stock adjustment, and reading an
    # audit trail is not the event an audit trail exists to record — it would put a row
    # in one table every time somebody looked at the other.
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


class StockCSVExportView(AdminAuditMixin, APIView):
    # Audited for the same reason as the catalogue export: a whole-table dump is a bulk
    # egress. The full argument is in apps/catalog/admin_views.py.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    audit_reads = True
    audit_action = "export_csv"
    audit_model_label = "inventory.stockitem"

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_stock_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=stock.csv"
        return resp


class StockCSVImportView(AdminAuditMixin, APIView):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    parser_classes = [MultiPartParser, FormParser]
    audit_action = "import_csv"
    audit_model_label = "inventory.stockitem"

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager inline in dev/tests (PLAN-05c-async note applies for a real broker).
        result = import_stock_csv_task.delay(upload.read(), user_id=request.user.id)
        return Response(result.get(), status=200)
