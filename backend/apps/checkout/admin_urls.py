"""Checkout admin routes (Plan-19b). SimpleRouter for the reason catalog gives: a
DefaultRouter's api-root would be an ungated route on the admin prefix."""
from rest_framework.routers import SimpleRouter

from apps.checkout.admin_views import CouponAdminViewSet

router = SimpleRouter()
router.register("coupons", CouponAdminViewSet, basename="admin-coupon")

urlpatterns = router.urls
