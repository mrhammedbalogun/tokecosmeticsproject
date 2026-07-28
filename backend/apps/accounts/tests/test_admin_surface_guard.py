"""The guard that keeps the admin surface from quietly reopening.

This walks the live URLconf rather than importing view classes directly, because
the thing being protected is what is actually ROUTED — a view can be perfect and
still be reachable through a second, unguarded path.

WHY EQUALITY AND NOT MEMBERSHIP. `authentication_classes` must be EXACTLY
`[AdminJWTAuthentication]`. A list that also contains stock `JWTAuthentication`
re-opens the bypass in full: DRF tries each authenticator in order and takes the
first that returns a user, so a customer-issued token would simply be picked up by
the stock class and sail past the admin one. An `in` assertion passes happily on
that list, which is exactly why it is not used here.

WHY THE CLAIM CHECK LIVES IN AUTHENTICATION AND NOT ONLY IN PERMISSIONS. Getting
authentication wrong fails CLOSED — a view that forgets its permission class still
sees a customer token as *unauthenticated* and answers 401. A permission-only check
fails OPEN: forget it once and the customer token walks in. This test enforces the
first arrangement so the second can never be introduced by accident.

TASK 2 EXTENDS THIS TEST. `ADMIN_SURFACE` below currently holds only the endpoints
that exist after Plan-16 Task 1. As each of the 18 `IsAdminUser` sites in
catalog/inventory/orders/payments/shipping is retrofitted, add its URL name here
with the scope it must require. Task 2 also adds the complementary sweep — walk
every route under `/api/v1/admin/` and fail on any that is still using bare
`IsAdminUser` — which cannot be written yet because today every one of them is.
"""
import pytest
from django.urls import get_resolver, reverse
from rest_framework.permissions import IsAdminUser

from apps.accounts.authentication import AdminJWTAuthentication

# url name -> the scope its permission class must require, or None for endpoints
# that deliberately gate on is_staff alone.
ADMIN_SURFACE: dict[str, str | None] = {
    # admin-me answers "who am I and what may I do". Every staff member must be able
    # to ask it, including one whose role grants nothing yet, so it holds no scope.
    "admin_me": None,
}


def _view_class_for(url_name):
    """Resolve a URL name through the real URLconf to the view class behind it."""
    match = get_resolver().resolve(reverse(url_name))
    view_class = getattr(match.func, "cls", None) or getattr(match.func, "view_class", None)
    assert view_class is not None, f"{url_name} does not resolve to a class-based view"
    return view_class


@pytest.mark.parametrize("url_name", sorted(ADMIN_SURFACE))
def test_admin_view_authenticates_with_the_admin_class_only(url_name):
    view_class = _view_class_for(url_name)
    assert view_class.authentication_classes == [AdminJWTAuthentication], (
        f"{url_name} ({view_class.__name__}) must authenticate with "
        f"AdminJWTAuthentication and nothing else — got "
        f"{[c.__name__ for c in view_class.authentication_classes]}"
    )


@pytest.mark.parametrize("url_name", sorted(ADMIN_SURFACE))
def test_admin_view_requires_staff_or_a_scope(url_name):
    view_class = _view_class_for(url_name)
    required_scope = ADMIN_SURFACE[url_name]
    permissions = view_class.permission_classes
    assert permissions, f"{url_name} has no permission_classes at all"

    if required_scope is None:
        assert IsAdminUser in permissions, f"{url_name} must require is_staff"
    else:
        scopes = {getattr(p, "scope", None) for p in permissions}
        assert required_scope in scopes, (
            f"{url_name} must require the {required_scope!r} scope; got {scopes}"
        )


def test_the_admin_token_endpoint_is_not_itself_behind_the_admin_class():
    """Sanity check on the guard's own boundary: admin-token/ MINTS the claim, so it
    cannot require it — a login that demanded an admin token to obtain an admin token
    would be unreachable. It is listed nowhere in ADMIN_SURFACE for that reason, and
    this test exists so that omission reads as deliberate rather than forgotten."""
    view_class = _view_class_for("admin_token_obtain_pair")
    assert "admin_token_obtain_pair" not in ADMIN_SURFACE
    assert AdminJWTAuthentication not in view_class.authentication_classes
