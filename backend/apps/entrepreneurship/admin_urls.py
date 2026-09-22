from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.entrepreneurship.admin_views import (
    ProgramApplicationAdminViewSet,
    ProgramSettingsAdminView,
)
from apps.entrepreneurship.notification_views import ProgrammeNotificationAdminViewSet

router = SimpleRouter()
router.register(
    "entrepreneurship/applications",
    ProgramApplicationAdminViewSet,
    basename="admin-programme-application",
)
# The screen's counts live at `entrepreneurship/applications/stats/`, an @action on the
# viewset above rather than a view of its own — see its docstring for why the audit
# guard is the reason.

router.register(
    # Who gets emailed when a student applies. Its own scope and its own viewset — see
    # `notification_views.py` for why the event is pinned three ways.
    "entrepreneurship/notifications",
    ProgrammeNotificationAdminViewSet,
    basename="admin-programme-notification",
)

urlpatterns = [
    # BEFORE the router's patterns is not strictly required (the prefixes do not
    # overlap), but keeping the singleton first matches how it reads on the screen: the
    # switch sits above the list it governs.
    path(
        "entrepreneurship/settings/",
        ProgramSettingsAdminView.as_view(),
        name="admin-programme-settings",
    ),
    *router.urls,
]
