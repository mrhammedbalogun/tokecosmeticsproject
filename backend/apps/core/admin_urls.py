"""Audit-log routes, mounted under `/api/v1/admin/` by `config/urls.py`.

Under the admin prefix, like every other admin route, so that
`apps/accounts/tests/test_admin_surface_guard.py` — which discovers the admin surface
by walking that prefix — has an opinion about it. A route mounted anywhere else is a
route the guard cannot see.
"""
from django.urls import path

from apps.core.admin_search import AdminSearchView
from apps.core.admin_views import AuditLogListView

urlpatterns = [
    path("audit/", AuditLogListView.as_view(), name="admin-audit-list"),
    path("search/", AdminSearchView.as_view(), name="admin-search"),
]
