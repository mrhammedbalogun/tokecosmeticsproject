"""The referral endpoints that are NOT about the caller's own account.

Its own module rather than a second list in `urls.py`, because `include()` only ever
reads `urlpatterns` — a `public_urlpatterns` name in that file would silently never be
mounted, and the include would re-expose the whole self-service set under a second
prefix instead.
"""
from django.urls import path

from apps.referrals.views import ReferralCodeLookupView, ReferralTermsView

urlpatterns = [
    path("lookup/", ReferralCodeLookupView.as_view(), name="referral-lookup"),
    path("terms/", ReferralTermsView.as_view(), name="referral-terms"),
]
