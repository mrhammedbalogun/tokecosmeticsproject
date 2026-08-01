"""Global admin search: who sees which sections, and what the log remembers about it.

WHY THIS FILE IS MOSTLY ABOUT AUTHORIZATION rather than about matching. The plan's Task 6
text said "staff, any scope", and that sentence is the whole reason this file is long: a
single endpoint returning orders, customers and products to anybody with `is_staff` would
be privilege escalation dressed as a convenience. A Content editor holds `cms.manage` and
can reach no customer or order endpoint anywhere on the surface — but could type an email
into a search box and read back customer names and order numbers. Convenience features are
where boundaries go to die, and the boundary here is the same one Task 2 spent eighteen
endpoints establishing.

So the endpoint gates PER SECTION, on the same scope as that section's own list endpoint,
and this file asserts that BEHAVIOURALLY — a real role, a real token, a real request, and
an assertion about which keys came back. `test_the_scope_matrix` is the named deliverable:
"a Content editor types an email and gets nothing", forever.

THE SECOND HALF is queryset parity. A search that resurfaces records the list endpoint
hides is the same bypass sideways, and the defence is structural: the search sources do
not carry querysets of their own, they call the list VIEW's `get_queryset()`.
`test_orders_search_runs_the_list_views_own_queryset` proves that is live rather than
merely intended, by making the list view return nothing and watching search return nothing.

THE THIRD HALF is the audit, which for this endpoint is the point of the endpoint's
existence being tolerable at all. Search is the highest-yield PII read on the surface: one
box that reaches customers, orders and products at once. The row records the RAW TERM and
the PER-TYPE RESULT COUNTS, and there are tests here for both, for the 90-day tombstone
that bounds how long the term survives, and for the deleted-customer tombstone — including
the case that DOES NOT work, which is pinned rather than papered over
(`test_a_partial_prefix_of_a_deleted_email_is_not_matched`).
"""
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.accounts.rbac import ROLES, SCOPE_GRANTS
from apps.catalog.factories import ProductFactory, ProductVariantFactory
from apps.core.admin_search import (
    MAX_TERM_LENGTH,
    MIN_TERM_LENGTH,
    RESULTS_PER_TYPE,
    SEARCH_AUDIT_ACTION,
    SEARCH_AUDIT_MODEL_LABEL,
    SEARCH_SOURCES,
    source_scope,
)
from apps.core.audit import REDACTED, SEARCH_TERM_RETENTION_DAYS
from apps.core.models import AuditLog, Country
from apps.orders.factories import OrderFactory

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/admin/search/"
CLIENT_IP = "203.0.113.9"

# The term every fixture below is built to match, in all three sections at once. One term
# that hits everything is what makes the matrix assertion meaningful: a role that is
# missing a section is missing it because of its scopes, never because nothing matched.
TERM = "zeta"

# WHO SEES WHAT, spelled out rather than derived from the scope table — the same reasoning
# as `test_admin_role_matrix.MATRIX`. Deriving it would make this file agree with
# `rbac.py` by construction and therefore prove nothing: get the grants wrong and the
# "test" rewrites itself to match. `test_the_matrix_agrees_with_the_scope_table` below is
# what makes the two independent statements disagree loudly.
EXPECTED_SECTIONS: dict[str, set[str]] = {
    # Owner holds every scope by construction (see rbac.py's import-time assertion).
    "Owner": {"orders", "customers", "products"},
    # Manager runs the shop: the order desk, the customer list and the catalogue.
    "Manager": {"orders", "customers", "products"},
    # Support answers the phone. They hold `orders.view` and `customers.view` and NOT
    # `products.manage`, so the catalogue section simply is not there for them — which is
    # right: the catalogue endpoints are all `.manage` (see catalog/admin_views.py) and a
    # search that returned products would be the read half of a scope they were denied.
    "Support": {"orders", "customers"},
    # THE ONE THIS ENDPOINT WAS REDESIGNED FOR. A content editor holds `cms.manage` and
    # nothing else. Under the plan's original "staff, any scope" they would have been able
    # to type a customer's email and read back their name, their toke_id and their order
    # history — data no endpoint anywhere else on the surface would show them.
    "Content": set(),
}


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def roles(django_user_model):
    """One staff user per seeded role, in exactly one group each.

    Deliberately not superusers: `scopes_for_user` short-circuits a superuser to every
    scope, so a superuser "Content" account would pass the matrix while proving nothing
    about the group grants.
    """
    users = {}
    for role in ROLES:
        user = django_user_model.objects.create_user(
            email=f"{role.lower()}@toke.test", is_staff=True
        )
        user.groups.add(Group.objects.get(name=role))
        users[role] = user
    return users


def client_for(user) -> APIClient:
    """A client carrying a token minted the way the real ceremony mints one.

    `mint_admin_token_pair` rather than `force_authenticate`, for the reason
    `test_admin_role_matrix.py` gives: forcing authentication skips
    `AdminJWTAuthentication` entirely, so the audience claim would never be exercised and
    `request.auth` would be None — which would leave `token_jti` untested in every audit
    assertion below.
    """
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(user)['access']}",
        HTTP_CF_CONNECTING_IP=CLIENT_IP,
    )
    return api


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", is_staff=True, is_superuser=True
    )
    return user


@pytest.fixture
def api(owner):
    return client_for(owner)


@pytest.fixture
def matchable(django_user_model):
    """One customer, one order and one product, all matching TERM and nothing else."""
    ng = Country.objects.get(code="NG")
    customer = django_user_model.objects.create_user(email=f"{TERM}@example.test")
    customer.first_name = "Zeta"
    customer.last_name = "Buyer"
    customer.save(update_fields=["first_name", "last_name"])
    order = OrderFactory(
        number="TC-ZETA01",
        country=ng,
        currency=ng.currency,
        grand_total="1500.00",
        status="processing",
        email="someone@example.test",
    )
    product = ProductFactory(name="Zeta Cream", slug="zeta-cream")
    ProductVariantFactory(product=product, sku="ZETA-50")
    return {"customer": customer, "order": order, "product": product}


def search(api, term=TERM, **params):
    return api.get(SEARCH_URL, {"q": term, **params})


# --- 1. the scope matrix, which is the whole task ----------------------------


@pytest.mark.parametrize("role", ROLES)
def test_the_scope_matrix(roles, matchable, role):
    """**THE NAMED DELIVERABLE.** One search that would match all three types, run as each
    seeded role, asserting the response contains EXACTLY the sections that role's scopes
    govern — no more, and no fewer.

    Set equality in both directions on purpose. "No more" is the security property. "No
    fewer" is the one a bug would otherwise hide: a section silently dropped for everybody
    (a typo'd scope name, a source removed) would make the security half pass trivially
    forever, and the endpoint would quietly become useless without a single red test.
    """
    response = search(client_for(roles[role]))

    assert response.status_code == 200, response.data
    assert set(response.data) == EXPECTED_SECTIONS[role], (
        f"{role} should see sections {sorted(EXPECTED_SECTIONS[role])} but the response "
        f"carried {sorted(response.data)}"
    )


def test_a_content_editor_typing_an_email_gets_nothing(roles, matchable):
    """The sentence this endpoint's design was changed to make true, as its own test so it
    survives any future refactor of the matrix above.

    An empty 200 rather than a 403, deliberately: holding `cms.manage` and using the
    search box is not an offence, it is just fruitless. A 403 would also be an oracle of a
    small kind — it would confirm that the sections exist and that this account is not
    allowed near them, which is a fact worth nothing to a colleague and worth something to
    an attacker enumerating what a stolen session can reach.
    """
    response = search(client_for(roles["Content"]), term="zeta@example.test")

    assert response.status_code == 200
    assert response.data == {}


def test_the_matrix_agrees_with_the_scope_table(matchable):
    """The two independent statements must say the same thing.

    `EXPECTED_SECTIONS` says who a human expects to see what. `SCOPE_GRANTS` composed with
    each source's DERIVED scope says who the code lets in. Written separately so that a
    mistake in either one shows up here rather than being absorbed silently.
    """
    for source in SEARCH_SOURCES:
        holders = SCOPE_GRANTS[source_scope(source)]
        for role in ROLES:
            expected = source.key in EXPECTED_SECTIONS[role]
            assert (role in holders) is expected, (
                f"EXPECTED_SECTIONS says {role} {'sees' if expected else 'does not see'} "
                f"{source.key!r}, but {source_scope(source)} is granted to {sorted(holders)}"
            )


def test_a_staff_member_with_no_role_at_all_gets_an_empty_200(django_user_model, matchable):
    """A freshly invited account, before anybody puts it in a group. The same empty answer
    as the Content editor, and for the same reason — this is the normal state of a new
    staff member for as long as it takes the Owner to assign a role, and a 403 there would
    look like a broken deployment rather than an unassigned account."""
    user = django_user_model.objects.create_user(email="nobody@toke.test", is_staff=True)
    response = search(client_for(user))

    assert response.status_code == 200
    assert response.data == {}


def test_a_customer_token_is_not_authenticated_at_all(django_user_model, matchable):
    """401, not 403: the admin audience claim (Amendment 6) is enforced in the
    AUTHENTICATION layer, so a token from the customer door is not a caller with the wrong
    scopes — it is not a caller. Pinned here because a search box is exactly the kind of
    endpoint somebody would later "helpfully" open up to the storefront."""
    from rest_framework_simplejwt.tokens import RefreshToken

    staff = django_user_model.objects.create_user(email="dual@toke.test", is_staff=True)
    customer_token = str(RefreshToken.for_user(staff).access_token)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {customer_token}")

    assert search(api).status_code == 401


# --- 2. queryset parity ------------------------------------------------------


def test_orders_search_runs_the_list_views_own_queryset(api, matchable, monkeypatch):
    """**THE NAMED DELIVERABLE: search excludes what the list endpoint excludes.**

    Asserted by making the list view's queryset empty and watching the search section go
    empty with it. That is a stronger statement than comparing two querysets for equality,
    because it fails if anybody ever replaces the derivation with a hand-written queryset
    that merely happens to match today — which is precisely how the exclusions would drift
    apart six months from now.

    There is nothing for the order list to exclude TODAY (`_ORDER_QS` is unfiltered), and
    that is the honest reason this test is written as a mutation rather than as a fixture
    that hides from the list and asserts it also hides from search: there is no such
    fixture to build yet. What is being pinned is the WIRE, so that the day an exclusion is
    added — a soft-delete flag, a per-market filter — search inherits it for free.
    """
    from apps.orders.models import Order
    from apps.orders.views import AdminOrderListView

    monkeypatch.setattr(AdminOrderListView, "get_queryset", lambda self: Order.objects.none())
    response = search(api)

    assert response.data["orders"] == []
    # The other sections are untouched, which is what shows the emptiness came from the
    # patched queryset and not from the search failing wholesale.
    assert response.data["customers"], "only the orders section should have been affected"


def test_an_anonymised_customer_is_not_searchable(api, django_user_model, matchable):
    """The one real exclusion that exists today, end to end.

    A customer who requested deletion has their PII overwritten 30 days later by
    `anonymize_deleted_accounts`, which leaves the row behind with a
    `deleted-TK-XXXXXX@deleted.invalid` address. Those rows must not come back from a
    search — a deleted account that is still findable by typing "deleted" is a deletion
    promise that was not kept.
    """
    ghost = django_user_model.objects.create_user(email="zeta-ghost@example.test")
    ghost.email = f"deleted-{ghost.toke_id}@deleted.invalid"
    ghost.save(update_fields=["email"])

    by_sentinel = search(api, term="deleted-")
    by_toke_id = search(api, term=ghost.toke_id)

    assert by_sentinel.data["customers"] == []
    assert by_toke_id.data["customers"] == []


def test_a_customer_who_asked_to_be_deleted_is_still_searchable_during_the_grace_window(
    api, django_user_model, matchable
):
    """The deliberate other side of the line, pinned so nobody "tidies" it.

    Deletion is a two-phase soft delete: `is_active` flips immediately and the PII is
    scrubbed 30 days later. During that window the person may still ring up about an order,
    and may still change their mind — so the record is still the store's to answer with.
    Only the ANONYMISED row disappears from search, because only it has nothing left to
    show.
    """
    leaving = django_user_model.objects.create_user(email="zeta-leaving@example.test")
    leaving.is_active = False
    leaving.deletion_requested_at = timezone.now()
    leaving.save(update_fields=["is_active", "deletion_requested_at"])

    emails = [row["email"] for row in search(api).data["customers"]]
    assert "zeta-leaving@example.test" in emails


# --- 3. the derivation -------------------------------------------------------


def test_every_section_scope_comes_from_its_own_list_endpoint():
    """The anti-drift property, asserted rather than asserted-in-a-comment.

    A hand-maintained `{"orders": "orders.view"}` dict inside the search view is exactly
    how the bypass gets reintroduced: somebody tightens the order list endpoint to
    `orders.manage` and search keeps answering on `orders.view` for as long as nobody
    re-reads two files at once. So each source names a list VIEW and the scope is read off
    that view's own `permission_classes` at call time.

    This test re-derives it independently, from the routed URLconf, and compares.
    """
    from apps.accounts.tests.test_admin_surface_guard import ADMIN_SURFACE

    for source in SEARCH_SOURCES:
        if source.list_view_path is None:
            continue
        view_class = source.list_view()
        assert source_scope(source) == ADMIN_SURFACE[view_class.__name__], (
            f"the {source.key!r} section and {view_class.__name__} disagree about which "
            f"scope governs {view_class.__name__}"
        )


def test_the_customers_section_is_the_only_underived_one_and_it_is_pinned():
    """HONEST EXCEPTION, and the guard that keeps it from becoming a hole.

    There is no customer list or detail endpoint anywhere on the admin surface yet —
    `customers.view` sits in the scope table with nothing behind it (Plan-18 builds the
    page). So the customers section has no endpoint to derive its scope FROM, and it
    declares one.

    The direction that can hurt is a future customers endpoint choosing a DIFFERENT scope,
    leaving search as the looser of the two.

    ── THIS TEST USED TO CLAIM MORE THAN IT CHECKED (fixed 2026-08-01) ──────────────

    `admin_search.py` says this "also fails the day a customers list view IS routed, which
    is the day this exception should be deleted". It did not. The second assertion only
    compared SCOPES, so routing an `AdminCustomerListView` gated on `customers.view` — the
    same scope search declares — passed in silence, and the exception would have quietly
    outlived the condition that justified it.

    Found by a Fable review during Plan-20 planning, and worth stating plainly because it
    is the fourth time this project has found a comment describing a control nobody built.
    The assertion below is now `not others`: any routed view in the `customers.` family
    fails this test, whatever scope it holds, which is what the docstring always promised.
    Today it is vacuously true — there are no such views.
    """
    from apps.accounts.tests.test_admin_surface_guard import ADMIN_SURFACE

    customers = next(s for s in SEARCH_SOURCES if s.key == "customers")
    assert customers.list_view_path is None, (
        "a customers list endpoint now exists — point the search source at it and delete "
        "the declared scope, so the derivation covers this section too"
    )
    others = {
        name: scope
        for name, scope in ADMIN_SURFACE.items()
        if (scope or "").startswith("customers.") and name != "AdminSearchView"
    }
    assert not others, (
        f"a customers endpoint is now routed ({others}) — this exception should be "
        f"deleted: point the search source's `list_view_path` at it, drop "
        f"`declared_scope`, and let the derivation cover this section like every other. "
        f"Add the queryset-parity test too; `_customers_base` was always meant to be "
        f"shared with the list endpoint."
    )


# --- 4. enumeration hygiene --------------------------------------------------


@pytest.mark.parametrize("term", ["", " ", "a", "ab", " ab "])
def test_the_minimum_term_length_is_enforced_server_side(api, matchable, term):
    """A client debounce is UX; this is the control.

    400 rather than an empty 200 because a too-short term is a malformed request rather
    than a search with no hits, and saying so is what stops somebody concluding the
    endpoint is broken. Whitespace is stripped BEFORE the length check, so a single space
    padded out to three characters does not sneak past.
    """
    response = search(api, term=term)
    assert response.status_code == 400, response.data
    assert "q" in response.data


def test_a_missing_q_is_a_400_and_not_a_dump_of_everything(api, matchable):
    """The failure mode worth naming: a search endpoint whose empty query means "match
    all" is an export endpoint with a different URL."""
    assert api.get(SEARCH_URL).status_code == 400


def test_an_over_long_term_is_refused(api, matchable):
    """Bounds the LIKE and, more importantly, bounds the audit row: the raw term is stored,
    so an unbounded term is an unbounded write into an append-only table."""
    assert search(api, term="z" * (MAX_TERM_LENGTH + 1)).status_code == 400


def test_results_are_capped_per_type(api, django_user_model):
    """The cap is the load-bearing enumeration control, and it is a cap with NO pagination
    on purpose: bulk access must go through the list endpoints, where it has its own,
    visible audit signature ("listed every order matching @gmail.com, 3,400 results").
    A paginated search would quietly become the export tool, with a much softer trail.
    """
    for i in range(RESULTS_PER_TYPE + 5):
        django_user_model.objects.create_user(email=f"zeta{i}@example.test")

    response = search(api)

    assert len(response.data["customers"]) == RESULTS_PER_TYPE
    assert "next" not in response.data and "count" not in response.data


def test_a_percent_in_the_term_is_a_literal_percent(api, django_user_model):
    """Django's `icontains` escapes LIKE wildcards, so no action is needed here — this test
    exists to PIN that, because "fix" the escaping away and the endpoint becomes a
    wildcard-injection oracle over the customer table.
    """
    django_user_model.objects.create_user(email="ab%cd@example.test")
    django_user_model.objects.create_user(email="abzcd@example.test")

    emails = [row["email"] for row in search(api, term="ab%cd").data["customers"]]

    assert emails == ["ab%cd@example.test"], (
        "a literal % matched other rows — the LIKE wildcard is no longer being escaped"
    )


def test_an_underscore_in_the_term_is_a_literal_underscore(api, django_user_model):
    """The wildcard everybody forgets. `_` matches any single character in LIKE."""
    django_user_model.objects.create_user(email="a_c@example.test")
    django_user_model.objects.create_user(email="abc@example.test")

    emails = [row["email"] for row in search(api, term="a_c").data["customers"]]

    assert emails == ["a_c@example.test"]


def test_the_throttle_is_keyed_on_the_user_and_locks_out_only_that_user(
    monkeypatch, roles, matchable
):
    """~60/min, request-counted, keyed on the USER — and that combination is safe here for
    a reason worth stating, because every other lesson on this branch says request-counting
    caps become denial buttons.

    Those lessons were all about SHARED OR FORGEABLE keys: `admin_login_ip` is one bucket
    for the whole staff because the BFF calls the API server-side, so anybody could fill
    it and lock everybody out. This key comes from the validated admin token. It cannot be
    forged (it is the authenticated user) and it is not shared, so the only person a caller
    can throttle is themselves, for a minute.
    """
    from apps.accounts.throttling import AdminSearchThrottle

    # Patching the CLASS attribute, not Django settings: DRF binds
    # `SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES` at import
    # time, so a settings override never reaches an already-imported throttle class. Same
    # pattern (and same trap) as `test_auth_throttling.tight_register_ip_rate`. The point
    # here is that the cap EXISTS and is per-user, not that it is 60.
    monkeypatch.setattr(
        AdminSearchThrottle,
        "THROTTLE_RATES",
        {**AdminSearchThrottle.THROTTLE_RATES, "admin_search": "2/min"},
    )

    manager = client_for(roles["Manager"])
    assert search(manager).status_code == 200
    assert search(manager).status_code == 200
    assert search(manager).status_code == 429

    # A different staff member is entirely unaffected — the property that makes this a
    # per-caller cost rather than a lever anyone can pull on anyone.
    assert search(client_for(roles["Support"])).status_code == 200


# --- 5. what the results actually say ----------------------------------------


def test_the_cards_carry_the_fields_the_phone_questions_need(api, matchable):
    """Plans 17/18 have not built the detail pages, so results carry NO links — the useful
    fields are inline instead. "What is the status of TC-ZETA01" and "which customer is
    this email" are answerable from this payload with zero navigation and zero 404s.
    """
    data = search(api).data

    order = data["orders"][0]
    assert order["number"] == "TC-ZETA01"
    assert order["status"] == "processing"
    assert order["grand_total"] == "1500.00"
    assert order["currency"] == "NGN"

    customer = data["customers"][0]
    assert customer["toke_id"] == matchable["customer"].toke_id
    assert customer["name"] == "Zeta Buyer"

    product = data["products"][0]
    assert product["name"] == "Zeta Cream"
    assert product["skus"] == ["ZETA-50"]


def test_orders_match_on_number_email_and_legacy_number(api):
    """The three things somebody reads off a bank transfer or a WhatsApp message. The
    legacy number matters more than it looks: 879 migrated NG orders carry one, and a
    customer quoting an old order number is exactly the case search exists for."""
    ng = Country.objects.get(code="NG")
    OrderFactory(number="TC-100777", country=ng, currency=ng.currency, email="a@b.test")
    OrderFactory(
        number="TC-100778",
        legacy_number="NG-5150",
        country=ng,
        currency=ng.currency,
        email="findme@b.test",
    )

    assert [o["number"] for o in search(api, term="100777").data["orders"]] == ["TC-100777"]
    assert [o["number"] for o in search(api, term="NG-5150").data["orders"]] == ["TC-100778"]
    assert [o["number"] for o in search(api, term="findme").data["orders"]] == ["TC-100778"]


def test_products_match_on_name_and_sku(api, matchable):
    by_sku = search(api, term="ZETA-50").data["products"]
    assert [p["slug"] for p in by_sku] == ["zeta-cream"]


def test_a_product_matching_on_two_variants_appears_once(api):
    """`variants__sku` is a join, so a product with two matching SKUs would come back
    twice without `distinct()` — and a duplicated row silently eats one of the ten slots."""
    product = ProductFactory(name="Twin", slug="twin")
    ProductVariantFactory(product=product, sku="TWIN-50")
    ProductVariantFactory(product=product, sku="TWIN-100", is_default=False)

    assert len(search(api, term="TWIN-").data["products"]) == 1


# --- 6. the audit row --------------------------------------------------------


def audit_rows():
    return AuditLog.objects.filter(model_label=SEARCH_AUDIT_MODEL_LABEL)


def test_one_search_writes_one_row_carrying_the_raw_term_and_per_type_counts(api, matchable):
    """**The raw term, not a hash and not a truncation.**

    "What did this person search for in the week before they quit" is the question this row
    exists to answer, and a hash only answers suspicions somebody already holds — it can
    confirm a guess and can never produce a lead. The counts are the harvest-detection
    signal: fifty searches returning ten customers each tells the whole story without a
    single additional byte of customer data.
    """
    search(api)

    row = audit_rows().get()
    assert row.action == SEARCH_AUDIT_ACTION
    assert row.actor_email == "owner@toke.test"
    assert row.client_ip == CLIENT_IP
    assert row.token_jti, "the row must name WHICH login searched, not just who"
    assert row.changes["query"] == {"q": TERM}
    assert row.changes["counts"] == {"orders": 1, "customers": 1, "products": 1}


def test_the_counts_name_only_the_sections_the_caller_could_see(roles, matchable):
    """Which is itself part of the record: the row says what this role was shown, so a
    later reader does not have to reconstruct the scope table as it was on the day."""
    search(client_for(roles["Support"]))

    assert audit_rows().get().changes["counts"] == {"orders": 1, "customers": 1}


def test_a_refused_search_writes_no_row(api, matchable):
    """The mixin writes on 2xx only. A 400 changed nothing and returned nothing, and a
    table where "typed two characters" looks like "ran a search" answers the wrong
    question."""
    search(api, term="ab")
    assert audit_rows().count() == 0


def test_the_security_mirror_carries_keys_only_never_the_term(api, matchable, caplog):
    """VERIFIED, not assumed. The keys-only mirror is what keeps search terms out of the
    log stream and therefore out of Sentry breadcrumbs — the term lives in the database
    row, where it is bounded by the 90-day tombstone, and nowhere else.
    """
    with caplog.at_level("INFO", logger="apps.security"):
        search(api)

    lines = [r.getMessage() for r in caplog.records if r.name == "apps.security"]
    assert any(SEARCH_AUDIT_ACTION in line for line in lines), lines
    assert not any(TERM in line for line in lines), (
        f"the search term reached the security log: {lines}"
    )


# --- 7. bounded retention ----------------------------------------------------


def later(days=SEARCH_TERM_RETENTION_DAYS + 1):
    """A clock far enough forward that today's rows are past the retention window.

    THE SWEEP IS MOVED, NOT THE ROWS, and that is forced rather than stylistic: the
    Postgres trigger from `core/0006_auditlog_append_only` refuses an UPDATE of any column
    but `changes`, so a test cannot backdate `created_at` at all. Which is the fence
    working — and it means the honest way to test a retention window here is to run the
    sweep from the future.
    """
    return timezone.now() + timedelta(days=days)


def test_search_terms_are_tombstoned_after_ninety_days(api, matchable):
    """A two-year archive of typed email fragments is liability, not audit.

    The ROW SKELETON survives indefinitely — actor, jti, IP, timestamp and the counts, so
    "this account ran forty searches that week" stays provable forever. Only the term
    itself is bounded, because the term is the only part that is somebody else's data.
    """
    from apps.core.audit import tombstone_expired_search_terms

    search(api)
    row = audit_rows().get()

    assert tombstone_expired_search_terms(now=later()) == 1

    row.refresh_from_db()
    assert row.changes["query"] == {"q": REDACTED}
    assert row.changes["counts"] == {"orders": 1, "customers": 1, "products": 1}
    assert row.actor_email == "owner@toke.test" and row.token_jti


def test_a_recent_search_term_is_left_alone(api, matchable):
    """And the beat task is what proves the wiring: it takes no arguments, so a sweep that
    ran on the wrong clock in production would be a bug in the function, not in the call."""
    from apps.core.tasks import tombstone_search_terms

    search(api)
    assert tombstone_search_terms() == 0
    assert audit_rows().get().changes["query"] == {"q": TERM}


def test_the_tombstone_sweep_is_idempotent(api, matchable):
    """It runs daily against the same rows forever, so a second pass must be a no-op — both
    for the count it reports and, more importantly, because every write to this table goes
    through the one permitted UPDATE and a churning sweep would bury real redactions."""
    from apps.core.audit import tombstone_expired_search_terms

    search(api)

    assert tombstone_expired_search_terms(now=later()) == 1
    assert tombstone_expired_search_terms(now=later()) == 0


def test_the_sweep_touches_no_other_kind_of_row(api, matchable):
    """Audit retention is INDEFINITE for everything else (see `AuditLog`'s docstring). This
    sweep is scoped to search rows alone, and picking a retention window for the rest of
    the table is not this task's decision to make."""
    from apps.core.audit import tombstone_expired_search_terms

    api.get("/api/v1/admin/orders/", {"search": "zeta"})
    other = AuditLog.objects.exclude(model_label=SEARCH_AUDIT_MODEL_LABEL).get()

    tombstone_expired_search_terms(now=later(days=400))

    other.refresh_from_db()
    assert other.changes["query"] == {"search": "zeta"}


# --- 8. deleted accounts -----------------------------------------------------


def test_deleting_an_account_tombstones_searches_naming_its_email_or_toke_id(
    api, django_user_model
):
    """The deletion promise reaches the search log too.

    A staff member who searched for a customer's address left that address in an audit row
    whose `object_id` is empty — a search has no object — so the `(model_label, object_id)`
    pass cannot find it. The text pass can, and the toke_id needle is what this task added:
    the email was already covered, a public customer id was not.
    """
    from apps.accounts.tasks import anonymize_deleted_accounts

    customer = django_user_model.objects.create_user(email="leaver@example.test")
    search(api, term="leaver@example.test")
    search(api, term=customer.toke_id)

    customer.is_active = False
    customer.deletion_requested_at = timezone.now() - timedelta(days=31)
    customer.save(update_fields=["is_active", "deletion_requested_at"])
    assert anonymize_deleted_accounts() == 1

    # Blanked WHOLE — `query` and `counts` both become the tombstone — rather than losing
    # only the term. That is the deliberate simplification recorded in
    # `redact_audit_values`: one redaction shape for the deletion promise instead of two.
    # The handful of rows naming one departing customer are not the harvest signal; the
    # aggregate across all of an actor's rows is, and those are untouched.
    assert [row.changes["query"] for row in audit_rows()] == [REDACTED, REDACTED]
    assert [row.changes["counts"] for row in audit_rows()] == [REDACTED, REDACTED]
    # The skeleton still says who searched, from where, and when.
    assert all(row.actor_email == "owner@toke.test" and row.token_jti for row in audit_rows())


def test_a_partial_prefix_of_a_deleted_email_is_not_matched(api, django_user_model):
    """**THE HONEST RESIDUAL, pinned as a test so it cannot be forgotten or overstated.**

    The deletion sweep finds rows by an exact substring match on the address and the
    toke_id. A staff member who typed only `leav` searched for the same person and left a
    fragment that no needle matches, and that fragment lives out its ≤90 days under the
    retention sweep above before disappearing.

    That is a bounded, stated imperfection rather than a fictional control. Closing it
    would mean either matching fragments against every deleted address (an unbounded
    prefix search over an append-only table, on every deletion) or refusing to store terms
    at all — which would delete the reason the log exists. The 90-day bound is what makes
    the residual acceptable: it has an end date whether or not anybody is deleted.
    """
    from apps.accounts.tasks import anonymize_deleted_accounts

    customer = django_user_model.objects.create_user(email="leaver@example.test")
    search(api, term="leav")

    customer.is_active = False
    customer.deletion_requested_at = timezone.now() - timedelta(days=31)
    customer.save(update_fields=["is_active", "deletion_requested_at"])
    anonymize_deleted_accounts()

    assert audit_rows().get().changes["query"] == {"q": "leav"}, (
        "if this now passes as REDACTED the residual has been closed — update the "
        "docstrings in apps/core/audit.py and apps/accounts/tasks.py, which currently "
        "state it plainly"
    )


# --- 9. constants used by the docs above -------------------------------------


def test_the_minimum_and_the_cap_are_what_the_rulings_say():
    """Cheap, and it makes the two numbers the rest of this file argues about impossible to
    change without reading the arguments."""
    assert MIN_TERM_LENGTH == 3
    assert RESULTS_PER_TYPE == 10
    assert SEARCH_TERM_RETENTION_DAYS == 90
