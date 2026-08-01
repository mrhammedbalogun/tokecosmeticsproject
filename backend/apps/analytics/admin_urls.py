from django.urls import path

from apps.analytics.views import ReportExportView, ReportView

urlpatterns = [
    # The export path is registered BEFORE the detail route so `<str:name>` cannot
    # swallow it — the same ordering the catalogue and orders urlconfs use.
    path("reports/<str:name>/export.csv", ReportExportView.as_view(), name="admin-report-export"),
    path("reports/<str:name>/", ReportView.as_view(), name="admin-report"),
]
