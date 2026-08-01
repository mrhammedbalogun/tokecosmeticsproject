from rest_framework.routers import SimpleRouter

from apps.cms.admin_views import PageAdminViewSet

router = SimpleRouter()
router.register("pages", PageAdminViewSet, basename="admin-page")

urlpatterns = router.urls
