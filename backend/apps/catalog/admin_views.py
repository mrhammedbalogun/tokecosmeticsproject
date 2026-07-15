from django.http import StreamingHttpResponse
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.csv_io import export_products_csv
from apps.catalog.tasks import import_products_csv_task

from apps.catalog.admin_serializers import (
    BrandAdminSerializer,
    CategoryAdminSerializer,
    CollectionAdminSerializer,
    PriceAdminSerializer,
    ProductAdminSerializer,
    ProductImageAdminSerializer,
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

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
        url_path="images",
    )
    def images(self, request, slug=None):
        product = self.get_object()
        serializer = ProductImageAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(product=product)
        return Response(serializer.data, status=201)


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


class ProductCSVExportView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_products_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=products.csv"
        return resp


class ProductCSVImportView(APIView):
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager in dev/tests -> report returns inline. In prod with a real broker this
        # blocks the request; PLAN-05c-async: switch to returning {"task_id": ...} + polling.
        result = import_products_csv_task.delay(upload.read())
        return Response(result.get(), status=200)
