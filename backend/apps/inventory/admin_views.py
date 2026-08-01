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
from django.db.models import F, Q
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
from apps.catalog.models import ProductVariant
from apps.inventory.models import StockItem, StockMovement, Warehouse
from apps.inventory.services import adjust
from apps.inventory.tasks import import_stock_csv_task


def _grid_cell(warehouse, item) -> dict:
    """One variant × warehouse cell. `stock_item_id: None` means no row exists — an
    absence the screen offers to fix, not a zero."""
    if item is None:
        return {
            "warehouse_id": warehouse.pk, "warehouse_name": warehouse.name,
            "stock_item_id": None, "quantity": None, "reserved": None,
            "available": None, "low_stock_threshold": None, "is_low": False,
        }
    return {
        "warehouse_id": warehouse.pk, "warehouse_name": warehouse.name,
        "stock_item_id": item.pk, "quantity": item.quantity, "reserved": item.reserved,
        "available": item.available, "low_stock_threshold": item.low_stock_threshold,
        "is_low": item.quantity <= item.low_stock_threshold,
    }


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

    @action(detail=False, methods=["get"])
    def grid(self, request):
        """`GET /admin/stock/grid/` — the inventory screen's data. Plan-17c Task 3.

        Variant per row, active warehouse per column, and **a cell with no `StockItem` is
        the point**: 122 of the 244 possible cells are empty in production and every empty
        one is the UK Warehouse. `stock_item_id: null` is what the screen renders as an
        actionable absence rather than a blank.

        It cannot be assembled from the ordinary stock list in the browser. That endpoint
        pages `StockItem` rows, so a variant with no row ANYWHERE never appears in it — and
        that is exactly the variant somebody is looking for when they open this screen.
        Paginating by variant is therefore a server-side job.

        An action on this viewset, not a new view: same resource, same `products.manage`,
        and a new class would owe the four guard declarations that this one already carries.

        `?low_stock=1` keeps rows holding a cell at or below its own threshold. An ABSENT
        cell is deliberately not low stock — an absence is a different problem with a
        different fix, and folding the two together makes the low-stock queue unworkable.
        """
        warehouses = list(
            Warehouse.objects.filter(is_active=True).order_by("priority", "name", "pk")
        )
        variants = ProductVariant.objects.select_related("product")

        search = (request.query_params.get("search") or "").strip()
        if search:
            variants = variants.filter(
                Q(sku__icontains=search) | Q(product__name__icontains=search)
            )
        if request.query_params.get("warehouse"):
            # Narrowing the COLUMNS, not the rows: "show me what the UK holds" is still a
            # question about every variant, including the ones it holds nothing of.
            warehouses = [w for w in warehouses if str(w.pk) == request.query_params["warehouse"]]

        if str(request.query_params.get("low_stock", "")).lower() in {"1", "true", "yes"}:
            variants = variants.filter(
                stock_items__quantity__lte=F("stock_items__low_stock_threshold"),
                stock_items__warehouse__in=warehouses,
            ).distinct()

        variants = variants.order_by("product__name", "sku")
        page = self.paginate_queryset(variants)
        rows_source = page if page is not None else list(variants)

        items = {
            (item.variant_id, item.warehouse_id): item
            for item in StockItem.objects.filter(
                variant__in=[v.pk for v in rows_source],
                warehouse__in=[w.pk for w in warehouses],
            )
        }
        rows = [
            {
                "variant_id": variant.pk,
                "sku": variant.sku,
                "variant_name": variant.name,
                "product_name": variant.product.name,
                "product_slug": variant.product.slug,
                "cells": [
                    _grid_cell(warehouse, items.get((variant.pk, warehouse.pk)))
                    for warehouse in warehouses
                ],
            }
            for variant in rows_source
        ]
        columns = [{"id": w.pk, "name": w.name} for w in warehouses]

        if page is None:
            return Response({"results": rows, "warehouses": columns})
        response = self.get_paginated_response(rows)
        # The header must not be derived from the rows currently on screen, or the table
        # would reshuffle its columns as somebody pages through it.
        response.data["warehouses"] = columns
        return response

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
    """POST a stock CSV. `?dry_run=1` reports what the file WOULD do and writes nothing —
    see `csv_io.import_stock_csv` for why that is the same code path rolled back.

    The audit ACTION distinguishes the two, because "who changed the stock levels" must
    not be answered with a row for somebody who only previewed a file. A dry-run is still
    audited: uploading a customer's spreadsheet is worth recording either way, and the
    row's action says plainly which it was.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    parser_classes = [MultiPartParser, FormParser]
    audit_action = "import_csv"
    audit_model_label = "inventory.stockitem"

    def _is_dry_run(self, request) -> bool:
        raw = request.query_params.get("dry_run", request.data.get("dry_run", ""))
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def resolve_action(self) -> str:
        return "import_csv_dry_run" if self._is_dry_run(self.request) else "import_csv"

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager inline in dev/tests (PLAN-05c-async note applies for a real broker).
        result = import_stock_csv_task.delay(
            upload.read(), user_id=request.user.id, dry_run=self._is_dry_run(request)
        )
        return Response(result.get(), status=200)
