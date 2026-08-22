"""The public store locator API. Two endpoints, both anonymous, both read-only.

    GET /api/v1/stores/places/                       -> countries that have stores
    GET /api/v1/stores/places/?country=ng            -> states in NG that have stores
    GET /api/v1/stores/places/?country=ng&state=lagos-> LGAs in Lagos that have stores
    GET /api/v1/stores/?country=ng&state=lagos&area=alimosho

WHY THE CASCADE ONLY OFFERS PLACES THAT HAVE STORES. The obvious alternative is to
reuse `/meta/regions/`, which already serves the same tree for the checkout address
form. It was rejected for two reasons and the first is the real one: a locator whose
LGA dropdown lists all 57 Lagos LGAs invites the customer to pick one of the 50-odd
that will answer "nothing here". That is the interaction failing, not the data. The
second is size — `/meta/regions/` would ship 774 rows to fill a dropdown whose
useful length is single digits.

The consequence, stated plainly: the empty state is only reachable by a SHARED OR
BOOKMARKED link whose store has since been archived, or by a directory with nothing
in it at all. It is still built and still tested, because both of those happen.

WHY SLUGS AND NOT IDS. `?state=lagos` rather than `?state=17`. The brief forbids
showing customers internal database ids, a slug survives a re-seed of the region
table where an autoincrement id does not, and the resulting URL is legible in a
WhatsApp message — which is how this page will actually be shared. The cost is that
renaming a region breaks links to it; `services.resolve_region` documents that trade
and `tests/test_slugs.py` pins the no-collision assumption underneath it.
"""

from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import services
from apps.stores.serializers import PlaceSerializer, StoreSerializer


class StorePlacesView(APIView):
    """The cascade. One URL, three levels, distinguished by what is passed.

    One endpoint rather than three because the client asks the same question at
    every step ("what can I pick next?") and the response says which level it
    answered — three URLs would put that fact in the caller's head instead of in
    the payload. `level` is therefore always present, and the item shape is the
    same at every level bar the two label fields only a country carries.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        country_slug = request.query_params.get("country") or ""
        state_slug = request.query_params.get("state") or ""

        if not country_slug:
            return Response({"level": "country", "parent": None,
                             "items": PlaceSerializer(services.countries_with_stores(),
                                                      many=True).data})
        try:
            country = services.resolve_country(country_slug)
            if not state_slug:
                items = services.states_with_stores(country)
                return Response({
                    "level": "state",
                    "parent": {"slug": _slug(country.name), "name": country.name,
                               "code": country.code},
                    "label": country.state_label,
                    "items": PlaceSerializer(items, many=True).data,
                })
            state = services.resolve_region(state_slug, country=country, parent=None)
        except services.PlaceNotFound as exc:
            raise NotFound(f"We could not find that {exc.args[0]}.")

        items = services.areas_with_stores(state)
        return Response({
            "level": "area",
            "parent": {"slug": _slug(state.name), "name": state.name, "code": None},
            "label": country.area_label,
            "items": PlaceSerializer(items, many=True).data,
        })


class StoreListView(generics.ListAPIView):
    """The results. Paginated with the project default (24) rather than capped.

    A cap would be simpler and would be a silent lie the day an LGA holds 30
    stockists: the page would show 24 and read as complete. The storefront pages
    through it with a "Show more" control.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    serializer_class = StoreSerializer
    filter_backends: list = []  # the query IS the filter; see get_queryset

    def get_queryset(self):
        params = self.request.query_params
        try:
            country = services.resolve_country(params.get("country") or "")
            state = area = None
            if params.get("state"):
                state = services.resolve_region(
                    params["state"], country=country, parent=None
                )
                if params.get("area"):
                    area = services.resolve_region(
                        params["area"], country=country, parent=state
                    )
        except services.PlaceNotFound as exc:
            raise NotFound(f"We could not find that {exc.args[0]}.")
        return services.stores_in(country, state, area)


def _slug(value: str) -> str:
    from apps.stores.normalize import slugify_name

    return slugify_name(value)
