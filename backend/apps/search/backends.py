"""Search backends. Postgres trigram today; get_backend() will branch to Meilisearch
(Plan-07b) when settings.MEILISEARCH_URL is set. Both return an ordered, price-annotated
Product queryset so the view can page it through the existing ProductListSerializer.
"""
from __future__ import annotations

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, OuterRef, Q, Subquery, Sum

from apps.catalog.models import Product
from apps.catalog.services import annotate_min_price

SORTS = {"price_asc": "min_price", "price_desc": "-min_price", "newest": "-published_at"}
_TRGM_THRESHOLD = 0.2


class PostgresSearchBackend:
    def _base(self, country):
        qs = (
            Product.objects.filter(status="active")
            .filter(Q(available_countries__isnull=True) | Q(available_countries=country))
            .distinct()
            .select_related("brand")
            .prefetch_related("images", "variants")  # PLAN-13 D2: variants for card default-variant fields
        )
        return annotate_min_price(qs, country).filter(min_price__isnull=False)  # priced/sellable

    def _apply_filters(self, qs, params, country):
        if params.get("category"):
            qs = qs.filter(categories__slug=params["category"])
        if params.get("brand"):
            qs = qs.filter(brand__slug=params["brand"])
        for key, lookup in (("price_min", "min_price__gte"), ("price_max", "min_price__lte")):
            raw = params.get(key)
            if raw:
                try:
                    qs = qs.filter(**{lookup: float(raw)})
                except ValueError:
                    pass  # ignore unparseable price
        if params.get("in_stock") in ("1", "true", "True"):
            from apps.inventory.models import StockItem

            avail = (
                StockItem.objects.filter(
                    variant__product=OuterRef("pk"),
                    warehouse__is_active=True,
                    warehouse__serves_countries=country,
                )
                .values("variant__product")
                .annotate(t=Sum(F("quantity") - F("reserved")))
                .values("t")
            )
            qs = qs.annotate(_avail=Subquery(avail)).filter(_avail__gt=0)
        return qs

    def search_queryset(self, params, country):
        qs = self._apply_filters(self._base(country), params, country)
        q = (params.get("q") or "").strip()
        if q and len(q) >= 3:
            qs = qs.annotate(sim=TrigramSimilarity("name", q)).filter(
                Q(sim__gt=_TRGM_THRESHOLD) | Q(name__icontains=q) | Q(brand__name__icontains=q)
            )
            default_order = ["-sim"]
        elif q:
            qs = qs.filter(Q(name__istartswith=q) | Q(name__icontains=q))
            default_order = ["name"]
        else:
            default_order = ["-published_at"]
        sort = SORTS.get(params.get("sort", ""))
        return qs.order_by(*([sort] if sort else default_order), "name")

    def suggest(self, q, country, limit=6):
        q = (q or "").strip()
        if not q:
            return []
        qs = self._base(country)
        if len(q) >= 3:
            qs = qs.annotate(sim=TrigramSimilarity("name", q)).filter(
                Q(sim__gt=_TRGM_THRESHOLD) | Q(name__icontains=q)
            ).order_by("-sim")
        else:
            qs = qs.filter(name__istartswith=q).order_by("name")
        return [{"name": p.name, "slug": p.slug} for p in qs[:limit]]


def get_backend():
    # Plan-07b: `if settings.MEILISEARCH_URL: return MeilisearchBackend()`
    return PostgresSearchBackend()
