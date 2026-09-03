"""The public combo endpoints: `/api/v1/combos/` and `/api/v1/combos/<slug>/`.

Cached through the CATALOGUE's cache version, not one of their own — a combo's price is
derived from catalogue prices, so a product repricing has to flush combo responses too.
`apps/combos/signals.py` bumps the same counter a product edit does.
"""
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound

from apps.catalog.api_views import CatalogCacheMixin
from apps.combos.api_serializers import ComboDetailSerializer, ComboListSerializer
from apps.combos.services import attach_pricing, available_in, visible_combos


class ComboListView(CatalogCacheMixin, generics.ListAPIView):
    """Every bundle buyable in the caller's market, curator's order first.

    FILTERED IN PYTHON, NOT SQL, and deliberately. `available_in` asks the pricing engine
    whether each component resolves in this country — that is a resolution ORDER (exact
    country, then currency-wide, then non-windowed), not a join, and it is not
    expressible as a filter. `visible_combos` narrows the rows and loads every relation
    the check reads, so the loop costs no queries; the list is a curated handful, not a
    catalogue.
    """

    serializer_class = ComboListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        country = self.request.country
        # `attach_pricing` FIRST, so the availability check and the serializer share one
        # answer instead of resolving every component's price twice over.
        priced = attach_pricing(visible_combos(country), country)
        return [c for c in priced if available_in(c, country)]


class ComboDetailView(CatalogCacheMixin, generics.RetrieveAPIView):
    serializer_class = ComboDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_object(self):
        country = self.request.country
        # FILTERED BY SLUG BEFORE the queryset is walked. This used to scan every visible
        # combo to find one, which costs the whole curated list on every product page
        # hit — invisible at three bundles and quadratic-feeling at fifty.
        combo = visible_combos(country).filter(slug=self.kwargs["slug"]).first()
        if combo is not None:
            attach_pricing([combo], country)
        # 404 rather than a page saying "not available here": a combo withdrawn from this
        # market has no content to show, and a stub page would be indexed as one.
        if combo is None or not available_in(combo, country):
            raise NotFound("No combo matches the given query.")
        return combo
