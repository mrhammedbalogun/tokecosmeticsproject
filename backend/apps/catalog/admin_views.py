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
from apps.core.audit import AdminAuditMixin
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


class AdminBaseViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Base for every catalogue viewset. All three of these are load-bearing.

    `authentication_classes` is what makes a future subclass fail CLOSED: a viewset
    added here inherits the admin-only authenticator, so even if someone forgets the
    permission class the request arrives unauthenticated and answers 401 rather than
    letting a customer-door token through.

    `AdminAuditMixin` is FIRST in the bases so its `dispatch` wraps the viewset's — the
    audit row is written inside the same transaction as the mutation, so an unauditable
    write does not happen at all (apps/core/audit.py). Inheriting it here has the same
    fail-closed property as the authenticator: a viewset added to this module is
    audited before anybody remembers to ask for it.

    READS ARE NOT AUDITED on this surface, by ruling rather than by omission: the
    catalogue carries no personal data, and an admin UI that lists products on every
    screen would bury the rows that matter. The two CSV EXPORTS opt in individually —
    a whole-catalogue dump is a bulk egress whatever it contains.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]


class ProductAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductAdminSerializer
    # The `images` action parses a DIFFERENT body from the rest of the viewset, so both
    # serializers are named: the audit guard checks allowlisted keys against every
    # serializer a view can parse, and a body shape it cannot see is a body shape whose
    # write-only fields nobody checked.
    audit_serializers = (ProductAdminSerializer, ProductImageAdminSerializer)
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


class ProductCSVExportView(AdminAuditMixin, APIView):
    # Read-only, and still `.manage`: see the module docstring. A bulk dump of the
    # catalogue is also the natural export half of the import below — whoever can
    # round-trip the file is the audience.
    #
    # AUDITED DESPITE BEING A CATALOGUE READ. The Task 4 ruling audits PII reads and
    # leaves catalogue reads alone; it also says "every list/export". This endpoint sits
    # in the gap between those two sentences, and it is resolved towards recording it:
    # the row costs one line a month, and "somebody took the whole price list" is a
    # sentence worth being able to write even though no customer is named in it.
    # Routine catalogue LISTS stay unaudited — the line drawn here is bulk egress.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    audit_reads = True
    audit_action = "export_csv"
    audit_model_label = "catalog.product"

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_products_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=products.csv"
        return resp


class ProductCSVImportView(AdminAuditMixin, APIView):
    # Bulk write over the whole catalogue, prices included — the single most
    # destructive thing on this surface.
    #
    # The audit row carries NO `changes`: the body is an uploaded file, and the only
    # things there are to store about it are its name and its size. What the row does
    # carry is that this account ran a whole-catalogue import at this time, from this
    # IP, on this session — which is the part somebody will want back.
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    parser_classes = [MultiPartParser, FormParser]
    audit_action = "import_csv"
    audit_model_label = "catalog.product"

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager in dev/tests -> report returns inline. In prod with a real broker this
        # blocks the request; PLAN-05c-async: switch to returning {"task_id": ...} + polling.
        result = import_products_csv_task.delay(upload.read())
        return Response(result.get(), status=200)
