"""Delivery admin (Plan-19b).

`products.manage`, matching inventory's reasoning: a Manager runs the shop day to day and
a delivery price is an operational number, not a money-routing decision like the payout
account (which is Owner-only under `settings.manage`).
"""
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from apps.core.models import Country, Region
from apps.delivery.admin_serializers import (
    DeliveryCoverageSerializer,
    DeliveryOptionAdminSerializer,
    RegionAdminSerializer,
    currency_mismatches,
)
from apps.delivery.models import DeliveryOption


class DeliveryOptionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Full CRUD. Delete became real when creation did (the wizard): a mistyped option
    deserves better than immortality as an inactive row. It is referentially safe —
    orders snapshot only the option NAME (`Order.delivery_option_name`), nothing holds
    an FK to the row, and a checkout in flight re-matches by id at place time, where a
    deleted option fails exactly like a deactivated one. "Retire because prices moved"
    is still `is_active=False`; delete is for mistakes.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = DeliveryOptionAdminSerializer
    audit_serializers = (DeliveryOptionAdminSerializer,)
    queryset = (
        DeliveryOption.objects.select_related("currency")
        .prefetch_related(
            "countries",
            # parent joined so the coverage summary can say "Ikeja, Lagos" without an
            # extra query per region row.
            Prefetch("regions", queryset=Region.objects.select_related("parent")),
        )
        .order_by("sort", "name")
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "kind", "countries"]
    # No pagination: the global PAGE_SIZE (24) would silently truncate the list page
    # at option 25, and under country grouping a truncated list reads as "this country
    # has no options" — a lie with consequences. The row count here is operator-scale.
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        # `changes` is normally built from request.data — empty on a DELETE. And a
        # seeded option has no API create row either, so without this snapshot the
        # audit trail would prove only that *something* was deleted. Serialized BEFORE
        # the delete, merged into the row by `_changes` below, same transaction.
        self._deleted_option = DeliveryOptionAdminSerializer(self.get_object()).data
        return super().destroy(request, *args, **kwargs)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted_option"):
            changes["deleted"] = self._deleted_option
        return changes

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """`GET /admin/delivery-options/preview/?country=NG&state_region=1&area_region=2`

        "What would a customer HERE be offered?" answered by the real matcher
        (`services.options_for_address`), not a client-side mirror — the mirror can
        only ever drift. Prices are computed on an empty cart (no weight tiers, no
        free-over), and `kind="carrier"` options are returned WITHOUT calling the
        carrier: the admin wants coverage truth, not a live GIG quote per keystroke.
        """
        from decimal import Decimal
        from types import SimpleNamespace

        from apps.core.country_context import resolve_country
        from apps.delivery.services import options_for_address

        code = (request.query_params.get("country") or "").upper()
        country = resolve_country(code)
        if country is None:
            return Response({"country": ["Unknown country code."]}, status=400)

        def region_or_400(param):
            raw = request.query_params.get(param)
            if not raw:
                return None
            region = Region.objects.filter(id=raw).first()
            if region is None:
                raise ValueError(param)
            return region

        try:
            address = SimpleNamespace(
                country_code=code,
                state_region=region_or_400("state_region"),
                area_region=region_or_400("area_region"),
            )
        except ValueError as exc:
            return Response({str(exc): ["Unknown region id."]}, status=400)

        options = options_for_address(address, [], Decimal("0"), country)
        return Response({"country": country.code, "options": options})

    @action(detail=True, methods=["put"])
    def coverage(self, request, pk=None):
        """`PUT /admin/delivery-options/{id}/coverage/` — Plan-19d.

        A REPLACE, not a merge, and its own endpoint rather than a field on the flat
        serializer. Coverage is mixed granularity (whole countries, whole states,
        individual areas), and folding it into the price PATCH would let a client that
        omitted the key silently clear every region.
        """
        option = self.get_object()
        serializer = DeliveryCoverageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        codes = serializer.validated_data.get("country_codes")
        countries = Country.objects.filter(code__in=codes) if codes is not None else None
        region_ids = serializer.validated_data.get("region_ids")
        regions = Region.objects.filter(id__in=region_ids) if region_ids is not None else None

        # Same rule the create path enforces: coverage in a currency the option is not
        # priced in silently never appears at checkout (services.options_for_address
        # filters on the order currency), so the write is the only place to catch it.
        mismatched = currency_mismatches(
            option.currency_id,
            countries if countries is not None else option.countries.all(),
            regions if regions is not None else option.regions.all(),
        )
        if mismatched:
            return Response(
                {"country_codes": [
                    f"This option is priced in {option.currency_id} but this coverage "
                    f"includes {', '.join(mismatched)}, which sell in a different "
                    "currency — checkout would never show it there."
                ]},
                status=400,
            )

        if countries is not None:
            option.countries.set(countries)
        if regions is not None:
            option.regions.set(regions)

        option.refresh_from_db()
        return Response(DeliveryOptionAdminSerializer(option).data, status=200)


class RegionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """The regions browser (Plan-19d). Read plus `is_active`, nothing else.

    NO CREATE OR DELETE. The 811 rows are reference data seeded by migration — Nigeria's
    37 states and 774 LGAs are not a thing an operator invents, and a typo'd extra "Lagos"
    would silently never match an address. Deactivating is how a place stops being
    offered.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = RegionAdminSerializer
    audit_serializers = (RegionAdminSerializer,)
    audit_model_label = "core.region"
    queryset = Region.objects.all().order_by("country_code", "level", "name")
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["country_code", "level", "is_active", "parent"]
    pagination_class = None  # 811 rows is one response; the client builds the tree
    http_method_names = ["get", "patch", "head", "options"]


class AdminGigShipmentView(AdminAuditMixin, APIView):
    """GET /api/v1/admin/orders/{number}/gig/ — the fulfilment panel's data: the
    shipment, the cached wallet balance, and whether capture is currently legal
    (with the reason when it isn't, so the UI renders a sentence, not a grey box).

    `orders.view` and read-audited: the payload carries the receiver snapshot's
    order linkage — same PII posture as the order detail it sits beside.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.view")]
    audit_reads = True
    audit_action = "read"
    audit_model_label = "delivery.gigshipment"

    def get(self, request, number: str):
        from django.core.cache import cache as django_cache

        from apps.delivery.gig.capture import WALLET_CACHE_KEY
        from apps.delivery.models import GigShipment
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        shipment = GigShipment.objects.filter(order=order).first()
        if shipment is None:
            return Response({"shipment": None})

        can_capture, reason = True, ""
        if shipment.status != "quoted":
            can_capture, reason = False, f"shipment is {shipment.status}"
        elif order.status != "processing":
            can_capture, reason = False, f"order is {order.status} — capture after payment"

        raw_balance = django_cache.get(WALLET_CACHE_KEY)
        return Response({
            "shipment": {
                "status": shipment.status,
                "waybill": shipment.waybill,
                "cost": str(shipment.cost) if shipment.cost is not None else None,
                "charged": str(shipment.charged),
                "quote": shipment.quote,
                "label_url": shipment.label_url,
                "capture_api_id": shipment.capture_api_id,
                "last_scan": shipment.last_scan,
                "last_tracked_at": shipment.last_tracked_at,
                # Centre-pickup snapshot (32b slice 5): {} for door shipments. The
                # packing desk needs to see WHERE the parcel is routed before pressing
                # the button that debits the wallet.
                "centre": shipment.centre,
            },
            # "unknown" is honest: the sandbox account has no wallet record, and a
            # stale/absent cache is not a zero.
            "wallet_balance": None if raw_balance in (None, "unknown") else raw_balance,
            "can_capture": can_capture,
            "capture_blocked_reason": reason,
        })


class AdminGigCaptureView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/gig/capture/ — create the waybill.

    `orders.manage`, the money-touching scope: this call debits the GIG wallet
    the full GrandTotal and dispatches a rider, irrevocably. The service refuses
    ineligible states and insufficient balance BEFORE calling GIG; a timeout
    parks the shipment in `create_unconfirmed` and this endpoint answers 502
    with the instruction to check with GIG — never an automatic retry.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.manage")]
    audit_action = "gig_capture"
    audit_model_label = "delivery.gigshipment"

    def post(self, request, number: str):
        from apps.delivery.gig.capture import CaptureRefused, CaptureUnconfirmed, capture_shipment
        from apps.delivery.gig.client import GigError
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        try:
            shipment = capture_shipment(order, actor=request.user)
        except CaptureRefused as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=409)
        except CaptureUnconfirmed:
            return Response(
                {"error": "capture_unconfirmed",
                 "detail": "The capture timed out — GIG may have created a waybill and "
                           "debited the wallet. Check with GIG (WhatsApp) before ANY retry."},
                status=502,
            )
        except GigError as exc:
            return Response(
                {"error": "gig_rejected", "detail": str(exc), "api_id": exc.api_id}, status=502
            )
        return Response({"waybill": shipment.waybill, "cost": str(shipment.cost)})


class AdminGigLabelView(AdminAuditMixin, APIView):
    """POST /api/v1/admin/orders/{number}/gig/label/ — fetch the waybill label PDF.

    `orders.operate`: printing a label is packing-bench work. "Not ready yet" is a
    NORMAL answer (GIG generates the label only after the parcel passes through
    their station), rendered as 200 + ready:false so the UI shows a sentence and
    a retry button rather than an error state.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("orders.operate")]
    audit_action = "gig_label"
    audit_model_label = "delivery.gigshipment"

    def post(self, request, number: str):
        from apps.delivery.gig.capture import CaptureRefused, fetch_label
        from apps.delivery.gig.client import GigUnavailable
        from apps.delivery.models import GigShipment
        from apps.orders.models import Order

        order = get_object_or_404(Order, number=number)
        shipment = get_object_or_404(GigShipment, order=order)
        try:
            url = fetch_label(shipment)
        except CaptureRefused as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=409)
        except GigUnavailable as exc:
            return Response({"error": "gig_unreachable", "detail": str(exc)}, status=502)
        if url is None:
            return Response({"ready": False,
                             "detail": "Label not generated yet — GIG produces it after the "
                                       "parcel is processed at their station."})
        return Response({"ready": True, "label_url": url})
