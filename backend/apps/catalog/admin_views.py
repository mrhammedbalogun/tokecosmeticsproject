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
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
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
    ProductImage,
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
    # Prefetched for the list. Two groups, and the second was a PRE-EXISTING N+1 that the
    # Task 2 query-budget test exposed rather than introduced:
    #
    #   images / variants__prices — the new thumbnail, variant-count and
    #     priced-currencies columns.
    #   categories / tags / related / available_countries — four M2M fields this
    #     serializer has always rendered, each costing a query PER ROW. A 12-product page
    #     measured 55 queries; the same page now measures 11, and a 24-row page does not
    #     cost twice that. Nothing in the JSON differed either way, which is why it
    #     survived this long.
    queryset = (
        Product.objects.all()
        .prefetch_related(
            "images",
            "variants__prices",
            "categories",
            "tags",
            "related",
            "available_countries",
        )
        .order_by("-created_at")
    )
    lookup_field = "slug"
    # BOTH backends named explicitly. Listing `filter_backends` on a view REPLACES
    # DEFAULT_FILTER_BACKENDS, so adding SearchFilter alone would silently drop
    # DjangoFilterBackend and the `?status=` facet with it — the failure is a filter that
    # is quietly ignored, which looks like "no results match" rather than like a bug.
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status"]
    # `variants__sku` is here because staff search by the SKU printed on the jar, and a
    # SKU belongs to a variant. It is a reverse FK, so the join yields one row per
    # matching variant; DRF's SearchFilter de-duplicates via `must_call_distinct`, and
    # test_search_returns_a_multi_variant_product_exactly_once pins that it stays that
    # way — 18 of 69 production products are multi-variant.
    #
    # NO `^` OR `=` PREFIXES: both compile to something other than `icontains`, and
    # `icontains` is the one lookup the Plan-16 Task 6 indexes were built for
    # (`product_name_upper_trgm`, `variant_sku_trgm`, both on UPPER(col)).
    search_fields = ["name", "variants__sku"]

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
    # The editor's Variants tab asks for ONE product's variants. Unfiltered this endpoint
    # returns all 122 in production, and narrowing that in the browser would serialise
    # every one of them into the RSC payload of a page showing a handful (Plan-16 Task 8).
    filterset_fields = ["product", "is_active"]


class ProductImageAdminViewSet(AdminBaseViewSet):
    """An uploaded image, as an editable thing.

    Before this existed an image could be POSTed to `products/{slug}/images/` and never
    touched again — no delete, no alt text, no reorder. The 17a Images tab needs all
    three, and none of them is a new capability so much as the other half of one that
    already shipped.

    CREATION IS NOT HERE, and that is the point of `http_method_names`. Uploading stays
    on `ProductAdminViewSet.images`, which owns the multipart parsers and binds `product`
    from the URL it was called on. A second create path would be a second place for the
    binding rules to live, and they would drift.

    PUT IS ALSO OUT. `image` is the one field this JSON route cannot write, so a PUT —
    which means "here is the whole record" — would have to silently ignore the file and
    keep it. Refusing is honest; 405 tells the caller to PATCH.
    """

    serializer_class = ProductImageAdminSerializer
    queryset = ProductImage.objects.all()  # Meta.ordering = ["position", "id"]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_fields = ["product", "variant"]


class ProductVideoAdminViewSet(AdminBaseViewSet):
    """Attach/reorder/detach library videos on a product (Videos tab).

    Unlike images there is no multipart create action on the product viewset: the bytes
    go straight to S3 through the cms ticket/finalize pair, so the create here is plain
    JSON and carries `product` in the body. The UPLOAD half of the flow lives behind
    `marketing.manage` (see `MediaAssetAdminViewSet`) — `test_admin_videos.py` pins that
    every `products.manage` role also holds it, so the Videos tab cannot half-break.
    """

    serializer_class = ProductVideoAdminSerializer
    # `select_related`, mirroring the serializer's `asset.file` read — without it the
    # editor's list costs one query per row.
    queryset = ProductVideo.objects.select_related("asset")
    # The editor asks for ONE product's videos; unfiltered this returns the whole
    # catalogue's. Same reasoning as variants/images above.
    filterset_fields = ["product"]


class PriceAdminViewSet(AdminBaseViewSet):
    serializer_class = PriceAdminSerializer
    # The Prices grid is variant x currency, so it fetches by variant and fills cells by
    # currency. `country` is filterable so the grid can SEE a country-level override
    # rather than silently showing the currency-level row underneath it — an edit that
    # appears to succeed and changes nothing is the worst failure this screen can have
    # (17a spec, "The Prices grid, precisely"). Writing overrides is 17c.
    #
    # `variant__product` added in Task 6: the grid needs EVERY price for a product at once,
    # and `variant` is an exact match, so without it the editor would issue one request per
    # variant — ten of them on the largest production product.
    filterset_fields = ["variant", "variant__product", "currency", "country"]
    queryset = Price.objects.select_related("variant", "currency", "country")

    @action(detail=False, methods=["get"])
    def unpriced(self, request):
        """`GET /admin/prices/unpriced/?currency=GBP` — active variants with no price in
        that currency. Plan-17c Task 2.

        The products list answers "what is this product missing?"; this answers the
        question somebody actually has on the day a market opens: "what is not sellable
        HERE yet?" A market needs a price in its currency before the product appears in it
        at all, and all 121 production prices are NGN — so a naive "does it have a price"
        check would report the whole catalogue ready for the UK.

        An action on this viewset rather than a new view: it is the same resource and the
        same `products.manage` scope, and a new class would owe the four guard
        declarations for a read that this one already carries.

        ACTIVE products only. A draft or archived product with no GBP price is not a gap
        in the catalogue, and listing it would pad a checklist that exists to be finished.
        """
        code = (request.query_params.get("currency") or "").strip().upper()
        if not code:
            return Response(
                {"detail": "currency is required, e.g. ?currency=GBP."}, status=400
            )

        variants = (
            ProductVariant.objects.filter(product__status="active")
            .exclude(prices__currency_id=code)
            .select_related("product")
            .order_by("product__name", "sku")
        )
        page = self.paginate_queryset(variants)
        rows = [
            {
                "variant_id": v.id,
                "sku": v.sku,
                "variant_name": v.name,
                "product_name": v.product.name,
                "product_slug": v.product.slug,
            }
            for v in (page if page is not None else variants)
        ]
        return self.get_paginated_response(rows) if page is not None else Response(rows)


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
