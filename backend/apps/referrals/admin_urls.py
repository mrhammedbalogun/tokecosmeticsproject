"""Referral admin routes. SimpleRouter for the list/detail reads, explicit paths for the
three writes — each write is its own view class so it can declare its own scope, which is
what `test_admin_surface_guard` enforces (see `admin_views` for the full reason)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.referrals.admin_views import (
    ApprovePayoutView,
    MarkPayoutPaidView,
    PayoutQueueViewSet,
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
]
