"""Staff-management routes, mounted under `/api/v1/admin/` by `config/urls.py`.

WHY THE PUBLIC ACCEPT ENDPOINT LIVES UNDER THE ADMIN PREFIX. It could have gone next
to the other public auth endpoints in `urls.py`, and the argument for putting it here
instead is about what the guard test can see: `test_admin_surface_guard.py` discovers
admin views by walking this prefix, so a route mounted here is one the guard has an
opinion about. Under `/api/v1/auth/` it would simply be invisible to that walker — a
public staff-creation endpoint that no admin-surface check ever looks at. Here it must
appear in the guard's explicit `PUBLIC_ADMIN_ROUTES` allowlist, which is what makes
"public" a recorded decision rather than an absence.
"""
from django.urls import path

from .views import (
    StaffInviteAcceptView,
    StaffInviteListCreateView,
    StaffInviteRevokeView,
)

urlpatterns = [
    path("staff/invites/", StaffInviteListCreateView.as_view(), name="admin-staff-invites"),
    # Before the <int:pk> route only for readability; the converters cannot collide.
    path("staff/invites/accept/", StaffInviteAcceptView.as_view(), name="staff-invite-accept"),
    path(
        "staff/invites/<int:pk>/revoke/",
        StaffInviteRevokeView.as_view(),
        name="admin-staff-invite-revoke",
    ),
]
