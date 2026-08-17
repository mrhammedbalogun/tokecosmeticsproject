"""Mounted under `/api/v1/admin/` by `config/urls.py`, like every other admin URLconf.

Under the admin prefix so that `apps/accounts/tests/test_admin_surface_guard.py` — which
discovers the admin surface by walking that prefix — has an opinion about it. A route
mounted anywhere else is a route the guard cannot see.
"""
from rest_framework.routers import SimpleRouter

from apps.notifications.admin_views import NotificationRecipientAdminViewSet

router = SimpleRouter()
router.register(
    "notification-recipients",
    NotificationRecipientAdminViewSet,
    basename="admin-notification-recipient",
)

urlpatterns = router.urls
