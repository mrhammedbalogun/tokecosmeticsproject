"""Catalogue admin routes.

SimpleRouter, not DefaultRouter, and the difference matters here. `DefaultRouter` adds
an `APIRootView` at the router's mount point — which, mounted under `api/v1/admin/`,
is an endpoint on the admin surface that inherits the project defaults: `AllowAny` and
stock `JWTAuthentication`. It answers unauthenticated GETs with a directory of the
admin API. Not a data leak, but a route on this surface that none of the Plan-16
controls touch, and `test_admin_surface_guard.py` refuses to let one exist.

SimpleRouter generates the identical viewset routes without that root view and without
the `.json` format-suffix duplicates. Nothing consumed either.
"""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.catalog.admin_views import (
    BrandAdminViewSet,
    CategoryAdminViewSet,
    CollectionAdminViewSet,
    PriceAdminViewSet,
    ProductAdminViewSet,
    ProductCSVExportView,
    ProductCSVImportView,
    ProductImageAdminViewSet,
    ProductVariantAdminViewSet,
    ProductVideoAdminViewSet,
    TagAdminViewSet,
)

router = SimpleRouter()
router.register("products", ProductAdminViewSet, basename="admin-product")
router.register("categories", CategoryAdminViewSet, basename="admin-category")
router.register("brands", BrandAdminViewSet, basename="admin-brand")
router.register("tags", TagAdminViewSet, basename="admin-tag")
router.register("collections", CollectionAdminViewSet, basename="admin-collection")
router.register("variants", ProductVariantAdminViewSet, basename="admin-variant")
router.register("images", ProductImageAdminViewSet, basename="admin-image")
router.register("videos", ProductVideoAdminViewSet, basename="admin-video")
router.register("prices", PriceAdminViewSet, basename="admin-price")

# Explicit CSV paths BEFORE the router so `products/export.csv` isn't swallowed by the
# router's `products/<slug>/` detail route.
urlpatterns = [
    path("products/export.csv", ProductCSVExportView.as_view(), name="admin-product-export"),
    path("products/import.csv", ProductCSVImportView.as_view(), name="admin-product-import"),
] + router.urls
