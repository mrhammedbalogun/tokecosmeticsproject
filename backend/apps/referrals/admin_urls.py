"""Referral admin routes. SimpleRouter for the list/detail reads, explicit paths for the
three writes — each write is its own view class so it can declare its own scope, which is
what `test_admin_surface_guard` enforces (see `admin_views` for the full reason)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.referrals.admin_views import (
    ApprovePayoutView,
    BlockReferrerView,
    CreateAdjustmentView,
    MarkPayoutPaidView,
    PayoutQueueViewSet,
    ReferrerAdjustmentsView,
    ReferrerListView,
    RejectPayoutView,
)

router = SimpleRouter()
router.register("referral-payouts", PayoutQueueViewSet, basename="admin-referral-payout")

urlpatterns = router.urls + [
    path("referral-payouts/<int:pk>/approve/", ApprovePayoutView.as_view(),
         name="admin-referral-payout-approve"),
    path("referral-payouts/<int:pk>/reject/", RejectPayoutView.as_view(),
         name="admin-referral-payout-reject"),
    path("referral-payouts/<int:pk>/mark-paid/", MarkPayoutPaidView.as_view(),
         name="admin-referral-payout-mark-paid"),
    # Referrers are keyed by USER id, not profile id: every other admin surface that
    # names a customer uses the user id, and two id spaces for one person is how a
    # support conversation ends up about the wrong account.
    path("referrers/", ReferrerListView.as_view(), name="admin-referrer-list"),
    path("referrers/<int:pk>/adjustments/", ReferrerAdjustmentsView.as_view(),
         name="admin-referrer-adjustments"),
    path("referrers/<int:pk>/block/", BlockReferrerView.as_view(), name="admin-referrer-block"),
    path("referrers/<int:pk>/adjust/", CreateAdjustmentView.as_view(),
         name="admin-referrer-adjust"),
]
