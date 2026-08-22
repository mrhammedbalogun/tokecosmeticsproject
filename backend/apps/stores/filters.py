"""Admin list filtering. Combinable by construction — django-filter ANDs every
filter that was supplied, so "Nigeria + Lagos + Alimosho + Authorized Distributor
+ Active" narrows exactly as a reader expects, and each one alone works too.

Filtering happens in SQL, never in the browser: the brief is explicit that this
table is expected to grow, and a client-side filter over a paginated response
would filter the visible page rather than the data.
"""

from django.db.models import Q
from django_filters import rest_framework as filters

from apps.stores.models import STORE_TYPE_CHOICES, StoreLocation

STATUS_CHOICES = [
    ("active", "Active"),
    ("inactive", "Inactive"),
    ("archived", "Archived"),
    ("all", "All (including archived)"),
]


class StoreLocationFilter(filters.FilterSet):
    country = filters.CharFilter(field_name="country__code", lookup_expr="iexact")
    state_region = filters.NumberFilter(field_name="state_region_id")
    area_region = filters.NumberFilter(field_name="area_region_id")
    store_type = filters.ChoiceFilter(choices=STORE_TYPE_CHOICES)
    status = filters.ChoiceFilter(choices=STATUS_CHOICES, method="filter_status")
    q = filters.CharFilter(method="filter_search", label="Name, address or phone")

    class Meta:
        model = StoreLocation
        fields = ["country", "state_region", "area_region", "store_type", "status", "q"]

    def filter_status(self, queryset, name, value):
        """The three real states plus an "everything" escape hatch.

        The view has already excluded archived rows when this filter is ABSENT (see
        `StoreLocationAdminViewSet.get_queryset`) — the default view of a directory
        is the directory, not its history.
        """
        if value == "active":
            return queryset.filter(is_active=True, archived_at__isnull=True)
        if value == "inactive":
            return queryset.filter(is_active=False, archived_at__isnull=True)
        if value == "archived":
            return queryset.filter(archived_at__isnull=False)
        return queryset  # "all"

    def filter_search(self, queryset, name, value):
        """Name, address, city and both phone numbers.

        Phones are stored E.164 and are searched by SUFFIX as well as substring, so
        typing the number the way it is printed on the shop's door ("0802 390 0964")
        finds the row stored as "+2348023900964". Anything non-numeric in the term
        is stripped for that comparison only.
        """
        term = (value or "").strip()
        if not term:
            return queryset
        matches = (
            Q(name__icontains=term)
            | Q(address__icontains=term)
            | Q(city_text__icontains=term)
            | Q(phone__icontains=term)
            | Q(phone_alt__icontains=term)
        )
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 6:
            suffix = digits[-9:]
            matches |= (
                Q(phone__endswith=suffix)
                | Q(phone_alt__endswith=suffix)
                | Q(whatsapp_phone__endswith=suffix)
            )
        return queryset.filter(matches)
