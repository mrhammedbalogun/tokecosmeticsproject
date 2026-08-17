"""Public notification routes. Mounted at `/api/v1/notifications/` by `config/urls.py`.

Outside the `/api/v1/admin/` prefix on purpose — see `views.py` for why an admin-prefix
waiver would have been the wrong shape for a page no staff member ever loads.
"""
from django.urls import path

from apps.notifications.views import RecipientConfirmView

urlpatterns = [
    path("confirm/", RecipientConfirmView.as_view(), name="notification-confirm"),
]
