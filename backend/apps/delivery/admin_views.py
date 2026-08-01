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
from apps.delivery.admin_serializers import DeliveryOptionAdminSerializer
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
