"""Combo admin routes.

SimpleRouter, not DefaultRouter, for the reason `apps/catalog/admin_urls.py` sets out at
length: DefaultRouter mounts an `APIRootView` that inherits the project defaults
(`AllowAny`, stock JWT) and answers unauthenticated GETs with a directory of the admin
API — a route on this surface that none of the Plan-16 controls touch, and one
`test_admin_surface_guard.py` refuses to let exist.
"""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.combos.admin_views import ComboAdminViewSet, ComboProductSearchView

router = SimpleRouter()
router.register("combos", ComboAdminViewSet, basename="admin-combo")

# BEFORE the router, so `combos/product-search/` is not swallowed by the router's
# `combos/<slug>/` detail route — the same ordering rule the catalogue's CSV paths follow.
urlpatterns = [
    path(
        "combos/product-search/",
        ComboProductSearchView.as_view(),
        name="admin-combo-product-search",
    ),
] + router.urls
