"""URLs for the delivery-partner portal (Plan-39), mounted at /api/v1/partner/."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.delivery.partner_views import (
    PartnerLgaListView,
    PartnerLoginView,
    PartnerMeView,
    PartnerStateListView,
    PartnerZoneViewSet,
    PublicRatesView,
)

router = SimpleRouter()
router.register("zones", PartnerZoneViewSet, basename="partner-zone")

urlpatterns = [
    path("auth/login/", PartnerLoginView.as_view(), name="partner-login"),
    path("me/", PartnerMeView.as_view(), name="partner-me"),
    path("states/", PartnerStateListView.as_view(), name="partner-states"),
    path("lgas/", PartnerLgaListView.as_view(), name="partner-lgas"),
    # Public, no auth: the marketers' read-only price list (see PublicRatesView).
    path("rates/", PublicRatesView.as_view(), name="partner-public-rates"),
] + router.urls
