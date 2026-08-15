"""Customer referral endpoints, mounted under /api/v1/me/ alongside addresses and the
wishlist — this is self-service about the caller's own account, which is what that
prefix means."""
from django.urls import path

from apps.referrals.views import (
    CommissionListView,
    PayoutMethodView,
    PayoutRequestListCreateView,
    ReferralOverviewView,
)

urlpatterns = [
    path("referrals/", ReferralOverviewView.as_view(), name="referral-overview"),
    path("referrals/commissions/", CommissionListView.as_view(), name="referral-commissions"),
    path("referrals/payout-methods/", PayoutMethodView.as_view(), name="referral-payout-methods"),
    path("referrals/payouts/", PayoutRequestListCreateView.as_view(), name="referral-payouts"),
]
