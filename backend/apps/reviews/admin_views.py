from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.reviews.admin_serializers import ReviewAdminSerializer
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


class ProductReviewAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """CUSTOMER product reviews — not the homepage's curated Google reviews
    (cms.GoogleReviewAdminViewSet) and not order fraud review (orders' resolve-review;
    beware the name collision). Reviews publish the moment a customer posts one, so
    this surface exists for after-the-fact control: PATCH status hidden/approved to
    pull one from (or return it to) the public list, or DELETE it for good. No create
    route on purpose — reviews only ever come from verified purchasers."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("reviews.manage")]
    serializer_class = ReviewAdminSerializer
    audit_serializers = (ReviewAdminSerializer,)
    audit_model_label = "reviews.review"
    queryset = Review.objects.select_related("product", "user").all()
    http_method_names = ["get", "patch", "delete", "head", "options"]
    # Relist DjangoFilterBackend: declaring filter_backends REPLACES the default, and
    # SearchFilter alone would silently kill the ?status= facet (catalog's warning).
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status", "rating"]
    search_fields = ["product__name", "user__email", "title", "body"]

    def perform_update(self, serializer):
        review = serializer.save()
        # A status flip moves the review in or out of the public average.
        recompute_product_rating(review.product)

    def destroy(self, request, *args, **kwargs):
        # Snapshot before deletion for the audit row — a DELETE carries no body, and
        # "which review did staff remove" is exactly what the log must answer
        # (delivery's DeliveryOptionAdminViewSet pattern).
        self._deleted_review = ReviewAdminSerializer(self.get_object()).data
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        product = instance.product
        instance.delete()
        recompute_product_rating(product)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted_review"):
            changes["deleted"] = self._deleted_review
        return changes
