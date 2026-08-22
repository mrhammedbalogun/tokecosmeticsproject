from rest_framework.routers import SimpleRouter

from apps.stores.admin_views import StoreLocationAdminViewSet

router = SimpleRouter()
router.register("stores", StoreLocationAdminViewSet, basename="admin-store")

urlpatterns = router.urls
