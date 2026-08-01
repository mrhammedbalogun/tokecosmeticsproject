from rest_framework.routers import SimpleRouter

from apps.delivery.admin_views import DeliveryOptionAdminViewSet, RegionAdminViewSet

router = SimpleRouter()
router.register("delivery-options", DeliveryOptionAdminViewSet, basename="admin-delivery-option")
router.register("regions", RegionAdminViewSet, basename="admin-region")

urlpatterns = router.urls
