from rest_framework.routers import DefaultRouter

from apps.catalog.admin_views import (
    BrandAdminViewSet,
    CategoryAdminViewSet,
    CollectionAdminViewSet,
    PriceAdminViewSet,
    ProductAdminViewSet,
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

urlpatterns = router.urls
