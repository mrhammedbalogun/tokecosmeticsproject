"""Coupon admin (Plan-19b). See `admin_serializers` for why this did not exist before."""
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.checkout.admin_serializers import CouponAdminSerializer
from apps.checkout.models import Coupon
from apps.core.audit import AdminAuditMixin


class CouponAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """`marketing.manage` — Owner and Manager, matching the nav item that has pointed at
    `/coupons` since Plan-16.

    DELETE IS NOT OFFERED. `CouponRedemption` records usage by `coupon_id`, so deleting a
    code that has been used detaches the ledger rows that say what discount an order got.
    Deactivating stops it working and keeps the accounting.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    serializer_class = CouponAdminSerializer
    audit_serializers = (CouponAdminSerializer,)
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["type", "is_active"]
    search_fields = ["code"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        # The count comes from the ledger rather than a counter column, so it cannot drift
        # from the rows that actually record a redemption.
        return (
            Coupon.objects.annotate(redemption_count=Count("redemptions"))
            .select_related("currency")
            .order_by("-created_at")
        )
