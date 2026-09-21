"""Public careers routes. All anonymous; see `views` for where the abuse controls sit.

`uploads/direct/` is registered unconditionally so the URLconf does not vary by
environment — a route that exists only in dev is a route whose absence in production is
discovered by a 404 at the worst moment. It refuses itself when a bucket is configured
(`resume_storage.store_direct_upload`).
"""
from django.urls import path

from apps.careers.views import (
    ApplyView,
    JobDetailView,
    JobListView,
    ResumeDirectUploadView,
    ResumeUploadTicketView,
)

urlpatterns = [
    path("jobs/", JobListView.as_view(), name="careers-job-list"),
    # BEFORE the slug detail route: `jobs/<slug>/apply/` is a distinct path, but keeping
    # the two adjacent and ordered makes the precedence obvious to the next reader.
    path("jobs/<slug:slug>/apply/", ApplyView.as_view(), name="careers-apply"),
    path("jobs/<slug:slug>/", JobDetailView.as_view(), name="careers-job-detail"),
    path("uploads/", ResumeUploadTicketView.as_view(), name="careers-upload-ticket"),
    path("uploads/direct/", ResumeDirectUploadView.as_view(), name="careers-upload-direct"),
]
