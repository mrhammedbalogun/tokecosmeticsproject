from rest_framework.routers import SimpleRouter

from apps.delivery.admin_views import DeliveryOptionAdminViewSet

router = SimpleRouter()
router.register("delivery-options", DeliveryOptionAdminViewSet, basename="admin-delivery-option")

urlpatterns = router.urls
