"""Catalogue administration.

EVERY endpoint here is `products.manage` — Owner and Manager — including the three
that only read (`export.csv`, and the list/retrieve halves of the viewsets). That is
a deliberate choice rather than an oversight, and the reasoning is worth writing down
because the obvious alternative looks better than it is.

A `products.view` scope would let Support answer "is this in stock, what does it
cost?" without also being able to rewrite prices. But `permission_classes` is a class
attribute, and every catalogue endpoint except the two CSV views is a `ModelViewSet`
whose reads and writes share one class. Splitting them means overriding
`get_permissions()` per action, which makes the declared `permission_classes` — the
thing `test_admin_surface_guard.py` reads, and the thing the next reader trusts —
decorative. The guard test is the only real guarantee on this surface (Plan-16
Amendment 6); trading it for a convenience scope is a bad trade. Half-splitting is
worse still: a `products.view` reaching `products/export.csv` but not
`GET /admin/products/` would let Support export the entire catalogue while being
unable to look up one product.

So the whole app is `.manage` until there is a read-only catalogue surface to design
the split around (Plan-17/19). Over-restriction is the safe direction to be wrong in.
"""
from django.http import StreamingHttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
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
    """Base for every catalogue viewset. Both class attributes are load-bearing.

    `authentication_classes` is what makes a future subclass fail CLOSED: a viewset
    added here inherits the admin-only authenticator, so even if someone forgets the
    permission class the request arrives unauthenticated and answers 401 rather than
    letting a customer-door token through.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]


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
    # Read-only, and still `.manage`: see the module docstring. A bulk dump of the
    # catalogue is also the natural export half of the import below — whoever can
    # round-trip the file is the audience.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_products_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=products.csv"
        return resp


class ProductCSVImportView(APIView):
    # Bulk write over the whole catalogue, prices included — the single most
    # destructive thing on this surface.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager in dev/tests -> report returns inline. In prod with a real broker this
        # blocks the request; PLAN-05c-async: switch to returning {"task_id": ...} + polling.
        result = import_products_csv_task.delay(upload.read())
        return Response(result.get(), status=200)
