"""Plan-25 task 3: per-object authorisation on the CUSTOMER-facing surface.

`test_admin_surface_guard` already asks "does this admin endpoint declare a scope". That
is a question about ROLES. This file asks the other one — *can one customer reach another
customer's object* — which no scope check answers, because both callers are legitimately
authenticated customers.

── WHAT THE PASS FOUND ──────────────────────────────────────────────────────────────────

Nothing. Every object-addressed endpoint outside `/api/v1/admin/` is either scoped to the
requesting user or public by design, verified endpoint by endpoint on 2026-08-02. That is
a good result and it is also the reason this file exists: a pass whose output is "we
looked and it was fine" protects nothing the next time somebody adds a route.

So the deliverable is the GUARD below. Every URL pattern outside the admin prefix that
carries a path parameter must be declared here, saying how it is scoped. A new
`/api/v1/me/invoices/<pk>/` fails this test until somebody writes down which of the two
it is — which is exactly the moment to notice it takes a bare pk.
"""

import re

import pytest
from django.urls import get_resolver

# ── the declaration ──────────────────────────────────────────────────────────────────────

#: Every object-addressed public route, and how it is protected.
#:
#: OWNED  — the lookup is filtered by the requesting user. Another customer's identifier
#:          must resolve to 404, never to their data.
#: PUBLIC — the object is public information and the identifier addresses no one person.
OWNED, PUBLIC = "owned", "public"

OBJECT_ROUTES: dict[str, tuple[str, str]] = {
    # --- personal: an integer pk is trivially enumerable, so these matter most ---
    "api/v1/me/addresses/<int:pk>/": (
        OWNED, "get_queryset() is request.user.addresses"),
    "api/v1/me/addresses/<int:pk>/set-default-shipping/": (
        OWNED, "get_object_or_404(request.user.addresses, pk=pk)"),
    "api/v1/me/addresses/<int:pk>/set-default-billing/": (
        OWNED, "get_object_or_404(request.user.addresses, pk=pk)"),
    "api/v1/me/wishlist/<str:sku>/": (
        OWNED, "get_object_or_404(request.user.wishlist_items, variant__sku=sku)"),
    "api/v1/cart/items/<int:variant_id>/": (
        OWNED, "the cart is resolved from the user or an unguessable X-Cart-Id UUID"),
    "api/v1/cart/combos/<int:group_id>/": (
        OWNED, "get_object_or_404(CartComboGroup, pk=..., cart=<the caller's own cart>)"),
    # --- personal: addressed by an order number a customer knows and may share ---
    "api/v1/orders/<str:number>/": (OWNED, "queryset filtered to request.user"),
    "api/v1/orders/<str:number>/invoice.pdf": (
        OWNED, "same queryset; the PDF carries name, address and totals"),
    "api/v1/orders/<str:number>/pay/": (
        OWNED, "retry_payment filters Order.objects.filter(number=..., user=user)"),
    "api/v1/payments/<str:reference>/verify/": (
        OWNED, "get_object_or_404(Payment, gateway_reference=..., order__user=request.user)"),
    # --- public by design ---
    "api/v1/products/<slug:slug>/": (PUBLIC, "the catalogue is public"),
    "api/v1/products/<slug:slug>/reviews/": (PUBLIC, "published reviews are public"),
    "api/v1/products/<slug:slug>/reviews/eligibility/": (
        OWNED, "answers only from request.user's own orders and review; the slug names a public product"),
    "api/v1/collections/<slug:slug>/": (
        PUBLIC, "a merchandising grouping; the slug names no person"),
    "api/v1/combos/<slug:slug>/": (
        PUBLIC, "a merchandising grouping over public catalogue rows; the slug names no person"),
    "api/v1/cms/pages/<slug:slug>/": (PUBLIC, "published pages only; a draft 404s"),
    "api/v1/webhooks/<str:gateway>/": (
        PUBLIC, "the gateway NAME, not an object id — authenticated by signature"),
    "api/v1/webhooks/aaj/<str:token>/": (
        PUBLIC, "not an object id at all: the segment IS the credential (AAJ's dashboard "
                "accepts a URL and nothing else), compared in constant time and paired "
                "with signature verification when AAJ sends one — aaj/webhook.py"),
    # --- the delivery-partner portal (Plan-39) ---
    "api/v1/partner/^zones/(?P<pk>[^/.]+)/$": (
        OWNED, "get_queryset() filters to request.user.delivery_partner — one partner "
               "can neither read nor write another's rate card"),
}

_PARAM = re.compile(r"<[^>]+>")


def _object_routes() -> dict[str, str]:
    """Every non-admin URL pattern carrying a path parameter, mapped to its view name."""

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern), p.callback

    found = {}
    for path, callback in walk(get_resolver().url_patterns):
        if not path.startswith("api/v1/") or path.startswith("api/v1/admin/"):
            continue
        if not _PARAM.search(path):
            continue
        view = getattr(callback, "view_class", None) or getattr(callback, "cls", callback)
        found[path] = getattr(view, "__name__", str(view))
    return found


def test_EVERY_OBJECT_ADDRESSED_ROUTE_IS_DECLARED():
    """The guard. A new route taking an id fails here until somebody says how it is scoped.

    This is the same shape as `ADMIN_SURFACE`, and for the same reason: the failure it
    prevents is silent. An endpoint that forgets to filter by user does not error, does not
    log, and returns a perfectly well-formed response — belonging to somebody else.
    """
    routed = set(_object_routes())
    declared = set(OBJECT_ROUTES)

    assert routed == declared, (
        f"undeclared object routes: {sorted(routed - declared)}; "
        f"declared but no longer routed: {sorted(declared - routed)}. "
        "Add an entry to OBJECT_ROUTES saying whether the object is OWNED (the lookup is "
        "filtered by request.user) or PUBLIC, and add a cross-account test below if it is "
        "the former."
    )


def test_no_route_is_declared_owned_without_saying_how():
    # A bare "owned" with no note is a claim nobody can check later.
    for path, (kind, why) in OBJECT_ROUTES.items():
        assert kind in (OWNED, PUBLIC), path
        assert len(why) > 15, f"{path}: say HOW it is scoped, not just that it is"


# ── the cross-account tests ──────────────────────────────────────────────────────────────

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_customers(django_user_model):
    """Mine and theirs. Every test below asks whether one can reach the other's object."""
    mine = django_user_model.objects.create_user(email="mine@example.com", password="x")
    theirs = django_user_model.objects.create_user(email="theirs@example.com", password="x")
    return mine, theirs


@pytest.fixture
def client_for():
    from rest_framework.test import APIClient

    def make(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return make


def _address(user):
    from apps.accounts.models import Address

    return Address.objects.create(
        user=user, label="Home", line1="1 Test Road", country_code="NG", city_text="Lagos"
    )


def test_ANOTHER_CUSTOMERS_ADDRESS_IS_A_404_NOT_A_403(two_customers, client_for):
    """404, deliberately, not 403.

    A 403 confirms the row exists and belongs to somebody — which is itself a disclosure
    when the identifier is a sequential integer, because it turns the endpoint into an
    oracle for "how many addresses does this shop hold".
    """
    mine, theirs = two_customers
    victim = _address(theirs)

    response = client_for(mine).get(f"/api/v1/me/addresses/{victim.pk}/")

    assert response.status_code == 404


@pytest.mark.parametrize("method,payload", [("patch", {"city_text": "Hijacked"}), ("delete", None)])
def test_another_customers_address_cannot_be_edited_or_deleted(
    two_customers, client_for, method, payload
):
    mine, theirs = two_customers
    victim = _address(theirs)

    response = getattr(client_for(mine), method)(
        f"/api/v1/me/addresses/{victim.pk}/", payload, format="json"
    )

    assert response.status_code == 404
    victim.refresh_from_db()
    assert victim.city_text == "Lagos"


@pytest.mark.parametrize("action", ["set-default-shipping", "set-default-billing"])
def test_ANOTHER_CUSTOMERS_ADDRESS_CANNOT_BE_MADE_A_DEFAULT(two_customers, client_for, action):
    """The action routes hanging off the detail URL, which are easy to miss.

    `AddressDetailView` scopes its queryset, but these are separate APIViews that could
    each have been written with a bare `Address.objects.get(pk=pk)` — and flipping a
    stranger's default shipping address is a real effect, not just a read.
    """
    mine, theirs = two_customers
    victim = _address(theirs)

    response = client_for(mine).post(f"/api/v1/me/addresses/{victim.pk}/{action}/")

    assert response.status_code == 404
    victim.refresh_from_db()
    assert victim.is_default_shipping is False
    assert victim.is_default_billing is False


def test_an_unauthenticated_caller_reaches_none_of_it(client, two_customers):
    _, theirs = two_customers
    victim = _address(theirs)

    for url in (
        f"/api/v1/me/addresses/{victim.pk}/",
        "/api/v1/me/wishlist/ANY-SKU/",
    ):
        assert client.get(url).status_code in (401, 403), url


def test_ANOTHER_CUSTOMERS_PAYMENT_CANNOT_BE_VERIFIED(two_customers, client_for, django_user_model):
    """`/payments/<reference>/verify/` takes a GATEWAY reference — a string that appears in
    return URLs, emails and browser history, so it is far more likely to leak than a
    session. It must still be useless to anybody but the payer."""
    from apps.core.models import Country, Currency
    from apps.orders.models import Order
    from apps.payments.models import Payment

    mine, theirs = two_customers
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"name": "Naira", "symbol": "₦"})
    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria", "currency": ngn})
    order = Order.objects.create(
        number="TC-900001", user=theirs, email=theirs.email, country=ng, currency=ngn,
        status="pending_payment", grand_total=100,
    )
    Payment.objects.create(
        order=order, gateway="bank_transfer", amount=100, currency=ngn,
        gateway_reference="REF-VICTIM-1",
    )

    response = client_for(mine).post("/api/v1/payments/REF-VICTIM-1/verify/")

    assert response.status_code == 404


def test_ANOTHER_PARTNERS_ZONE_IS_A_404_NOT_A_403(django_user_model, client_for):
    """Plan-39: one delivery partner must never see — or price — another's rate card.
    404 for the same oracle reason as addresses: zone pks are sequential integers."""
    from apps.delivery.models import DeliveryPartner, PartnerZone

    victim = PartnerZone.objects.first()  # BrandnPack's, seeded by delivery 0017
    rival_user = django_user_model.objects.create_user(email="rival@courier.com", password="x")
    DeliveryPartner.objects.create(name="Rival Riders", code="rival", user=rival_user)

    client = client_for(rival_user)
    assert client.get(f"/api/v1/partner/zones/{victim.pk}/").status_code == 404
    assert client.patch(
        f"/api/v1/partner/zones/{victim.pk}/", {"price": "1"}, format="json"
    ).status_code == 404
