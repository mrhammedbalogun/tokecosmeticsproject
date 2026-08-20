"""URLs for the delivery-partner portal (Plan-39), mounted at /api/v1/partner/."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.delivery.partner_views import (
    PartnerLgaListView,
    PartnerLoginView,
    PartnerMeView,
    PartnerZoneViewSet,
)

router = SimpleRouter()
router.register("zones", PartnerZoneViewSet, basename="partner-zone")

urlpatterns = [
    path("auth/login/", PartnerLoginView.as_view(), name="partner-login"),
    path("me/", PartnerMeView.as_view(), name="partner-me"),
    path("lgas/", PartnerLgaListView.as_view(), name="partner-lgas"),
] + router.urls
