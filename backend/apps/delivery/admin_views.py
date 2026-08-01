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
