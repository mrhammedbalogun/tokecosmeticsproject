from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.marketing.admin_views import (
    ConversionEventAdminViewSet,
    MarketingChannelAdminViewSet,
    MarketingSettingsView,
)

router = SimpleRouter()
router.register("marketing/channels", MarketingChannelAdminViewSet, basename="admin-marketing-channel")
router.register("marketing/events", ConversionEventAdminViewSet, basename="admin-marketing-event")

urlpatterns = [
    path("marketing/settings/", MarketingSettingsView.as_view(), name="admin-marketing-settings"),
    *router.urls,
]
