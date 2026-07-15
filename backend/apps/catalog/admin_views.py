from rest_framework import permissions, viewsets

from apps.catalog.admin_serializers import ProductAdminSerializer
from apps.catalog.models import Product


class AdminBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC


class ProductAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductAdminSerializer
    queryset = Product.objects.all().order_by("-created_at")
    lookup_field = "slug"
