from rest_framework.routers import SimpleRouter

from django.urls import path

from apps.cms.admin_views import (
    BannerAdminViewSet,
    GoogleReviewAdminViewSet,
    GoogleReviewsMetaAdminView,
    HomepageSectionAdminViewSet,
    MediaAssetAdminViewSet,
    MenuItemAdminViewSet,
    PageAdminViewSet,
    TrainingLibraryView,
    TrainingResourceAdminViewSet,
)

router = SimpleRouter()
router.register("pages", PageAdminViewSet, basename="admin-page")
router.register("banners", BannerAdminViewSet, basename="admin-banner")
router.register("media", MediaAssetAdminViewSet, basename="admin-media")
router.register("homepage-sections", HomepageSectionAdminViewSet, basename="admin-homepage-section")
router.register("menu-items", MenuItemAdminViewSet, basename="admin-menu-item")
router.register("google-reviews", GoogleReviewAdminViewSet, basename="admin-google-review")
# The Owner's CRUD; the staff-facing read is the separate path below (two classes on
# purpose — see the viewset docstring).
router.register("training", TrainingResourceAdminViewSet, basename="admin-training")

urlpatterns = router.urls + [
    path("google-reviews-meta/", GoogleReviewsMetaAdminView.as_view(),
         name="admin-google-reviews-meta"),
    path("training-library/", TrainingLibraryView.as_view(), name="admin-training-library"),
]
