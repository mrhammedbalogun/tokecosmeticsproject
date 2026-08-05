"""The location-first create path (Countries_breakdown work).

POST /admin/delivery-options/ accepts coverage inline so an option and where it is
offered are born in ONE request — no window where a coverage-less option sits active
and matches nothing. The serializer is the audit boundary for the traps that
otherwise ship silently: unknown carriers priced at 0, cross-currency coverage that
checkout filters out forever, quote_required with no disclaimer to show.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country, Currency, Region
from apps.delivery.models import DeliveryOption

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _payload(**over):
    defaults = {
        "name": "Ikeja Same-Day", "price": "2000", "currency": "NGN",
        "min_days": 0, "max_days": 1, "country_codes": ["NG"],
    }
    return {**defaults, **over}


def test_an_option_and_its_coverage_are_created_in_one_request(client):
    lagos = Region.objects.create(country_code="NG", name="Lagos X", level="state")

    response = client.post(
        "/api/v1/admin/delivery-options/",
        _payload(country_codes=[], region_ids=[lagos.id]),
        format="json",
    )

    assert response.status_code == 201, response.data
    option = DeliveryOption.objects.get(pk=response.data["id"])
    assert list(option.regions.values_list("id", flat=True)) == [lagos.id]


def test_an_option_covering_nowhere_is_refused(client):
    """An uncovered option shows "Offered at checkout ✓" in the admin and matches no
    address at all — the phantom the one-request create exists to prevent."""
    response = client.post(
        "/api/v1/admin/delivery-options/", _payload(country_codes=[]), format="json"
    )

    assert response.status_code == 400
    assert "country_codes" in response.data


def test_cross_currency_coverage_is_refused(client):
    """checkout filters options to the order country's currency, so an NGN option
    covering GB is not an error anywhere at runtime — it silently never appears."""
    response = client.post(
        "/api/v1/admin/delivery-options/",
        _payload(currency="NGN", country_codes=["GB"]),
        format="json",
    )

    assert response.status_code == 400
    assert "currency" in response.data


def test_an_unknown_carrier_is_refused(client):
    """A carrier option checkout cannot quote falls through to its flat price — and the
    carrier pattern sets price=0, so the failure mode is free delivery."""
    response = client.post(
        "/api/v1/admin/delivery-options/",
        _payload(kind="carrier", carrier_code="dhl", price="0"),
        format="json",
    )

    assert response.status_code == 400
    assert "carrier_code" in response.data


def test_quote_required_needs_the_disclaimer(client):
    """quote_required renders NO price — the disclaimer is the only text shown in its
    place, and without one the option is a nameless blank at checkout."""
    response = client.post(
        "/api/v1/admin/delivery-options/",
        _payload(quote_required=True, disclaimer=""),
        format="json",
    )

    assert response.status_code == 400
    assert "disclaimer" in response.data


def test_new_options_join_the_end_of_the_checkout_list(client):
    """checkout orders by (sort, name); the model default of 0 would put every new
    option ABOVE the seeded ones. Unsent sort lands after the current maximum."""
    DeliveryOption.objects.create(
        name="Existing", price="1000", currency=Currency.objects.get(code="NGN"),
        min_days=1, max_days=2, sort=10,
    )

    response = client.post("/api/v1/admin/delivery-options/", _payload(), format="json")

    assert response.status_code == 201, response.data
    assert DeliveryOption.objects.get(pk=response.data["id"]).sort > 10


def test_coverage_still_cannot_be_edited_through_a_patch(client):
    """Writable-on-create must not quietly reopen the price-PATCH-clears-coverage
    accident the separate coverage endpoint exists to prevent."""
    option = DeliveryOption.objects.create(
        name="Nationwide", price="3500", currency=Currency.objects.get(code="NGN"),
        min_days=1, max_days=4,
    )
    option.countries.set(Country.objects.filter(code="NG"))

    response = client.patch(
        f"/api/v1/admin/delivery-options/{option.pk}/",
        {"country_codes": ["GB"]},
        format="json",
    )

    assert response.status_code == 400
    assert list(option.countries.values_list("code", flat=True)) == ["NG"]


def test_the_coverage_endpoint_also_refuses_cross_currency(client):
    option = DeliveryOption.objects.create(
        name="Lagos", price="1500", currency=Currency.objects.get(code="NGN"),
        min_days=1, max_days=2,
    )

    response = client.put(
        f"/api/v1/admin/delivery-options/{option.pk}/coverage/",
        {"country_codes": ["US"], "region_ids": []},
        format="json",
    )

    assert response.status_code == 400


def test_preview_answers_with_the_real_matcher(client):
    """The admin address-tester asks the backend, not a client-side mirror."""
    lagos = Region.objects.create(country_code="NG", name="Lagos Y", level="state")
    ngn = Currency.objects.get(code="NGN")
    covered = DeliveryOption.objects.create(
        name="Lagos Only", price="1500", currency=ngn, min_days=1, max_days=2,
    )
    covered.regions.set([lagos])
    elsewhere = DeliveryOption.objects.create(
        name="Kano Only", price="1500", currency=ngn, min_days=1, max_days=2,
    )
    elsewhere.regions.set(
        [Region.objects.create(country_code="NG", name="Kano Y", level="state")]
    )

    response = client.get(
        f"/api/v1/admin/delivery-options/preview/?country=NG&state_region={lagos.id}"
    )

    assert response.status_code == 200, response.data
    names = {o["name"] for o in response.data["options"]}
    assert "Lagos Only" in names
    assert "Kano Only" not in names
    lagos_only = next(o for o in response.data["options"] if o["name"] == "Lagos Only")
    assert Decimal(lagos_only["price"]) == Decimal("1500.00")


def test_the_intl_level1_seed_landed():
    """GB constituent countries, US states + DC, CA provinces + territories."""
    assert Region.objects.filter(country_code="GB", parent=None).count() == 4
    assert Region.objects.filter(country_code="US", parent=None).count() == 51
    assert Region.objects.filter(country_code="CA", parent=None).count() == 13
    assert Country.objects.get(code="CA").state_label == "Province"
    assert Country.objects.get(code="GB").state_label == "Country"
