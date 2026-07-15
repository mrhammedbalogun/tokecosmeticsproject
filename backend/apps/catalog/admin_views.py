from rest_framework import permissions, viewsets

from apps.catalog.admin_serializers import (
    BrandAdminSerializer,
    CategoryAdminSerializer,
    CollectionAdminSerializer,
    PriceAdminSerializer,
    ProductAdminSerializer,
    ProductVariantAdminSerializer,
    ProductVideoAdminSerializer,
    TagAdminSerializer,
)
from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    Product,
    ProductVariant,
    ProductVideo,
    Tag,
)
from apps.pricing.models import Price


class AdminBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC


class ProductAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductAdminSerializer
    queryset = Product.objects.all().order_by("-created_at")
    lookup_field = "slug"


class CategoryAdminViewSet(AdminBaseViewSet):
    serializer_class = CategoryAdminSerializer
    queryset = Category.objects.all().order_by("sort_order", "name")
    lookup_field = "slug"


class BrandAdminViewSet(AdminBaseViewSet):
    serializer_class = BrandAdminSerializer
    queryset = Brand.objects.all().order_by("name")
    lookup_field = "slug"


class TagAdminViewSet(AdminBaseViewSet):
    serializer_class = TagAdminSerializer
    queryset = Tag.objects.all().order_by("name")
    lookup_field = "slug"


class CollectionAdminViewSet(AdminBaseViewSet):
    serializer_class = CollectionAdminSerializer
    queryset = Collection.objects.all().order_by("name")
    lookup_field = "slug"


class ProductVariantAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductVariantAdminSerializer
    queryset = ProductVariant.objects.all().order_by("product_id", "position")


class ProductVideoAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductVideoAdminSerializer
    queryset = ProductVideo.objects.all()


class PriceAdminViewSet(AdminBaseViewSet):
    serializer_class = PriceAdminSerializer
    queryset = Price.objects.all()
