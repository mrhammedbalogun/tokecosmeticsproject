from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.catalog.admin_views import (
    BrandAdminViewSet,
    CategoryAdminViewSet,
    CollectionAdminViewSet,
    PriceAdminViewSet,
    ProductAdminViewSet,
    ProductCSVExportView,
    ProductCSVImportView,
    ProductVariantAdminViewSet,
    ProductVideoAdminViewSet,
    TagAdminViewSet,
)

router = DefaultRouter()
router.register("products", ProductAdminViewSet, basename="admin-product")
router.register("categories", CategoryAdminViewSet, basename="admin-category")
router.register("brands", BrandAdminViewSet, basename="admin-brand")
router.register("tags", TagAdminViewSet, basename="admin-tag")
router.register("collections", CollectionAdminViewSet, basename="admin-collection")
router.register("variants", ProductVariantAdminViewSet, basename="admin-variant")
router.register("videos", ProductVideoAdminViewSet, basename="admin-video")
router.register("prices", PriceAdminViewSet, basename="admin-price")

# Explicit CSV paths BEFORE the router so `products/export.csv` isn't swallowed by the
# router's `products/<slug>/` detail route.
urlpatterns = [
    path("products/export.csv", ProductCSVExportView.as_view(), name="admin-product-export"),
    path("products/import.csv", ProductCSVImportView.as_view(), name="admin-product-import"),
] + router.urls
