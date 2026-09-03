"""Combo administration.

`products.manage` throughout — Owner and Manager — for the same reason the catalogue is:
a combo is a shelf decision with a price on it, and the people who set prices are the
people who build bundles. The catalogue's argument against splitting reads and writes
applies here unchanged (`apps/catalog/admin_views.py`): `permission_classes` is a class
attribute, and overriding `get_permissions()` per action would make the declared class —
the thing `test_admin_surface_guard.py` reads — decorative.

DELETING A COMBO IS NOT ELEVATED, unlike deleting a product. A product delete cascades
into order history's FK and destroys a catalogue record; a combo delete removes a
curation, and every order that ever contained one keeps its own snapshot
(`OrderItem.combo_name`). Retiring a bundle is week-to-week marketing work.
"""
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.catalog.models import Product, ProductVariant
from apps.combos.admin_serializers import (
    ComboAdminSerializer,
    ComboListAdminSerializer,
    ProductPickerSerializer,
)
from apps.combos.models import Combo, ComboItem
from apps.core.audit import AdminAuditMixin

PICKER_LIMIT = 8
PICKER_MIN_QUERY = 2


class ComboAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """CRUD for bundles.

    `AdminAuditMixin` is FIRST in the bases so its `dispatch` wraps the viewset's and the
    audit row is written inside the same transaction as the mutation — an unauditable
    write does not happen at all. Same fail-closed arrangement as the catalogue's base
    viewset, and the reason `authentication_classes` is pinned here rather than inherited
    from anything looser.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = ComboAdminSerializer
    audit_serializers = (ComboAdminSerializer,)
    lookup_field = "slug"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status"]
    search_fields = ["name"]
    queryset = (
        Combo.objects.all()
        .prefetch_related(
            "available_countries",
            "prices",
            Prefetch(
                "items",
                queryset=ComboItem.objects.select_related("variant__product").prefetch_related(
                    "variant__prices", "variant__images", "variant__product__images"
                ),
            ),
        )
        .order_by("position", "-updated_at")
    )

    def get_serializer_class(self):
        if self.action == "list":
            return ComboListAdminSerializer
        return ComboAdminSerializer

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
        url_path="image",
    )
    def image(self, request, slug=None):
        """The featured image, uploaded on its own.

        SEPARATE FROM THE MAIN BODY, and for a concrete reason rather than symmetry with
        the catalogue: the combo body carries a nested `items` array, and a nested array
        does not survive a multipart encoding — it arrives as flat form fields the
        serializer reads as garbage. Keeping the file on its own route means the body
        stays JSON and stays whole.
        """
        combo = self.get_object()
        uploaded = request.data.get("image")
        if not uploaded:
            return Response({"image": ["No file was submitted."]}, status=400)
        combo.image = uploaded
        combo.save(update_fields=["image", "updated_at"])
        return Response(ComboAdminSerializer(combo, context={"request": request}).data)


class ComboProductSearchView(AdminAuditMixin, APIView):
    """The builder's product box: `?q=shea` → matching products with their variants,
    pictures and per-market prices.

    A DEDICATED ENDPOINT rather than reusing `GET /admin/products/?search=`, because the
    two answer different questions. The products list returns the catalogue admin's row
    shape — no variant option values, no per-market prices — so a builder using it would
    need one follow-up request per suggestion just to know what picking it would cost.
    This returns everything a suggestion row draws AND everything picking it changes, in
    one response, which is what lets the pricing panel update as the person types.

    Draft and archived products are included on purpose: a bundle is often built ahead of
    the launch it belongs to. What keeps an unsellable one out of the shops is
    `available_in`, which is asked at read time and again at add-to-cart.

    `AdminAuditMixin` carries no cost here and is not optional: every admin view must be
    IN the mechanism (`test_audit_guard.py`), and the mixin writes nothing for a read
    unless the view is declared read-audited. This one is not — it returns catalogue
    rows, no personal data, and it fires on every keystroke of a search box. Auditing it
    would bury the rows that matter under a hundred a minute.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    # Declared rather than derived: this view has no queryset and no serializer_class for
    # the mixin to read a label off, and an audit row with an empty `model_label` is a row
    # nobody can search for. It writes none today (reads here are not audited, see the
    # docstring), and the label is what keeps that true if one is ever added.
    audit_model_label = "catalog.Product"

    def get(self, request):
        term = (request.query_params.get("q") or "").strip()
        if len(term) < PICKER_MIN_QUERY:
            return Response([])
        products = (
            Product.objects.filter(name__icontains=term)
            .prefetch_related(
                "images",
                Prefetch(
                    "variants",
                    queryset=ProductVariant.objects.filter(is_active=True)
                    .prefetch_related("prices", "images")
                    .order_by("position", "id"),
                ),
            )
            .order_by("name")[:PICKER_LIMIT]
        )
        return Response(ProductPickerSerializer(products, many=True).data)
