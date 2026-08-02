"""Delivery admin (Plan-19b).

`products.manage`, matching inventory's reasoning: a Manager runs the shop day to day and
a delivery price is an operational number, not a money-routing decision like the payout
account (which is Owner-only under `settings.manage`).
"""
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
)
from apps.delivery.models import DeliveryOption


class DeliveryOptionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """CRUD minus delete: a delivery option is named on every order that used it
    (`Order.delivery_option_name` is a snapshot, but the row is what future checkouts
    match), and deactivating is what "retire this option" means.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = DeliveryOptionAdminSerializer
    audit_serializers = (DeliveryOptionAdminSerializer,)
    queryset = (
        DeliveryOption.objects.select_related("currency")
        .prefetch_related("countries", "regions")
        .order_by("sort", "name")
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active", "kind", "countries"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

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
        if codes is not None:
            option.countries.set(Country.objects.filter(code__in=codes))
        region_ids = serializer.validated_data.get("region_ids")
        if region_ids is not None:
            option.regions.set(Region.objects.filter(id__in=region_ids))

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
