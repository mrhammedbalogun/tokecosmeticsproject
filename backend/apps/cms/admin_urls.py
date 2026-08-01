from rest_framework.routers import SimpleRouter

from apps.cms.admin_views import (
    BannerAdminViewSet,
    HomepageSectionAdminViewSet,
    MenuItemAdminViewSet,
    PageAdminViewSet,
)

router = SimpleRouter()
router.register("pages", PageAdminViewSet, basename="admin-page")
router.register("banners", BannerAdminViewSet, basename="admin-banner")
router.register("homepage-sections", HomepageSectionAdminViewSet, basename="admin-homepage-section")
router.register("menu-items", MenuItemAdminViewSet, basename="admin-menu-item")

urlpatterns = router.urls
