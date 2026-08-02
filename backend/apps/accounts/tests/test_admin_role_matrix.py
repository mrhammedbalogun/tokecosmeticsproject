"""Who can do what, proved over real HTTP. The document of record.

`test_admin_surface_guard.py` checks that each admin view DECLARES the right scope.
This file checks the declaration does what a human reading it would expect: it logs
each seeded role in through the real admin login, fires a real request at every admin
endpoint, and asserts the outcome. When someone asks "can Support issue a refund?",
`MATRIX` below is the answer, and the answer is executable.

HOW A ROW IS READ. Each row names one endpoint and the roles allowed to reach it.
"Reached" deliberately does not mean "succeeded": most of these rows aim at an order
number that does not exist, so an authorised caller gets 404 and an unauthorised one
gets 403. That is the whole assertion, and it is a strong one — 403-vs-404 is exactly
the distinction the permission layer makes, and it needs no fixture data, so the table
stays readable rather than drowning in setup. Rows that need no object (list
endpoints) assert a non-403 that is usually 200.

WHY `allowed` IS SPELLED OUT AND NOT DERIVED from SCOPE_GRANTS. Deriving it would make
this file agree with `rbac.py` by construction and therefore prove nothing: rewrite the
grant table wrongly and the "test" rewrites itself to match. The literal role sets here
are a second, independent statement of intent, and
`test_the_matrix_agrees_with_the_scope_table` makes the two disagree loudly. Changing
who holds a scope should require changing both — that friction is the feature.

STATUS CODES ARE PINNED, never "4xx". 401 and 403 mean different things on this
surface and confusing them hides real bugs:

* **401** — no credentials, or credentials this surface does not accept. A staff
  member's perfectly valid CUSTOMER token lands here, because `AdminJWTAuthentication`
  never authenticates it (Plan-16 Amendment 6). A test accepting "4xx" would pass
  identically if the claim check were deleted and the request merely lacked a scope.
* **403** — authenticated as staff through the admin door, but the role does not hold
  the scope. This is the RBAC layer, and it is the only 403 expected here.
"""
import pytest
from rest_framework.test import APIClient

from apps.accounts.rbac import ROLES, SCOPE_GRANTS
from apps.accounts.authentication import mint_admin_token_pair
from apps.accounts.tests.test_admin_surface_guard import ADMIN_SURFACE

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
NO_SUCH_ORDER = "TC-000000"
ALL_ROLES = frozenset(ROLES)


class Row:
    """One endpoint and the roles that may reach it. A class rather than a tuple so the
    matrix reads as prose at the call site and so pytest ids come out as endpoint names."""

    def __init__(self, view, method, path, allowed, body=None, scope=...):
        self.view = view          # view class name; ties the row to ADMIN_SURFACE
        self.method = method
        self.path = path
        self.allowed = frozenset(allowed)
        self.body = body or {}
        # The scope this row is really testing. Defaults to whatever the view declares;
        # set explicitly only where a row exercises something other than the declared
        # floor (the cancel transition), so the cross-check below stays meaningful.
        self.scope = ADMIN_SURFACE[view] if scope is ... else scope

    def __repr__(self):
        return f"{self.method.upper()} {self.path}"


_ORDER = f"/api/v1/admin/orders/{NO_SUCH_ORDER}"

# Roles, spelled out so each row is legible on its own line.
_OWNER = {"Owner"}
_MANAGERS = {"Owner", "Manager"}
_DESK = {"Owner", "Manager", "Support"}  # everyone who works the order desk
# The Content editor's whole surface. Manager runs the shop and Support works the desk;
# neither writes marketing copy, and `cms.manage` is not theirs (rbac.py:94).
_CONTENT = {"Owner", "Content"}
_OWNER = {"Owner"}  # settings.manage: the payout account and the gateway switches

MATRIX: list[Row] = [
    # --- catalog: writing the catalogue is Owner + Manager -----------------------
    Row("ProductAdminViewSet", "get", "/api/v1/admin/products/", _MANAGERS),
    Row("CategoryAdminViewSet", "get", "/api/v1/admin/categories/", _MANAGERS),
    Row("BrandAdminViewSet", "get", "/api/v1/admin/brands/", _MANAGERS),
    Row("TagAdminViewSet", "get", "/api/v1/admin/tags/", _MANAGERS),
    Row("CollectionAdminViewSet", "get", "/api/v1/admin/collections/", _MANAGERS),
    Row("ProductVariantAdminViewSet", "get", "/api/v1/admin/variants/", _MANAGERS),
    Row("ProductImageAdminViewSet", "get", "/api/v1/admin/images/", _MANAGERS),
    Row("ProductVideoAdminViewSet", "get", "/api/v1/admin/videos/", _MANAGERS),
    Row("PriceAdminViewSet", "get", "/api/v1/admin/prices/", _MANAGERS),
    Row("ProductCSVExportView", "get", "/api/v1/admin/products/export.csv", _MANAGERS),
    Row("ProductCSVImportView", "post", "/api/v1/admin/products/import.csv", _MANAGERS),
    # --- cms: Content holds this and nothing else; Manager and Support do not.
    Row("PageAdminViewSet", "get", "/api/v1/admin/pages/", _CONTENT),
    Row("MenuItemAdminViewSet", "get", "/api/v1/admin/menu-items/", _CONTENT),
    Row("RedirectAdminViewSet", "get", "/api/v1/admin/redirects/", _CONTENT),
    # --- customers: Support holds customers.view, because answering a customer's
    # question is the job. Content does not.
    Row("CustomerAdminViewSet", "get", "/api/v1/admin/customers/",
        {"Owner", "Manager", "Support"}),
    # Campaign material: Manager can run a promotion, a copywriter cannot.
    Row("BannerAdminViewSet", "get", "/api/v1/admin/banners/", _MANAGERS),
    Row("HomepageSectionAdminViewSet", "get", "/api/v1/admin/homepage-sections/", _MANAGERS),
    # --- inventory ---------------------------------------------------------------
    Row("WarehouseAdminViewSet", "get", "/api/v1/admin/warehouses/", _MANAGERS),
    Row("StockItemAdminViewSet", "get", "/api/v1/admin/stock/", _MANAGERS),
    Row("StockMovementListView", "get", "/api/v1/admin/stock/movements/", _MANAGERS),
    Row("StockCSVExportView", "get", "/api/v1/admin/stock/export.csv", _MANAGERS),
    Row("StockCSVImportView", "post", "/api/v1/admin/stock/import.csv", _MANAGERS),
    # --- money config: Owner alone. A Manager runs the shop; only the Owner moves
    # where the money lands.
    Row("BankAccountAdminViewSet", "get", "/api/v1/admin/bank-accounts/", _OWNER),
    Row("CountryPaymentGatewayAdminViewSet", "get", "/api/v1/admin/payment-gateways/", _OWNER),
    Row("CouponAdminViewSet", "get", "/api/v1/admin/coupons/", _MANAGERS),
    Row("DeliveryOptionAdminViewSet", "get", "/api/v1/admin/delivery-options/", _MANAGERS),
    Row("RegionAdminViewSet", "get", "/api/v1/admin/regions/?country_code=NG", _MANAGERS),
    # --- reports: Owner and Manager. Support works the desk and does not see the books.
    Row("ReportView", "get", "/api/v1/admin/reports/revenue/", _MANAGERS),
    Row("ReportExportView", "get", "/api/v1/admin/reports/revenue/export.csv", _MANAGERS),
    # --- orders: the queue and one order. Support lives here all day -------------
    Row("AdminOrderListView", "get", "/api/v1/admin/orders/", _DESK),
    Row("AdminOrderDetailView", "get", f"{_ORDER}/", _DESK),
    # Support packs parcels, and the invoice goes in the box.
    Row("AdminOrderInvoiceView", "get", f"{_ORDER}/invoice.pdf", _DESK),
    # But a dump of every customer is not Support's to take.
    Row("AdminOrderCSVExportView", "get", "/api/v1/admin/orders/export.csv", _MANAGERS),
    # --- orders: operational writes. Support ships, tracks and annotates ---------
    Row("AdminOrderTransitionView", "post", f"{_ORDER}/transition/", _DESK,
        body={"to_status": "shipped"}),
    Row("AdminOrderTrackingView", "patch", f"{_ORDER}/tracking/", _DESK,
        body={"tracking_carrier": "DHL", "tracking_number": "123"}),
    Row("AdminOrderNoteView", "patch", f"{_ORDER}/note/", _DESK,
        body={"admin_note": "rang the customer"}),
    # --- orders: money. Support is deliberately out ------------------------------
    Row("AdminRefundsOwedView", "get", "/api/v1/admin/refunds-owed/", _MANAGERS),
    Row("AdminResolveReviewView", "post", f"{_ORDER}/resolve-review/", _MANAGERS),
    Row("OrderRefundView", "post", f"{_ORDER}/refunds/", _MANAGERS, body={"amount": "1.00"}),
    Row("ManualRefundView", "post", f"{_ORDER}/manual-refund/", _MANAGERS,
        body={"amount": "1.00", "bank_reference": "REF1"}),
    Row("ConfirmManualReceiptView", "post", f"{_ORDER}/confirm-payment/", _MANAGERS,
        body={"amount_received": "1.00", "bank_reference": "REF1"}),
    # --- freight: quoting, waiving, cancelling and banking money -----------------
    Row("QuoteFreightView", "post", f"{_ORDER}/freight/quote/", _MANAGERS,
        body={"amount": "1.00"}),
    Row("WaiveFreightView", "post", f"{_ORDER}/freight/waive/", _MANAGERS,
        body={"note": "goodwill"}),
    Row("CancelQuoteView", "post", f"{_ORDER}/freight/cancel/", _MANAGERS,
        body={"note": "no answer"}),
    Row("FreightReceiptView", "post", f"{_ORDER}/freight/receipt/", _MANAGERS,
        body={"amount_received": "1.00", "bank_reference": "REF1"}),
    # --- staff: Owner only, because inviting staff MINTS ADMINISTRATORS ----------
    # The most consequential scope in the table: everything else changes data, this
    # changes who can change data. Revoking carries the same scope because an
    # outstanding invite is the same capability either way.
    Row("StaffInviteListCreateView", "get", "/api/v1/admin/staff/invites/", _OWNER),
    Row("StaffInviteRevokeView", "post", "/api/v1/admin/staff/invites/999999/revoke/", _OWNER),
    Row("StaffListView", "get", "/api/v1/admin/staff/", _OWNER),
    # --- audit: Owner only. It records what every other role did, so a role that
    # could read it could also watch for whether anyone had noticed it yet ---------
    Row("AuditLogListView", "get", "/api/v1/admin/audit/", _OWNER),
    # --- search: every staff member may USE the box; what comes back is gated per
    # section, against the scope of that section's own list endpoint. This row only
    # asserts admission — that a Content editor is not refused outright, because being
    # refused and being shown nothing are different answers and the second is the right
    # one. WHICH SECTIONS each role actually gets back is asserted behaviourally in
    # `apps/core/tests/test_admin_search.py::test_the_scope_matrix`, which is where the
    # real authorization check for this endpoint lives.
    Row("AdminSearchView", "get", "/api/v1/admin/search/?q=zzz", ALL_ROLES),
    # --- identity: every staff member, whatever their role -----------------------
    Row("AdminMeView", "get", "/api/v1/auth/admin-me/", ALL_ROLES),
]

# The cancel transition is the one place a single route spans two scopes: the endpoint
# declares orders.operate so Support can ship, and elevates to orders.manage for
# `cancelled`, which frees the stock reservation and strands the customer's money.
# Listed apart from MATRIX because it shares a view with the row above it and the
# completeness check below is one-row-per-view.
CANCEL_ROW = Row("AdminOrderTransitionView", "post", f"{_ORDER}/transition/", _MANAGERS,
                 body={"to_status": "cancelled"}, scope="orders.manage")


@pytest.fixture
def roles(django_user_model):
    """One staff user per seeded role, each in exactly one group.

    Deliberately NOT superusers: `scopes_for_user` short-circuits superusers to every
    scope, so a superuser Owner would prove the group grants work when they might not.

    Only Owner gets a usable password, and only because one test logs in at the customer
    door with it. The rest authenticate by minted token, and PBKDF2 is slow enough that
    hashing four passwords in a fixture this heavily parametrised costs minutes across
    the run for nothing.
    """
    from django.contrib.auth.models import Group

    users = {}
    for role in ROLES:
        user = django_user_model.objects.create_user(
            email=f"{role.lower()}@toke.test",
            password=PW if role == "Owner" else None,
            is_staff=True,
        )
        user.groups.add(Group.objects.get(name=role))
        users[role] = user
    return users


def _admin_client(user) -> APIClient:
    """A client carrying a token minted the way the real ceremony mints one.

    Uses the real mint rather than `force_authenticate` on purpose: forcing
    authentication skips `AdminJWTAuthentication` entirely, so the audience claim would
    never be exercised and this file would silently stop covering half of what it says
    it covers.

    It calls `mint_admin_token_pair` directly rather than driving password -> preauth ->
    enrol -> confirm over HTTP, because this file is a role/scope matrix run against
    every endpoint for every role — several hundred parametrised cases — and making each
    one perform a full TOTP ceremony would add a PBKDF2 hash and four requests apiece for
    no coverage this file is responsible for. `test_staff_totp.py` owns the ceremony;
    this owns what the resulting token may do. Note that this is a TEST call site: the
    guard test's "exactly one caller" rule deliberately excludes test modules, since
    fixtures legitimately need to construct the credential under test.
    """
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(user)['access']}")
    return client


def _fire(client, row):
    return getattr(client, row.method)(row.path, row.body, format="json")


def _ids(rows):
    return [f"{r.view}-{r.method}" for r in rows]


# --- the matrix itself --------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("row", MATRIX + [CANCEL_ROW], ids=_ids(MATRIX + [CANCEL_ROW]))
def test_role_against_endpoint(roles, row, role):
    response = _fire(_admin_client(roles[role]), row)
    if role in row.allowed:
        assert response.status_code != 403, (
            f"{role} should be able to reach {row} but was refused: "
            f"{response.status_code} {getattr(response, 'data', b'')}"
        )
    else:
        assert response.status_code == 403, (
            f"{role} must NOT reach {row}; expected 403, got {response.status_code}"
        )


def test_the_matrix_covers_every_admin_endpoint():
    """A new admin endpoint must appear here too, or nobody ever checks who can use it.

    The surface guard already forces a new endpoint to declare a scope; without this
    check the declaration would still go untested against a real role.
    """
    covered = {row.view for row in MATRIX}
    assert covered == set(ADMIN_SURFACE), (
        f"endpoints with no matrix row: {sorted(set(ADMIN_SURFACE) - covered)}; "
        f"matrix rows for no endpoint: {sorted(covered - set(ADMIN_SURFACE))}"
    )


def test_the_matrix_agrees_with_the_scope_table():
    """The two independent statements of intent must say the same thing.

    `MATRIX` says who a human expects to get in; `SCOPE_GRANTS` says who the code lets
    in. They are written separately so that a mistake in either shows up here rather
    than being absorbed silently.
    """
    for row in MATRIX + [CANCEL_ROW]:
        if row.scope is None:  # admin-me: staff-only, no scope
            assert row.allowed == ALL_ROLES, f"{row} gates on is_staff, so every role passes"
            continue
        assert row.allowed == SCOPE_GRANTS[row.scope], (
            f"{row} is documented as allowing {sorted(row.allowed)}, but "
            f"{row.scope} is granted to {sorted(SCOPE_GRANTS[row.scope])}"
        )


def test_support_cannot_issue_a_refund_but_can_ship(roles):
    """The question this whole file exists to answer, asserted in one place so it does
    not have to be reconstructed from the matrix. Support is the interesting role: it is
    the only one that writes without holding any money scope."""
    support = _admin_client(roles["Support"])
    refund = support.post(f"{_ORDER}/refunds/", {"amount": "1.00"}, format="json")
    ship = support.post(f"{_ORDER}/transition/", {"to_status": "shipped"}, format="json")
    cancel = support.post(f"{_ORDER}/transition/", {"to_status": "cancelled"}, format="json")

    assert refund.status_code == 403
    assert cancel.status_code == 403, "cancelling strands the customer's money"
    assert ship.status_code == 404, "shipping is the Support day job; 404 is the missing order"


# --- status codes: 401 is not 403 ---------------------------------------------


@pytest.mark.parametrize("row", MATRIX, ids=_ids(MATRIX))
def test_no_credentials_is_401_not_403(row):
    """An anonymous caller is UNAUTHENTICATED, not merely unauthorised.

    This is the property that makes `AdminJWTAuthentication` worth having: because it is
    the only authenticator on these views, a view that lost its permission class would
    still answer 401 here rather than running.
    """
    response = _fire(APIClient(), row)
    assert response.status_code == 401, (
        f"{row} answered {response.status_code} to an anonymous caller"
    )


@pytest.mark.parametrize("row", MATRIX, ids=_ids(MATRIX))
def test_a_staff_token_from_the_customer_door_is_401(roles, row):
    """Plan-16 Amendment 6, as a regression test on every endpoint at once.

    The Owner's password is the same at both doors. Before the audience claim existed,
    logging in at `/auth/token/` — 30/min, customer Turnstile widget, no admin alerting —
    produced a token that opened the entire admin. It must now be rejected at
    AUTHENTICATION, so the answer is 401 and not 403: a 403 would mean the token
    authenticated fine and merely lacked a scope, which is the bug coming back wearing a
    different status code.
    """
    owner = roles["Owner"]
    token = APIClient().post(
        "/api/v1/auth/token/", {"email": owner.email, "password": PW}, format="json"
    )
    assert token.status_code == 200, "the customer door must still work for staff"

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
    response = _fire(client, row)
    assert response.status_code == 401, (
        f"{row} accepted a customer-door token from a staff member "
        f"({response.status_code})"
    )


def test_a_demoted_staff_member_loses_access_immediately(roles):
    """The claim is a snapshot; `is_staff` is read fresh on every request.

    Revocation must not wait for the token to expire, which is why `scopes_for_user`
    checks the database rather than trusting the token. 403, not 401: the token is still
    a genuine admin token — it is the person who is no longer staff.
    """
    owner = roles["Owner"]
    client = _admin_client(owner)
    assert client.get("/api/v1/admin/orders/").status_code == 200

    owner.is_staff = False
    owner.save(update_fields=["is_staff"])
    assert client.get("/api/v1/admin/orders/").status_code == 403


def test_group_membership_alone_grants_nothing_without_is_staff(django_user_model):
    """A customer put in the Owner group by accident is still a customer.

    Cheap to assert and the failure would be catastrophic: `user.groups` is ordinary
    Django state that any future feature might touch.
    """
    from django.contrib.auth.models import Group

    customer = django_user_model.objects.create_user(email="shopper@toke.test", password=PW)
    customer.groups.add(Group.objects.get(name="Owner"))
    # No admin token can even be minted for them, so authenticate the only way left.
    client = APIClient()
    client.force_authenticate(customer)
    assert client.get("/api/v1/admin/orders/").status_code == 403
