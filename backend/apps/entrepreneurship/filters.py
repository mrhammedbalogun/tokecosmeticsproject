"""Admin list filtering for the programme applications. SQL, never the browser.

The same rule `apps.stores.filters` and `apps.careers.filters` state: a client-side
filter over a paginated response filters the visible page rather than the data, which on
a table of applicants means a search that quietly misses the student you are looking for.
"""
from django.db.models import Q
from django_filters import rest_framework as filters

from apps.entrepreneurship.models import APPLICATION_STATUS_CHOICES, ProgramApplication


class ProgramApplicationFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=APPLICATION_STATUS_CHOICES)
    country = filters.CharFilter(field_name="country_id", lookup_expr="iexact")
    q = filters.CharFilter(method="filter_search", label="Name, email, phone or school")

    class Meta:
        model = ProgramApplication
        fields = ["status", "country", "q"]

    def filter_search(self, queryset, name, value):
        """Name, email, school and course — and the phone by SUFFIX as well as substring.

        Same trick as the store directory and the careers table: a reviewer holding a
        WhatsApp message types the number the way the student wrote it ("0802 390 0964")
        and the row is stored E.164 ("+2348023900964"). Without the suffix match the
        search silently finds nothing and reads as "that application is gone".

        `institution` is in the match set because it is how these are actually looked
        up in practice — "did anyone from UNILAG apply?" is the question a coordinator
        arrives with, far more often than a name they already know.
        """
        term = (value or "").strip()
        if not term:
            return queryset
        matches = (
            Q(full_name__icontains=term)
            | Q(email__icontains=term)
            | Q(phone__icontains=term)
            | Q(institution__icontains=term)
            | Q(course_of_study__icontains=term)
        )
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 6:
            matches |= Q(phone__endswith=digits[-9:])
        return queryset.filter(matches)
