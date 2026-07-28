from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AccountDeletionView,
    AdminLoginView,
    AdminMeView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
    RegisterView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("token/", LoginView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Staff auth. `token/refresh/` is shared deliberately: a refresh token proves
    # nothing about is_staff by itself, and the admin app's cookie jar is separate
    # (different origin), so a second refresh endpoint would add surface without
    # adding a check. Staff-ness is re-evaluated on every request by the permission
    # classes, not by which endpoint issued the token.
    path("admin-token/", AdminLoginView.as_view(), name="admin_token_obtain_pair"),
    path("admin-me/", AdminMeView.as_view(), name="admin_me"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("password/change/", PasswordChangeView.as_view(), name="password_change"),
    path("account/delete/", AccountDeletionView.as_view(), name="account_delete"),
    path("password/reset/", PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify_email"),
]
