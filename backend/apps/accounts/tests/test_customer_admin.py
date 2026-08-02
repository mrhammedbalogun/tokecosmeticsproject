"""The staff customer list and detail (Plan-18b).

Weighted deliberately toward what leaks rather than what renders: this is the densest PII
surface in the system, and it was scheduled before Plan-25 precisely so the hardening pass
would have it to test.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import LegacyIdentity, LegacyStore
from apps.core.models import AuditLog, Country, Currency
from apps.orders.models import Order

pytestmark = pytest.mark.django_db

User = get_user_model()
LIST = "/api/v1/admin/customers/"


@pytest.fixture
def markets(db):
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"name": "Naira", "symbol": "₦"})
    gbp, _ = Currency.objects.get_or_create(code="GBP", defaults={"name": "Pound", "symbol": "£"})
    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria", "currency": ngn})
    gb, _ = Country.objects.get_or_create(code="GB", defaults={"name": "UK", "currency": gbp})
    return {"NG": ng, "GB": gb, "NGN": ngn, "GBP": gbp}


PW = "Str0ng!pass9"


def _staff(email, role):
    user = User.objects.create_user(email=email, password=PW, is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def support_client(db):
    """Support holds `customers.view` — answering a customer's question is the job."""
    return _staff("support@toke.test", "Support")


@pytest.fixture
def content_client(db):
    """Content does not hold `customers.view`, and marketing copy is not a reason to read
    somebody's address."""
    return _staff("content@toke.test", "Content")


@pytest.fixture
def customer(db):
    user = User.objects.create_user(
        email="ada@example.com", password="x", first_name="Ada", last_name="Okafor",
        phone="+2348012345678",
    )
    return user


def order(user, markets, *, currency="NGN", total="10000.00", status="completed", email=None):
    country = "NG" if currency == "NGN" else "GB"
    return Order.objects.create(
        number=f"TC-{Order.objects.count() + 100000}",
        user=user,
        email=email or (user.email if user else "guest@example.com"),
        country=markets[country],
        currency=markets[currency],
        status=status,
        grand_total=Decimal(total),
        placed_at=timezone.now(),
    )


# ── access ───────────────────────────────────────────────────────────────────────────────


def test_an_anonymous_request_gets_nothing(client):
    assert client.get(LIST).status_code in (401, 403)


def test_A_SIGNED_IN_CUSTOMER_IS_NOT_A_STAFF_MEMBER(customer):
    # Being authenticated is not being authorised. A customer holds no group, so
    # `HasAdminScope` refuses them even with a valid session.
    client = APIClient()
    client.force_authenticate(customer)
    assert client.get(LIST).status_code == 403


def test_support_can_read_the_list(support_client):
    assert support_client.get(LIST).status_code == 200


def test_a_role_WITHOUT_customers_view_is_refused(content_client):
    assert content_client.get(LIST).status_code == 403


# ── what must never be serialised ────────────────────────────────────────────────────────


SECRETS = ["password", "totp", "secret", "recovery", "session", "token"]


def test_NO_CREDENTIAL_MATERIAL_APPEARS_IN_THE_LIST(support_client, customer):
    """`fields = "__all__"` minus a deny-list is one forgotten field away from publishing a
    credential, and the forgotten field is always the one added later. The serializers list
    fields explicitly; this asserts the result rather than the technique."""
    body = support_client.get(LIST).json()
    row = body["results"][0]

    for banned in SECRETS:
        assert not any(banned in key.lower() for key in row), f"{banned} leaked: {sorted(row)}"


def test_NO_CREDENTIAL_MATERIAL_APPEARS_IN_THE_DETAIL(support_client, customer):
    body = support_client.get(f"{LIST}{customer.toke_id}/").json()

    for banned in SECRETS:
        assert not any(banned in key.lower() for key in body), f"{banned} leaked: {sorted(body)}"
    assert customer.password not in str(body)


# ── who is visible ───────────────────────────────────────────────────────────────────────


def test_STAFF_ARE_NOT_IN_THE_CUSTOMER_LIST(support_client, customer):
    # A support agent granted `customers.view` should not be able to page through their
    # colleagues' contact details from a screen granted for customers.
    User.objects.create_user(email="colleague@example.com", password="x", is_staff=True)

    emails = [
        r["email"] for r in support_client.get(LIST).json()["results"]
    ]

    assert "ada@example.com" in emails
    assert "colleague@example.com" not in emails


def test_AN_ANONYMISED_CUSTOMER_IS_NOT_LISTED(support_client, customer):
    """Deletion is a two-phase soft delete and an anonymised row is an empty shell. A
    deleted customer who is still findable would be a deletion promise that was not kept —
    and the list must agree with the global search, or whichever shows more becomes a way
    around the other."""
    User.objects.create_user(email="deleted-TK-ABC123@deleted.invalid", password="x")

    emails = [
        r["email"] for r in support_client.get(LIST).json()["results"]
    ]

    assert not any(e.endswith("@deleted.invalid") for e in emails)


def test_an_anonymised_customer_cannot_be_fetched_directly_either(support_client):
    # Excluding a row from the list but serving it on the detail URL is the classic
    # half-applied filter.
    ghost = User.objects.create_user(email="deleted-TK-ABC123@deleted.invalid", password="x")
    response = support_client.get(f"{LIST}{ghost.toke_id}/")
    assert response.status_code == 404


def test_a_staff_member_cannot_be_fetched_by_toke_id(support_client):
    colleague = User.objects.create_user(email="c@example.com", password="x", is_staff=True)
    response = support_client.get(f"{LIST}{colleague.toke_id}/")
    assert response.status_code == 404


def test_an_unknown_toke_id_is_a_404(support_client):
    assert support_client.get(f"{LIST}TK-ZZZZZZ/").status_code == 404


# ── the money ────────────────────────────────────────────────────────────────────────────


def test_LIFETIME_VALUE_IS_PER_CURRENCY_AND_NEVER_SUMMED(support_client, customer, markets):
    # Plan-23 imports multi-currency history and the project bans FX mixing. A single
    # number here would be a signature that had to be broken later.
    order(customer, markets, currency="NGN", total="10000.00")
    order(customer, markets, currency="NGN", total="5000.00")
    order(customer, markets, currency="GBP", total="80.00")

    totals = support_client.get(
        f"{LIST}{customer.toke_id}/"
    ).json()["totals"]

    by_currency = {t["currency"]: t for t in totals}
    assert by_currency["NGN"]["lifetime_value"] == "15000.00"
    assert by_currency["NGN"]["orders"] == 2
    assert by_currency["GBP"]["lifetime_value"] == "80.00"


def test_UNPAID_ORDERS_ARE_NOT_LIFETIME_VALUE(support_client, customer, markets):
    """The same REVENUE_STATUSES the dashboard uses. Plan-23 imports 2,277 abandoned bank
    transfers as `expired`; if those counted here, every migrated customer would look like
    a big spender who never paid."""
    order(customer, markets, total="10000.00", status="completed")
    order(customer, markets, total="99999.00", status="expired")
    order(customer, markets, total="88888.00", status="cancelled")

    totals = support_client.get(
        f"{LIST}{customer.toke_id}/"
    ).json()["totals"]

    assert totals[0]["lifetime_value"] == "10000.00"
    assert totals[0]["orders"] == 1


def test_the_detail_agrees_with_the_top_customers_report(customer, markets):
    # Two screens, one definition. If they disagreed, both numbers would be untrustworthy
    # and neither obviously the wrong one.
    from datetime import timedelta

    from apps.analytics.queries import Range, customer_totals, top_customers

    order(customer, markets, total="10000.00")
    window = Range(
        start=timezone.now() - timedelta(days=1), end=timezone.now() + timedelta(days=1)
    )

    detail = {t["currency_id"]: t["lifetime_value"] for t in customer_totals(customer.pk)}
    report = {
        r["currency_id"]: r["lifetime_value"]
        for r in top_customers(window)
        if r["email"] == customer.email
    }

    assert detail["NGN"] == report["NGN"]


def test_GUEST_ORDERS_ARE_COUNTED_SEPARATELY_NOT_ADDED_TO_LTV(
    support_client, customer, markets
):
    """Attributing an unclaimed guest order to this person would put money against
    somebody who has not proved the address is theirs — exactly the claim `claims.py`
    refuses to make. It IS shown, because "why can't they see their old orders?" is
    support's most common question about a migrated customer."""
    order(customer, markets, total="10000.00")
    order(None, markets, total="7500.00", email=customer.email)  # unclaimed

    body = support_client.get(f"{LIST}{customer.toke_id}/").json()

    assert body["totals"][0]["lifetime_value"] == "10000.00"
    assert body["unclaimed_guest_orders"] == 1


# ── the rest of the detail ───────────────────────────────────────────────────────────────


def test_the_detail_shows_which_legacy_stores_the_customer_came_from(
    support_client, customer
):
    LegacyIdentity.objects.create(user=customer, store=LegacyStore.NG, wp_user_id=101)
    LegacyIdentity.objects.create(user=customer, store=LegacyStore.INTL, wp_user_id=55)

    body = support_client.get(f"{LIST}{customer.toke_id}/").json()

    assert {i["store"] for i in body["legacy_identities"]} == {"legacy_ng", "legacy_intl"}


def test_the_list_is_searchable_and_filterable(support_client, customer):
    User.objects.create_user(email="zed@example.com", password="x", first_name="Zed")
    client = support_client

    assert client.get(LIST, {"search": "Okafor"}).json()["count"] == 1
    assert client.get(LIST, {"search": customer.toke_id}).json()["count"] == 1
    assert client.get(LIST, {"is_active": "false"}).json()["count"] == 0


def test_THE_LIST_DOES_NOT_FIRE_AN_AGGREGATE_PER_ROW(
    support_client, markets, django_assert_max_num_queries
):
    """LTV is on the detail, not the list. A 25-row page firing 25 aggregate queries is the
    N+1 that a "just show lifetime value in the table" request quietly buys."""
    for i in range(15):
        user = User.objects.create_user(email=f"c{i}@example.com", password="x")
        order(user, markets, total="100.00")

    client = support_client
    with django_assert_max_num_queries(12):
        assert client.get(LIST).status_code == 200


# ── it is read-only, and reads are audited ───────────────────────────────────────────────


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_THE_SURFACE_IS_READ_ONLY(support_client, customer, method):
    """Editing an email here would silently re-point order history and password resets;
    toggling is_active is what the deletion flow owns, on a timer, with an anonymisation
    sweep behind it. A write surface would be a second way to do both without either's
    rules."""
    client = support_client
    url = f"{LIST}{customer.toke_id}/"

    response = getattr(client, method)(url, {"email": "attacker@example.com"}, format="json")

    assert response.status_code == 405
    customer.refresh_from_db()
    assert customer.email == "ada@example.com"


def test_READING_A_CUSTOMER_IS_AUDITED(support_client, customer):
    # "Who looked up this customer" is the question that actually gets asked after an
    # incident, and it is only answerable if the read was recorded.
    before = AuditLog.objects.count()

    support_client.get(f"{LIST}{customer.toke_id}/")

    assert AuditLog.objects.count() > before


def test_reading_the_list_is_audited_too(support_client, customer):
    before = AuditLog.objects.count()
    support_client.get(LIST)
    assert AuditLog.objects.count() > before


def test_THE_DETAIL_RENDERS_A_REAL_ADDRESS(support_client, customer):
    """The gap that let a broken serializer through a green test run.

    Every address test here previously asserted the EMPTY case, so `CustomerAddressSerializer`
    naming a column `Address` does not have (`city` — the model stores `city_text`) built
    fine and never serialised anything. The OpenAPI schema test caught it, because
    generating a schema forces field construction. This exercises the field names against a
    real row so the next wrong one fails here first.
    """
    from apps.accounts.models import Address

    Address.objects.create(
        user=customer, label="Home", line1="1 Adeola Odeku", line2="Flat 3",
        city_text="Lagos", state_text="Lagos", postcode="101241", country_code="NG",
        is_default_shipping=True,
    )

    body = support_client.get(f"{LIST}{customer.toke_id}/").json()

    assert len(body["addresses"]) == 1
    address = body["addresses"][0]
    assert address["line1"] == "1 Adeola Odeku"
    assert address["city_text"] == "Lagos"
    assert address["postcode"] == "101241"
    assert address["is_default_shipping"] is True


def test_the_detail_serialiser_builds_its_fields_at_all(customer):
    # The cheapest possible version of the check above: DRF builds ModelSerializer fields
    # lazily, so a bad field name can sit unnoticed until something forces construction.
    from apps.accounts.customer_admin import CustomerDetailSerializer

    fields = CustomerDetailSerializer().fields
    assert "addresses" in fields and "totals" in fields
