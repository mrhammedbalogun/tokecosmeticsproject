"""Public notification routes. Mounted at `/api/v1/notifications/` by `config/urls.py`.

Outside the `/api/v1/admin/` prefix on purpose — see `views.py`.
"""
from django.urls import path

from apps.notifications.views import RecipientConfirmView

urlpatterns = [
    path("confirm/", RecipientConfirmView.as_view(), name="notification-confirm"),
]
