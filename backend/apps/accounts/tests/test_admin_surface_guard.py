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

TWO EXPLICIT ALLOWLISTS, added in Task 3, both deliberately short and both commented
per entry:

* `PUBLIC_ADMIN_ROUTES` — admin-prefix routes that are public ON PURPOSE. Task 2's
  headline find was an ACCIDENTALLY public admin route; accept-invite is a deliberately
  public one, and without somewhere to say so the only ways to ship it would be to
  weaken the guard for every route or to mount it where the walker cannot see it. An
  entry is not a waiver: allowlisted routes are held to a stricter rule than guarded
  ones (see `test_public_admin_routes_declare_their_own_openness`).
* `PREAUTH_ACCEPTING_VIEWS` — views allowed to accept the TOTP-bootstrap claim. Exactly
  three, asserted against the URLconf in both directions.

TASK 3b ADDED THE TEST THIS FILE WAS ALWAYS MISSING. Everything above checks that the
right classes are attached to the right routes, which is a statement about *reachability*
— it says nothing about where an admin-audience token can come from. Amendment 6's
invariant is about ORIGIN: the claim means the full ceremony and is minted nowhere else.
`test_only_totp_confirm_can_mint_an_admin_token` walks the AST of every production
module and asserts exactly one call site for the single mint function. That is the
invariant in executable form, and it fails on the day a second mint is written rather
than on the day one is routed.

WHAT THIS FILE DOES NOT CHECK is behaviour: that the declared scope actually keeps
the wrong role out over real HTTP, with the right status code, is
`test_admin_role_matrix.py`. This file checks the wiring; that one checks the wire.
"""
import ast
import pathlib

import pytest
from django.urls import get_resolver, reverse
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.authentication import AdminJWTAuthentication, AdminPreauthJWTAuthentication

# Every admin route in the project is mounted under this prefix by config/urls.py.
ADMIN_URL_PREFIX = "api/v1/admin/"

# Routes on the admin prefix that are PUBLIC ON PURPOSE, by view class name, each with
# the reason. This list is the whole point of the addition: Task 2's headline find was
# an ACCIDENTALLY public admin route (DefaultRouter's `APIRootView`, inheriting AllowAny
# plus the stock authentication class, answering anonymous GETs with a directory of the
# admin API). Without somewhere to write "this one is deliberate", the only two options
# for a genuinely public admin endpoint are to weaken the guard for everybody or to
# hide the route somewhere the walker cannot see it. Both end with the next accidental
# one going unnoticed.
#
# An entry here is not a waiver. `test_public_admin_routes_declare_their_own_openness`
# holds them to a STRICTER standard than the guarded routes: they must declare
# `permission_classes` and `authentication_classes` on the class itself, and the
# authentication list must be EMPTY. A route that accepts no credential cannot act on
# behalf of one, and — the property that matters here — it cannot be public by
# inheriting a default nobody looked at, which is exactly how `APIRootView` got in.
PUBLIC_ADMIN_ROUTES: dict[str, str] = {
    "StaffInviteAcceptView": (
        "Accept a staff invite. The caller has no account yet (or a customer account "
        "whose credentials are irrelevant), so the proof it accepts is the invite "
        "token, which proves control of the invited inbox. Turnstile-gated; the "
        "throttle is applied inside the view, only to invalid tokens."
    ),
}

# Views permitted to accept `AdminPreauthJWTAuthentication` — the bootstrap claim minted
# by accept-invite and by the staff password step. EXACTLY THREE, and the number is the
# point: a preauth token is a caller who has proved a password and a human check and
# owes a TOTP code, so the only things it may reach are the ones that finish the
# ceremony. Enumerated rather than discovered so that widening it is a deliberate,
# reviewed edit and not a side effect of adding a view — and asserted against the live
# URLconf in BOTH directions below, so it can be neither quietly widened nor quietly
# emptied.
PREAUTH_ACCEPTING_VIEWS: tuple[str, ...] = (
    "AdminTOTPEnrolView",  # hand out a secret (refused once one is confirmed)
    "AdminTOTPConfirmView",  # verify a code — the ONLY mint of an admin token
    "AdminTOTPRecoveryView",  # burn a recovery code; voids the factor, mints nothing
)

# The routes those three are expected to occupy. A second copy of the same fact as the
# names above, on purpose: the names answer "which classes", these answer "at which
# URLs", and a view re-mounted somewhere else would satisfy the first and not the second.
PREAUTH_ACCEPTING_PATHS: frozenset[str] = frozenset(
    {
        "api/v1/auth/admin-totp/enrol/",
        "api/v1/auth/admin-totp/confirm/",
        "api/v1/auth/admin-totp/recovery/",
    }
)

# The one function allowed to create a `toke-admin` token, and the one place allowed to
# call it. `test_only_totp_confirm_can_mint_an_admin_token` walks the AST of every module
# under `apps/` and `config/` to enforce it. See that test for why this is the executable
# form of Amendment 6.
ADMIN_MINT_FUNCTION = "mint_admin_token_pair"
ADMIN_MINT_CALLER = ("apps/accounts/views.py", "AdminTOTPConfirmView")

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
    # Editing an uploaded image — alt text, order, deletion. Same scope as uploading it,
    # because deleting a product photograph and adding one are the same authority.
    "ProductImageAdminViewSet": "products.manage",
    "ProductVideoAdminViewSet": "products.manage",
    "PriceAdminViewSet": "products.manage",
    "ProductCSVExportView": "products.manage",
    "ProductCSVImportView": "products.manage",
    # --- cms: the first endpoint to declare `cms.manage`, which Plan-16 seeded and
    # nothing used until Plan-19a. A Content editor's entire surface.
    "PageAdminViewSet": "cms.manage",
    # --- inventory ---------------------------------------------------------------
    # Warehouses are where stock physically is, and `serves_countries` on one of them
    # decides whether a market can be sold to at all. Same scope as the stock it holds.
    "WarehouseAdminViewSet": "products.manage",
    "StockItemAdminViewSet": "products.manage",
    "StockMovementListView": "products.manage",
    "StockCSVExportView": "products.manage",
    "StockCSVImportView": "products.manage",
    # --- orders: read ------------------------------------------------------------
    "AdminOrderListView": "orders.view",
    # An invoice carries the customer's name and home address, so this is read-audited.
    # It exists because the customer-surface route staff could already use sits where
    # neither this guard nor the audit mixin reaches (Plan-18a Task 2).
    "AdminOrderInvoiceView": "orders.view",
    # A scope ABOVE the list: one file with every customer's email is bulk egress,
    # which is a different act from working the order desk.
    "AdminOrderCSVExportView": "orders.manage",
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
    # Inviting staff mints administrators, so `staff.manage` is Owner-only. Revocation
    # carries the same scope because an invite is a live staff-creation capability
    # either way: being able to cancel one is as consequential as being able to send it.
    "StaffInviteListCreateView": "staff.manage",
    "StaffInviteRevokeView": "staff.manage",
    # The roster: who holds an administrator account today, and which of them has not
    # confirmed a second factor. Same scope as inviting, because it is the same subject
    # — and because the list of administrators together with their enrolment gaps is a
    # target list, not a staff directory. Nobody but the Owner needs it.
    "StaffListView": "staff.manage",
    # --- search ------------------------------------------------------------------
    # `None`, and this is the one entry in the dict where that needs an argument rather
    # than a sentence. Every OTHER `None` here means "gates on is_staff and that is the
    # whole control" (admin-me). This one means the view carries NO single scope because
    # it gates PER SECTION: orders behind `orders.view`, customers behind `customers.view`,
    # products behind `products.manage` — each derived at request time from that section's
    # own list endpoint, so the two can never drift apart. A single declared scope here
    # would be a lie in whichever direction it was written: `orders.view` would hand the
    # customer section to anyone holding it, and the strictest of the three would hide the
    # box from Support entirely.
    #
    # That makes this the one admin view whose authorization this file CANNOT check, and
    # the check therefore lives where it can be made behaviourally:
    # `apps/core/tests/test_admin_search.py::test_the_scope_matrix` drives a real request
    # per seeded role and asserts the exact set of sections returned. Read that before
    # changing anything here.
    "AdminSearchView": None,
    # --- audit -------------------------------------------------------------------
    # `settings.manage` rather than a scope of its own: an `audit.view` scope would be
    # held by exactly the roles that already hold this one, and the log records what
    # every other role did — so the reader should be the person who decides who those
    # roles are. See apps/core/admin_views.py.
    "AuditLogListView": "settings.manage",
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
        if view_class.__name__ in PUBLIC_ADMIN_ROUTES:
            continue  # deliberately public — held to the rules below instead
        existing = found.setdefault(view_class.__name__, view_class)
        # Two different classes sharing a name would let one hide behind the other's
        # entry in ADMIN_SURFACE. Cheap to rule out, silent and nasty if it happened.
        assert existing is view_class, f"two admin view classes are named {view_class.__name__}"
    for url_name in ADMIN_VIEWS_OUTSIDE_THE_PREFIX:
        view_class = _view_class_for_name(url_name)
        found[view_class.__name__] = view_class
    return found


def discover_public_admin_views() -> dict[str, type]:
    """The admin-prefix routes named in `PUBLIC_ADMIN_ROUTES`, as they are actually
    routed. Separate from `discover_admin_views` so a name in the allowlist that no
    longer corresponds to a route fails loudly instead of quietly exempting nothing."""
    found: dict[str, type] = {}
    for pattern, _name, callback in _walk(get_resolver()):
        if not pattern.startswith(ADMIN_URL_PREFIX):
            continue
        view_class = _view_class(callback)
        if view_class is not None and view_class.__name__ in PUBLIC_ADMIN_ROUTES:
            found[view_class.__name__] = view_class
    return found


ADMIN_VIEWS = discover_admin_views()
PUBLIC_ADMIN_VIEWS = discover_public_admin_views()


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


# HTTP methods that cannot change state. `options` and `head` are DRF/Django's own
# and are always present; `get` is the read.
SAFE_METHODS = frozenset({"get", "head", "options"})


def _routed_methods(callback) -> set[str]:
    """The HTTP methods this particular ROUTE exposes, lowercase.

    Per route, not per class, because a DRF viewset is one class behind several routes
    with different method maps: the list route is `{get: list, post: create}` and the
    detail route is `{get: retrieve, patch: partial_update, delete: destroy}`. Asking
    the class alone would answer "all of them" for both.
    """
    actions = getattr(callback, "actions", None)
    if actions:  # router-generated viewset route
        return {method.lower() for method in actions}
    view_class = _view_class(callback)
    return {m for m in view_class.http_method_names if hasattr(view_class, m)}


def test_nothing_named_view_is_routed_onto_a_writing_method():
    """AMENDMENT 7's HEADLINE RULE, finally asserted against the routes.

    `test_rbac.py` claimed to enforce this and did not: it only checked that scope
    STRINGS end in `.view`/`.operate`/`.manage`, so declaring
    `HasAdminScope("orders.view")` on a POST endpoint passed happily. The rule is
    about what a scope lets you DO, and that is a property of the URLconf, not of the
    string — which is why the check has to live here.

    Why it matters concretely: `orders.view` is the scope you hand a temp, a
    contractor, or an analyst because the name promises reading. The three-way order
    split exists precisely so that Support's ability to move an order lives on
    `orders.operate` instead. A write reachable with `.view` quietly hands that
    ability to everyone the name was chosen to reassure.
    """
    offenders = []
    for pattern, _name, callback in _walk(get_resolver()):
        if not pattern.startswith(ADMIN_URL_PREFIX):
            continue
        scope = ADMIN_SURFACE.get(_view_class(callback).__name__)
        if scope is None or not scope.endswith(".view"):
            continue
        writes = _routed_methods(callback) - SAFE_METHODS
        if writes:
            offenders.append(f"{pattern} ({scope}) exposes {sorted(writes)}")
    assert not offenders, (
        "a scope named `.view` is routed onto a method that writes: " + "; ".join(offenders)
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


def test_every_public_admin_route_in_the_allowlist_still_exists():
    """Symmetric, for the same reason `test_every_routed_admin_view_is_declared` is: a
    stale exemption is worse than no exemption, because the next person reading
    PUBLIC_ADMIN_ROUTES treats it as a description of the surface. A name here that is
    no longer routed also means the guard is silently exempting nothing while looking
    like it exempts something."""
    assert set(PUBLIC_ADMIN_VIEWS) == set(PUBLIC_ADMIN_ROUTES), (
        f"allowlisted but not routed: {sorted(set(PUBLIC_ADMIN_ROUTES) - set(PUBLIC_ADMIN_VIEWS))}"
    )


def test_no_view_is_both_guarded_and_exempt():
    """The two sets must not overlap, or a view could satisfy the exemption while its
    ADMIN_SURFACE entry made it look guarded."""
    assert not (set(PUBLIC_ADMIN_VIEWS) & set(ADMIN_VIEWS))


@pytest.mark.parametrize("view_name", sorted(PUBLIC_ADMIN_ROUTES))
def test_public_admin_routes_declare_their_own_openness(view_name):
    """A deliberately public admin route must SAY SO ON THE CLASS.

    This is the check that would have caught `APIRootView`. That view was public not
    because anybody decided it should be, but because it declared nothing and inherited
    the project defaults — `AllowAny` (DRF's own default; the project sets no
    `DEFAULT_PERMISSION_CLASSES`) plus stock `JWTAuthentication`. Asserting
    `permission_classes == [AllowAny]` alone would not have caught it, because the
    inherited value IS `[AllowAny]`. So the assertion is on `vars(view_class)`: the
    attribute must be defined on the class itself.

    `authentication_classes` must additionally be EMPTY. A public endpoint that still
    runs an authenticator can act on behalf of whatever credential it happens to be
    handed, and a malformed token there turns a public route into a 401 for no reason.
    Nothing on this list needs to know who is calling — that is what makes it public.
    """
    view_class = PUBLIC_ADMIN_VIEWS[view_name]
    assert "permission_classes" in vars(view_class), (
        f"{view_name} is public by INHERITANCE, not by decision — declare "
        f"permission_classes = [AllowAny] on the class"
    )
    assert "authentication_classes" in vars(view_class), (
        f"{view_name} inherits its authentication classes; declare them on the class"
    )
    assert view_class.permission_classes == [AllowAny], view_class.permission_classes
    assert view_class.authentication_classes == [], (
        f"{view_name} is public but still accepts a credential: "
        f"{[c.__name__ for c in view_class.authentication_classes]}"
    )


def preauth_accepting_paths() -> set[str]:
    """Every routed path whose view accepts the preauth claim. Importable because
    `test_staff_totp.py` asserts the same set from the behavioural side."""
    return {
        pattern
        for pattern, _name, callback in _walk(get_resolver())
        if AdminPreauthJWTAuthentication
        in getattr(_view_class(callback), "authentication_classes", [])
    }


def test_only_enumerated_views_accept_the_preauth_claim():
    """The bootstrap claim (`toke-admin-preauth`) is minted at two moments — accepting a
    staff invite, and passing the staff password step — and both mean the same thing: a
    password and a human check have been proved, and a TOTP code is owed. Amendment 6's
    invariant is that the ADMIN audience claim means the FULL ceremony and is minted
    nowhere else, so bootstrap gets its own claim and that claim must reach only the
    endpoints that finish the ceremony.

    This walks the WHOLE URLconf rather than the admin prefix, because a
    preauth-accepting endpoint mounted anywhere else would be exactly as dangerous and
    exactly as easy to add by accident.
    """
    offenders = []
    for pattern, _name, callback in _walk(get_resolver()):
        view_class = _view_class(callback)
        if view_class is None:
            continue
        if AdminPreauthJWTAuthentication in getattr(view_class, "authentication_classes", []):
            if view_class.__name__ not in PREAUTH_ACCEPTING_VIEWS:
                offenders.append(f"{pattern} -> {view_class.__name__}")
    assert not offenders, (
        "these views accept the TOTP-bootstrap claim without being enumerated in "
        f"PREAUTH_ACCEPTING_VIEWS: {sorted(set(offenders))}"
    )


def test_the_preauth_claim_reaches_exactly_three_routes():
    """The other direction, and the half that a one-sided allowlist always misses.

    The test above catches WIDENING — a fourth endpoint that started accepting the
    claim. This one catches NARROWING and RE-MOUNTING: a TOTP endpoint whose
    `authentication_classes` were changed to something else would leave the ceremony
    reachable by the wrong credential and pass the test above silently, because a view
    that no longer accepts the claim is simply not an offender.

    Asserted as PATHS rather than class names because that is the property that matters
    operationally: these three URLs, and no others, may be opened by a caller who has
    proved a password but not a second factor.
    """
    assert preauth_accepting_paths() == set(PREAUTH_ACCEPTING_PATHS)


@pytest.mark.parametrize("view_name", sorted(PREAUTH_ACCEPTING_VIEWS))
def test_a_preauth_view_accepts_the_preauth_class_and_nothing_else(view_name):
    """Equality, for the same reason the admin views are held to equality: listing a
    second authenticator alongside means a request can be authenticated by whichever
    runs first, and a list is exactly the kind of line a reviewer's eye slides over.
    Stock `JWTAuthentication` here would be the sharpest version — it would let any
    logged-in CUSTOMER enrol a TOTP secret against their own account and then walk
    through the confirm endpoint, which mints admin tokens."""
    routed = {
        _view_class(callback).__name__: _view_class(callback)
        for _pattern, _name, callback in _walk(get_resolver())
        if _view_class(callback) is not None
    }
    view_class = routed.get(view_name)
    assert view_class is not None, f"{view_name} is in PREAUTH_ACCEPTING_VIEWS but not routed"
    assert view_class.authentication_classes == [AdminPreauthJWTAuthentication], (
        f"{view_name} must authenticate with AdminPreauthJWTAuthentication and nothing "
        f"else — got {[c.__name__ for c in view_class.authentication_classes]}"
    )


def _python_sources():
    """Every production Python module in the backend, excluding tests and migrations.

    Tests are excluded because they legitimately mint tokens to construct fixtures;
    migrations because they cannot call a view. The exclusion is by path so that a new
    app is covered automatically — the opposite of an allowlist, which is what a check
    on "where can an admin token come from" has to be.
    """
    root = pathlib.Path(__file__).resolve().parents[3]  # backend/
    for path in sorted((root / "apps").rglob("*.py")) + sorted((root / "config").rglob("*.py")):
        parts = set(path.parts)
        if "tests" in parts or "migrations" in parts or path.name.startswith("test_"):
            continue
        yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")


def _enclosing_class(tree, node) -> str | None:
    """The name of the class a node sits inside, if any. Walks down from the module
    rather than up, because `ast` nodes carry no parent pointer."""
    for candidate in ast.walk(tree):
        if isinstance(candidate, ast.ClassDef):
            for descendant in ast.walk(candidate):
                if descendant is node:
                    return candidate.name
    return None


def test_only_totp_confirm_can_mint_an_admin_token():
    """**AMENDMENT 6, EXECUTABLE.** The invariant is that the `toke-admin` audience claim
    means the full ceremony completed — password, Turnstile, TOTP — and is minted
    nowhere else. Until Task 3b that was an intention: `/auth/admin-token/` minted a
    full session for a password alone, so the claim actually meant "password", and the
    preauth token accept-invite returned was a fence around a door that was still open.

    The invariant is now a property of the CALL GRAPH, and this is what checks it: there
    is exactly one function that writes the claim (`mint_admin_token_pair`), and the AST
    of every production module is searched for calls to it. Exactly one may exist, in
    `AdminTOTPConfirmView`.

    WHY STATIC RATHER THAN DRIVING EVERY ROUTE. A behavioural sweep can only exercise
    the request shapes a test happens to construct — it proves things about the routes
    it reached, not about the URLconf. This proves something about all code: a new view
    that mints an admin token fails here on the day it is written, before it is ever
    routed, and so does an "exception" added to an existing one. `test_staff_totp.py`
    carries the behavioural half (a preauth token opens exactly three endpoints; the
    password step returns no session; a superuser gets no shortcut), and the two
    together are the guarantee. Neither alone is.
    """
    call_sites = []
    for relative_path, source in _python_sources():
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name == ADMIN_MINT_FUNCTION:
                call_sites.append((relative_path, _enclosing_class(tree, node), node.lineno))

    assert len(call_sites) == 1, (
        f"{ADMIN_MINT_FUNCTION} must be called from exactly one place — TOTP confirm. "
        f"Found: {call_sites}"
    )
    path, enclosing_class, _lineno = call_sites[0]
    assert (path, enclosing_class) == ADMIN_MINT_CALLER, (
        f"the admin token mint moved to {path}:{enclosing_class}; the only place "
        f"allowed to mint one is {ADMIN_MINT_CALLER}"
    )


def test_nothing_else_writes_the_admin_audience_claim():
    """The complement, and the reason the test above is not enough on its own: a new
    call site is caught there, but assigning `ADMIN_AUDIENCE` onto a token directly
    would bypass the named function entirely.

    Only `authentication.py` may name the constant in an assignment or a comparison —
    it defines it, mints with it, and compares it in `AdminJWTAuthentication`. Anywhere
    else is either a second mint or a second enforcement point, and both are how a
    single invariant becomes two things that disagree.
    """
    offenders = []
    for relative_path, source in _python_sources():
        if relative_path.endswith("apps/accounts/authentication.py"):
            continue
        if "ADMIN_AUDIENCE" in source:
            # `ADMIN_AUDIENCE_CLAIM` is the claim NAME and is harmless to read; the
            # value is what mints. Distinguish them by token, not by substring.
            for line in source.splitlines():
                if "ADMIN_AUDIENCE" in line and "ADMIN_AUDIENCE_CLAIM" not in line:
                    offenders.append(f"{relative_path}: {line.strip()}")
    assert not offenders, (
        "the admin audience VALUE is referenced outside authentication.py, which is "
        f"where the mint and the check both live: {offenders}"
    )


def test_no_view_anywhere_uses_session_authentication():
    """The companion trapdoor, guarded rather than re-investigated.

    `django.contrib.admin` IS mounted at `/django-admin/` (`config/urls.py`), and the
    live Apache vhost denies it outright — `<Location /django-admin/> Require all
    denied`, verified externally as 403 from the public internet. That is configuration
    and cannot be asserted from here. What CAN be asserted is the thing that would make
    a Django admin session dangerous even so: if any DRF view accepted
    `SessionAuthentication`, a Django login cookie would authenticate API calls, and the
    admin audience claim — which a session cannot carry — would be bypassed entirely for
    every view that had it.

    `DEFAULT_AUTHENTICATION_CLASSES` contains only `JWTAuthentication` today. This test
    is what keeps that true, and it sweeps the URLconf as well as the setting because a
    single view opting in would be enough.
    """
    from django.conf import settings
    from rest_framework.authentication import SessionAuthentication

    configured = settings.REST_FRAMEWORK.get("DEFAULT_AUTHENTICATION_CLASSES", [])
    assert not any("SessionAuthentication" in str(entry) for entry in configured), configured

    offenders = [
        f"{pattern} -> {_view_class(callback).__name__}"
        for pattern, _name, callback in _walk(get_resolver())
        if SessionAuthentication in getattr(_view_class(callback), "authentication_classes", [])
    ]
    assert not offenders, (
        "these views accept a Django session cookie, which cannot carry the admin "
        f"audience claim and therefore bypasses it: {sorted(set(offenders))}"
    )


def test_no_admin_view_accepts_the_preauth_claim_as_well_as_the_admin_one():
    """The two audiences are mutually exclusive by construction — one claim, compared
    for equality by each class — but listing both classes on one view would union them
    and let a half-authenticated caller through. Cheap to rule out."""
    for view_name, view_class in ADMIN_VIEWS.items():
        assert AdminPreauthJWTAuthentication not in view_class.authentication_classes, (
            f"{view_name} accepts a bootstrap token that has not completed TOTP"
        )


def test_the_admin_token_endpoint_is_not_itself_behind_the_admin_class():
    """Sanity check on the guard's own boundary: admin-token/ MINTS the claim, so it
    cannot require it — a login that demanded an admin token to obtain an admin token
    would be unreachable. It is listed nowhere in ADMIN_SURFACE for that reason, and
    this test exists so that omission reads as deliberate rather than forgotten."""
    view_class = _view_class_for_name("admin_token_obtain_pair")
    assert "admin_token_obtain_pair" not in ADMIN_VIEWS_OUTSIDE_THE_PREFIX
    assert AdminJWTAuthentication not in view_class.authentication_classes
