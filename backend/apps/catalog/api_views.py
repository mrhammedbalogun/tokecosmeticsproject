from django.core.cache import cache as _cache
from django.db.models import Q
from rest_framework import generics, permissions
from rest_framework.response import Response

from apps.catalog.api_serializers import (
    BrandSerializer,
    CategorySerializer,
    CollectionSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
)
from apps.catalog.models import Brand, Category, Collection, Product
from apps.catalog.services import CATALOG_CACHE_TTL, annotate_min_price, catalog_cache_key


class CatalogCacheMixin:
    """Cache list/retrieve response payloads for CATALOG_CACHE_TTL seconds, keyed on
    (cache-version, country, path, querystring). The version bumps on any catalog write
    (see signals.py), so a write invalidates every cached catalog response at once.
    """

    def _cached_response(self, request, produce):
        key = catalog_cache_key(request)
        data = _cache.get(key)
        if data is None:
            data = produce().data
            _cache.set(key, data, CATALOG_CACHE_TTL)
        return Response(data)

    def list(self, request, *args, **kwargs):
        return self._cached_response(
            request, lambda: super(CatalogCacheMixin, self).list(request, *args, **kwargs)
        )

    def retrieve(self, request, *args, **kwargs):
        return self._cached_response(
            request, lambda: super(CatalogCacheMixin, self).retrieve(request, *args, **kwargs)
        )


ORDERING = {
    "newest": "-published_at",
    "price_asc": "min_price",
    "price_desc": "-min_price",
    "best_selling": "-published_at",  # PLAN-10: real best-selling from order data
}


class ProductListView(CatalogCacheMixin, generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        country = self.request.country
        qs = (
            Product.objects.filter(status="active")
            .prefetch_related("images", "variants")  # PLAN-13 D2: variants for card default-variant fields
            .select_related("brand")
        )
        # Restrict to products available in this country (empty available_countries = all).
        qs = qs.filter(
            Q(available_countries__isnull=True) | Q(available_countries=country)
        ).distinct()
        qs = annotate_min_price(qs, country)
        # "hide until priced": drop rows with no resolvable price in this currency.
        qs = qs.filter(min_price__isnull=False)

        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(categories__slug=p["category"])
        if p.get("brand"):
            qs = qs.filter(brand__slug=p["brand"])
        if p.get("tag"):
            qs = qs.filter(tags__slug=p["tag"])
        if p.get("collection"):
            qs = qs.filter(collections__slug=p["collection"])
        if p.get("price_min"):
            qs = qs.filter(min_price__gte=p["price_min"])
        if p.get("price_max"):
            qs = qs.filter(min_price__lte=p["price_max"])
        if p.get("q"):  # PLAN-07: replace with Meilisearch
            term = p["q"]
            qs = qs.filter(Q(name__icontains=term) | Q(short_description__icontains=term))
        # in_stock filter is a no-op until PLAN-06 inventory exists.

        ordering = ORDERING.get(p.get("ordering", "newest"), "-published_at")
        return qs.order_by(ordering, "name").distinct()


class ProductDetailView(CatalogCacheMixin, generics.RetrieveAPIView):
    serializer_class = ProductDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return (
            Product.objects.filter(status="active")
            .select_related("brand")
            .prefetch_related("images", "variants", "related__images")
        )

    def get_object(self):
        from django.http import Http404

        from apps.catalog.services import sellable_in

        obj = super().get_object()
        if not sellable_in(obj, self.request.country):
            raise Http404("Not available in this country.")
        return obj


class CategoryTreeView(CatalogCacheMixin, generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        # Return roots only; children are nested by the serializer.
        return (
            Category.objects.filter(is_active=True, parent__isnull=True)
            .prefetch_related("children")
            .order_by("sort_order", "name")
        )


class BrandListView(CatalogCacheMixin, generics.ListAPIView):
    serializer_class = BrandSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    queryset = Brand.objects.filter(is_active=True).order_by("name")


class CollectionDetailView(CatalogCacheMixin, generics.RetrieveAPIView):
    serializer_class = CollectionSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"
    queryset = Collection.objects.filter(is_active=True)
