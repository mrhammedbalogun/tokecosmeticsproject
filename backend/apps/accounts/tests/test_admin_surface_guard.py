"""The guard that keeps the admin surface from quietly reopening.

This walks the live URLconf rather than importing view classes directly, because
the thing being protected is what is actually ROUTED — a view can be perfect and
still be reachable through a second, unguarded path.

WHY IT DISCOVERS RATHER THAN BEING TOLD. Task 1 shipped this as a hand-written list
of URL names, which is a snapshot: a nineteenth admin endpoint added next month is
simply absent from the list, every parametrised test still passes, and the suite
reports green while the surface has a hole. Since every admin route in this project
lives under the `/api/v1/admin/` prefix (plus the two `/api/v1/auth/admin-*`
endpoints, named explicitly below), the URLconf itself can be asked what exists.
`test_every_routed_admin_view_is_declared` then makes forgetting the declaration a
FAILURE rather than a silence — that is the whole difference between a test that
guarantees something and a test that documents a moment.

The prefix is the load-bearing assumption and it is deliberately a convention, not a
guess: `config/urls.py` mounts all five admin URLconfs under `api/v1/admin/`. If a
future plan mounts admin routes elsewhere, this file must learn about it — which is
why the escape hatch below (`ADMIN_VIEWS_OUTSIDE_THE_PREFIX`) is a short explicit
list rather than a heuristic. Heuristics considered and rejected: "any view class
whose name starts with Admin" (misses `OrderRefundView`, `QuoteFreightView`,
`StockItemAdminViewSet`), and "any view whose permission is a HasAdminScope
subclass" (circular — it can only find views that already did the right thing, so it
can never catch the one that forgot).

WHY EQUALITY AND NOT MEMBERSHIP. `authentication_classes` must be EXACTLY
`[AdminJWTAuthentication]`. A list that also contains stock `JWTAuthentication`
re-opens the bypass when the stock class is listed first: DRF takes the first
authenticator that returns a user, and a customer-issued token sails past the admin
one. Listed second it is inert, because the admin class raises and DRF re-raises
rather than trying the next authenticator — verified by mutation, and written up in
`apps/accounts/authentication.py`. Both orderings are rejected here anyway: an
authentication list is exactly the kind of line a reviewer's eye slides over, and
"safe in one of its two orderings" is not a property to depend on. An `in` assertion
passes happily on both, which is why it is not used.

WHY THE CLAIM CHECK LIVES IN AUTHENTICATION AND NOT ONLY IN PERMISSIONS. Getting
authentication wrong fails CLOSED — a view that forgets its permission class still
sees a customer token as *unauthenticated* and answers 401. A permission-only check
fails OPEN: forget it once and the customer token walks in. This test enforces the
first arrangement so the second can never be introduced by accident.

WHAT THIS FILE DOES NOT CHECK is behaviour: that the declared scope actually keeps
the wrong role out over real HTTP, with the right status code, is
`test_admin_role_matrix.py`. This file checks the wiring; that one checks the wire.
"""
import pytest
from django.urls import get_resolver, reverse
from rest_framework.permissions import IsAdminUser
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.authentication import AdminJWTAuthentication

# Every admin route in the project is mounted under this prefix by config/urls.py.
ADMIN_URL_PREFIX = "api/v1/admin/"

# The admin views that are NOT under that prefix, by URL name. Kept tiny and explicit:
# each entry is a route someone deliberately put somewhere else, and writing it down is
# cheaper than a heuristic that would also have to be trusted. `admin_token_obtain_pair`
# is absent on purpose — see the test at the bottom.
ADMIN_VIEWS_OUTSIDE_THE_PREFIX: tuple[str, ...] = ("admin_me",)

# view class name -> the scope its permission class must require, or None for the
# endpoints that deliberately gate on `is_staff` alone.
#
# This dict is not a list of things to check; it is a declaration that must MATCH what
# the URLconf exposes, in both directions. An entry with no route is dead text; a route
# with no entry fails `test_every_routed_admin_view_is_declared`.
ADMIN_SURFACE: dict[str, str | None] = {
    # --- catalog: everything here writes the product catalogue -------------------
    "ProductAdminViewSet": "products.manage",
    "CategoryAdminViewSet": "products.manage",
    "BrandAdminViewSet": "products.manage",
    "TagAdminViewSet": "products.manage",
    "CollectionAdminViewSet": "products.manage",
    "ProductVariantAdminViewSet": "products.manage",
    "ProductVideoAdminViewSet": "products.manage",
    "PriceAdminViewSet": "products.manage",
    "ProductCSVExportView": "products.manage",
    "ProductCSVImportView": "products.manage",
    # --- inventory ---------------------------------------------------------------
    "StockItemAdminViewSet": "products.manage",
    "StockMovementListView": "products.manage",
    "StockCSVExportView": "products.manage",
    "StockCSVImportView": "products.manage",
    # --- orders: read ------------------------------------------------------------
    "AdminOrderListView": "orders.view",
    "AdminOrderDetailView": "orders.view",
    # --- orders: operational writes, no money ------------------------------------
    # The transition endpoint declares the FLOOR. Cancelling additionally requires
    # orders.manage, checked in the view because one route covers both kinds of move;
    # apps/orders/views.py explains why, and test_admin_role_matrix.py proves it.
    "AdminOrderTransitionView": "orders.operate",
    "AdminOrderTrackingView": "orders.operate",
    "AdminOrderNoteView": "orders.operate",
    # --- orders: money -----------------------------------------------------------
    "AdminRefundsOwedView": "orders.manage",
    "AdminResolveReviewView": "orders.manage",
    "OrderRefundView": "orders.manage",
    "ManualRefundView": "orders.manage",
    "ConfirmManualReceiptView": "orders.manage",
    "QuoteFreightView": "orders.manage",
    "WaiveFreightView": "orders.manage",
    "CancelQuoteView": "orders.manage",
    "FreightReceiptView": "orders.manage",
    # --- accounts ----------------------------------------------------------------
    # admin-me answers "who am I and what may I do". Every staff member must be able
    # to ask it, including one whose role grants nothing yet, so it holds no scope.
    "AdminMeView": None,
}


def _walk(resolver, prefix=""):
    """Yield (full_pattern, url_name, callback) for every leaf route in the URLconf."""
    for entry in resolver.url_patterns:
        pattern = prefix + str(entry.pattern)
        if hasattr(entry, "url_patterns"):
            yield from _walk(entry, pattern)
        else:
            yield pattern, getattr(entry, "name", None), entry.callback


def _view_class(callback):
    """The class behind a routed callback, for both `as_view()` styles DRF produces."""
    return getattr(callback, "cls", None) or getattr(callback, "view_class", None)


def _view_class_for_name(url_name):
    """Resolve a URL name through the real URLconf to the view class behind it."""
    match = get_resolver().resolve(reverse(url_name))
    view_class = _view_class(match.func)
    assert view_class is not None, f"{url_name} does not resolve to a class-based view"
    return view_class


def discover_admin_views() -> dict[str, type]:
    """Every view class reachable on the admin surface, found in the live URLconf.

    Keyed by class name because a single class is routed under many URL names (a DRF
    viewset alone contributes list/detail/action routes) while `permission_classes` and
    `authentication_classes` are attributes of the class — one entry per class is the
    unit the guard actually reasons about.
    """
    found: dict[str, type] = {}
    for pattern, _name, callback in _walk(get_resolver()):
        if not pattern.startswith(ADMIN_URL_PREFIX):
            continue
        view_class = _view_class(callback)
        assert view_class is not None, f"{pattern} does not resolve to a class-based view"
        existing = found.setdefault(view_class.__name__, view_class)
        # Two different classes sharing a name would let one hide behind the other's
        # entry in ADMIN_SURFACE. Cheap to rule out, silent and nasty if it happened.
        assert existing is view_class, f"two admin view classes are named {view_class.__name__}"
    for url_name in ADMIN_VIEWS_OUTSIDE_THE_PREFIX:
        view_class = _view_class_for_name(url_name)
        found[view_class.__name__] = view_class
    return found


ADMIN_VIEWS = discover_admin_views()


def test_every_routed_admin_view_is_declared():
    """The test that makes this file a guarantee instead of a snapshot.

    A nineteenth admin endpoint added without a line in ADMIN_SURFACE fails HERE, before
    any of the parametrised checks below get a chance to silently not run on it. The
    assertion is symmetric on purpose: an ADMIN_SURFACE entry with no route left behind
    by a deleted endpoint is also a failure, because a stale declaration makes the dict
    a worse answer to "what is the admin surface?" every time it is read.
    """
    routed = set(ADMIN_VIEWS)
    declared = set(ADMIN_SURFACE)
    assert routed == declared, (
        f"admin routes with no ADMIN_SURFACE entry: {sorted(routed - declared)}; "
        f"ADMIN_SURFACE entries with no route: {sorted(declared - routed)}"
    )


@pytest.mark.parametrize("view_name", sorted(ADMIN_VIEWS))
def test_admin_view_authenticates_with_the_admin_class_only(view_name):
    view_class = ADMIN_VIEWS[view_name]
    assert view_class.authentication_classes == [AdminJWTAuthentication], (
        f"{view_name} must authenticate with AdminJWTAuthentication and nothing else — "
        f"got {[c.__name__ for c in view_class.authentication_classes]}"
    )


@pytest.mark.parametrize("view_name", sorted(ADMIN_VIEWS))
def test_admin_view_requires_staff_or_a_scope(view_name):
    view_class = ADMIN_VIEWS[view_name]
    required_scope = ADMIN_SURFACE[view_name]
    permissions = view_class.permission_classes
    assert permissions, f"{view_name} has no permission_classes at all"

    if required_scope is None:
        assert IsAdminUser in permissions, f"{view_name} must require is_staff"
    else:
        scopes = {getattr(p, "scope", None) for p in permissions}
        assert required_scope in scopes, (
            f"{view_name} must require the {required_scope!r} scope; got {scopes}"
        )


@pytest.mark.parametrize("view_name", sorted(ADMIN_VIEWS))
def test_no_admin_view_falls_back_to_the_customer_stack(view_name):
    """The complementary sweep Task 1 could not write, because every one of the
    eighteen retrofit sites was still bare `IsAdminUser` at the time.

    It overlaps the two tests above and that is the point: those ask "does it declare
    the right thing?", this asks "does it still declare the WRONG thing?". The failure
    modes differ. A view could satisfy the scope check while also listing IsAdminUser as
    a second permission — harmless in itself, but it is the fingerprint of a half-done
    retrofit, and the next person to read the view would reasonably conclude is_staff is
    the control. Stock `JWTAuthentication` appearing anywhere in the list is not a
    fingerprint but the live bypass, since DRF takes the first authenticator that
    returns a user.

    `AdminMeView` is exempt from the IsAdminUser half by design (see ADMIN_SURFACE).
    """
    view_class = ADMIN_VIEWS[view_name]
    assert JWTAuthentication not in view_class.authentication_classes, (
        f"{view_name} lists stock JWTAuthentication — a customer token authenticates "
        f"against it and the admin audience claim is never consulted"
    )
    if ADMIN_SURFACE[view_name] is not None:
        assert IsAdminUser not in view_class.permission_classes, (
            f"{view_name} still uses bare IsAdminUser; it must gate on "
            f"HasAdminScope({ADMIN_SURFACE[view_name]!r}) instead"
        )


def test_the_admin_prefix_has_no_route_of_its_own():
    """`/api/v1/admin/` itself must not be routed.

    DRF's `DefaultRouter` adds an `APIRootView` at the router's mount point, and it
    inherits the project defaults — `AllowAny` plus stock `JWTAuthentication`. Mounted
    under this prefix that is an unauthenticated endpoint that enumerates the admin API
    for anyone who asks. It is not a data leak, but it is a route on the admin surface
    that no admin control touches, and the honest fix is to not have it: the admin
    URLconfs use `SimpleRouter`, which generates the same viewset routes without a root
    view or the `.json` format-suffix duplicates. Nothing consumes either.

    This is a separate test from the sweep above because the sweep can only inspect
    routes that exist; the property wanted here is that this one does not.
    """
    roots = [
        (pattern, name)
        for pattern, name, _cb in _walk(get_resolver())
        if pattern.startswith(ADMIN_URL_PREFIX) and name == "api-root"
    ]
    assert not roots, f"an ungated router root is mounted on the admin prefix: {roots}"


def test_the_admin_token_endpoint_is_not_itself_behind_the_admin_class():
    """Sanity check on the guard's own boundary: admin-token/ MINTS the claim, so it
    cannot require it — a login that demanded an admin token to obtain an admin token
    would be unreachable. It is listed nowhere in ADMIN_SURFACE for that reason, and
    this test exists so that omission reads as deliberate rather than forgotten."""
    view_class = _view_class_for_name("admin_token_obtain_pair")
    assert "admin_token_obtain_pair" not in ADMIN_VIEWS_OUTSIDE_THE_PREFIX
    assert AdminJWTAuthentication not in view_class.authentication_classes
