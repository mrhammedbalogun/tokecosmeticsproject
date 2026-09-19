import hashlib

from django.core.cache import cache
from rest_framework import generics, permissions
from rest_framework.response import Response
from apps.accounts.throttling import ScopedRateThrottle  # XFF-safe; NOT rest_framework.throttling
from rest_framework.views import APIView

from apps.catalog.api_serializers import ProductListSerializer
from apps.catalog.services import CATALOG_CACHE_TTL, catalog_cache_version
from apps.combos.api_serializers import ComboListSerializer
from apps.search.backends import get_backend
from apps.search.combos import MAX_COMBO_RESULTS, search_combos, suggest_combos

# How many suggestions the header dropdown gets, bundles included. Unchanged from when
# products were the only thing in it: the list is a glance, not a result page.
SUGGEST_LIMIT = 6


class SearchView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "search"

    def get_queryset(self):
        from apps.catalog.services import annotate_in_stock, annotate_priced_variant_count

        country = self.request.country
        return annotate_priced_variant_count(
            annotate_in_stock(
                get_backend().search_queryset(self.request.query_params, country), country
            ),
            country,
        )

    def list(self, request, *args, **kwargs):
        """The product page, plus the bundles that match, under their own key.

        `combos` rides ALONGSIDE `results` rather than inside it. The two have different
        payload shapes and different URLs (`/combo/<slug>` vs `/product/<slug>`), and the
        page count would be a lie if a handful of unpaginated bundles were counted into
        it. An older storefront build simply ignores the extra key, which is what makes
        this safe to ship in either deploy order — unlike `suggest` below.

        FIRST PAGE ONLY. The bundle list is not paginated, so repeating it under page 2
        would show the same six boxes on every page of a long result set.
        """
        response = super().list(request, *args, **kwargs)
        if isinstance(response.data, dict):
            response.data["combos"] = self._combos(request)
        return response

    def _combos(self, request):
        """The serialised bundle block, cached the way the combos listing already is.

        THE PRODUCT HALF OF THIS ENDPOINT IS ONE QUERY; THE BUNDLE HALF IS NOT. A combo
        has no `annotate_min_price` equivalent — its price is a walk through the pricing
        engine per component and its stock a SUM per component — so a handful of them
        costs about twenty queries each (`apps/combos/tests/test_query_budget.py`). That
        is what `/combos/` pays too, and it pays it once a minute rather than once a
        request because `CatalogCacheMixin` caches it. Search borrows the same cache and
        the SAME VERSION COUNTER, so a repricing or a combo edit flushes this alongside
        every other catalogue response instead of leaving a stale saving on a card.

        Not the whole response: the product page underneath is `cache: "no-store"` for
        reasons of its own (stock, relevance) and this must not quietly start caching it.
        """
        page = request.query_params.get("page")
        if page not in (None, "", "1"):
            return []
        # Only the params the bundle block actually reads. `page` is excluded because it
        # is pinned to the first page above, so every page-1 spelling shares one entry.
        facets = "\x1f".join(
            str(request.query_params.get(k, ""))
            for k in ("q", "category", "brand", "price_min", "price_max", "in_stock", "sort")
        )
        # HASHED, because `q` is untrusted input of unbounded length and a cache key is
        # neither. Raw, a search for "shea butter" writes a key with a space in it —
        # which memcached rejects outright and Django warns about — and a long enough
        # query silently overruns the backend's key limit. The separator is a control
        # character no query string can contain, so two different facet sets cannot
        # collide by concatenating to the same string.
        digest = hashlib.sha256(facets.encode("utf-8")).hexdigest()[:32]
        key = f"search:combos:{catalog_cache_version()}:{request.country.code}:{digest}"
        data = cache.get(key)
        if data is None:
            combos = search_combos(request.query_params, request.country, MAX_COMBO_RESULTS)
            data = ComboListSerializer(combos, many=True, context={"request": request}).data
            cache.set(key, data, CATALOG_CACHE_TTL)
        return data


class SuggestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "suggest"

    def get(self, request):
        """Up to six suggestions: matching bundles first, products filling the rest.

        EVERY ROW CARRIES A `type`, and that is not decoration. A combo slug and a product
        slug live in separate namespaces and can collide, so a client that assumes
        "product" sends the shopper to `/product/<combo-slug>` and a 404. Products keep
        their existing `name`/`slug`, so the field is additive — but the storefront must
        ship BEFORE this does, or the first combo suggestion is a broken link.

        Bundles go first, capped at two, because a bundle is the answer a shopper did not
        know to ask for; products are what they will find anyway.
        """
        q = request.query_params.get("q", "")
        country = request.country
        combos = suggest_combos(q, country)
        products = get_backend().suggest(q, country, limit=SUGGEST_LIMIT - len(combos))
        return Response(combos + products)
