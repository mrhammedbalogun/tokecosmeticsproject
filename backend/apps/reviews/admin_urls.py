from rest_framework.routers import SimpleRouter

from apps.reviews.admin_views import ProductReviewAdminViewSet

# SimpleRouter, never DefaultRouter: DefaultRouter's APIRootView would be an ungated
# public route on the admin prefix (pinned by test_admin_surface_guard).
router = SimpleRouter()
router.register("reviews", ProductReviewAdminViewSet, basename="admin-review")

urlpatterns = router.urls
