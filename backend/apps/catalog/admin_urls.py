from rest_framework.routers import DefaultRouter

from apps.catalog.admin_views import ProductAdminViewSet

router = DefaultRouter()
router.register("products", ProductAdminViewSet, basename="admin-product")

urlpatterns = router.urls
