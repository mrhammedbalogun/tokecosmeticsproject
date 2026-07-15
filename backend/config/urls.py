"""Root URL configuration.

`/django-admin/` is the low-level Django admin fallback (IP-restricted in prod, Plan-02).
The `/api/v1/...` surface is added in Plan-03.
"""
from django.contrib import admin
from django.urls import path

from apps.core.views import healthz

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("healthz/", healthz),
]
