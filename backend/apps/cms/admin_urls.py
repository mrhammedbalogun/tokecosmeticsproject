from rest_framework.routers import SimpleRouter

from django.urls import path

from apps.cms.admin_views import (
    BannerAdminViewSet,
    GoogleReviewAdminViewSet,
    GoogleReviewsMetaAdminView,
    HomepageSectionAdminViewSet,
    MenuItemAdminViewSet,
    PageAdminViewSet,
)

router = SimpleRouter()
router.register("pages", PageAdminViewSet, basename="admin-page")
router.register("banners", BannerAdminViewSet, basename="admin-banner")
router.register("homepage-sections", HomepageSectionAdminViewSet, basename="admin-homepage-section")
router.register("menu-items", MenuItemAdminViewSet, basename="admin-menu-item")
router.register("google-reviews", GoogleReviewAdminViewSet, basename="admin-google-review")

urlpatterns = router.urls + [
    path("google-reviews-meta/", GoogleReviewsMetaAdminView.as_view(),
         name="admin-google-reviews-meta"),
]
