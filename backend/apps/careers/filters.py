"""Admin list filtering for both careers tables. SQL, never the browser — the same rule
`apps.stores.filters` states: a client-side filter over a paginated response filters the
visible page rather than the data, which on an applications table means a search that
quietly misses the candidate you are looking for.
"""
from django.db.models import Q
from django_filters import rest_framework as filters

from apps.careers.models import (
    APPLICATION_STATUS_CHOICES,
    EMPLOYMENT_TYPE_CHOICES,
    JOB_STATUS_CHOICES,
    JobApplication,
    JobPosting,
)

JOB_LIST_STATUS_CHOICES = JOB_STATUS_CHOICES + [
    ("archived", "Archived"),
    ("all", "All (including archived)"),
]


class JobPostingFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=JOB_LIST_STATUS_CHOICES, method="filter_status")
    employment_type = filters.ChoiceFilter(choices=EMPLOYMENT_TYPE_CHOICES)
    department = filters.CharFilter(lookup_expr="icontains")
    q = filters.CharFilter(method="filter_search", label="Title, department or location")

    class Meta:
        model = JobPosting
        fields = ["status", "employment_type", "department", "q"]

    def filter_status(self, queryset, name, value):
        """The three real states plus archived and an "everything" escape hatch.

        The viewset has already excluded archived rows when this filter is ABSENT — the
        default view of a board is the board, not its history.
        """
        if value == "archived":
            return queryset.filter(archived_at__isnull=False)
        if value == "all":
            return queryset
        return queryset.filter(status=value, archived_at__isnull=True)

    def filter_search(self, queryset, name, value):
        term = (value or "").strip()
        if not term:
            return queryset
        return queryset.filter(
            Q(title__icontains=term)
            | Q(department__icontains=term)
            | Q(summary__icontains=term)
            | Q(locations__label__icontains=term)
        ).distinct()
        # `.distinct()` because the location join fans a posting out to one row per
        # matching city — eleven "Sales Representative" rows for one posting is the exact
        # shape this model was built to stop showing.


class JobApplicationFilter(filters.FilterSet):
    job = filters.NumberFilter(field_name="job_id")
    status = filters.ChoiceFilter(choices=APPLICATION_STATUS_CHOICES)
    location = filters.NumberFilter(field_name="location_id")
    q = filters.CharFilter(method="filter_search", label="Name, email or phone")

    class Meta:
        model = JobApplication
        fields = ["job", "status", "location", "q"]

    def filter_search(self, queryset, name, value):
        """Name, email and phone — and the phone by SUFFIX as well as substring.

        Same trick as the store directory: a reviewer holding a CV types the number the
        way the candidate printed it ("0802 390 0964") and the row is stored E.164
        ("+2348023900964"). Without the suffix match the search silently finds nothing and
        reads as "that application is gone".
        """
        term = (value or "").strip()
        if not term:
            return queryset
        matches = (
            Q(full_name__icontains=term)
            | Q(email__icontains=term)
            | Q(phone__icontains=term)
        )
        digits = "".join(ch for ch in term if ch.isdigit())
        if len(digits) >= 6:
            matches |= Q(phone__endswith=digits[-9:])
        return queryset.filter(matches)
