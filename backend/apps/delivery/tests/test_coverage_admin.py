"""Plan-19d: coverage editing and the regions browser.

Coverage is MIXED GRANULARITY (master spec Decision 13) — an option can serve whole
countries, whole states, or individual LGAs, in any combination. Nigeria alone has 811
regions (37 states, 774 areas), which is why this is its own endpoint and its own screen
rather than a field on the price form.
"""
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


def _option():
    # NGN explicitly: the coverage endpoint refuses coverage in a currency the option
    # is not priced in, and these tests cover NG places.
    return DeliveryOption.objects.create(
        name="Lagos Delivery", price="1500", currency=Currency.objects.get(code="NGN"),
        min_days=1, max_days=2,
    )


def _regions():
    state = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=state)
    eti_osa = Region.objects.create(country_code="NG", name="Eti-Osa", level="area", parent=state)
    return state, ikeja, eti_osa


def test_regions_require_staff():
    assert APIClient().get("/api/v1/admin/regions/").status_code in (401, 403)


def test_the_browser_returns_the_whole_tree_unpaginated(client):
    """37 states and 774 areas in one response beats 37 requests to expand each state,
    and the client assembles the tree from `parent`."""
    _regions()

    response = client.get("/api/v1/admin/regions/?country_code=NG")

    assert response.status_code == 200
    # Not a paginated envelope — a bare list.
    assert isinstance(response.data, list)
    assert {r["name"] for r in response.data} >= {"Lagos", "Ikeja", "Eti-Osa"}


def test_a_region_can_be_deactivated_but_NOT_created_or_deleted(client):
    """The 811 rows are reference data seeded by migration. A typo'd extra "Lagos" would
    silently never match a real address."""
    state, _, _ = _regions()

    assert client.patch(
        f"/api/v1/admin/regions/{state.pk}/", {"is_active": False}, format="json"
    ).status_code == 200
    state.refresh_from_db()
    assert state.is_active is False

    assert client.post(
        "/api/v1/admin/regions/", {"country_code": "NG", "name": "Nowhere", "level": "state"},
        format="json",
    ).status_code == 405
    assert client.delete(f"/api/v1/admin/regions/{state.pk}/").status_code == 405


def test_coverage_can_mix_a_whole_country_and_individual_areas(client):
    option = _option()
    _state, ikeja, _eti = _regions()

    response = client.put(
        f"/api/v1/admin/delivery-options/{option.pk}/coverage/",
        {"country_codes": ["NG"], "region_ids": [ikeja.pk]},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert list(option.countries.values_list("code", flat=True)) == ["NG"]
    assert list(option.regions.values_list("id", flat=True)) == [ikeja.pk]


def test_COVERAGE_IS_A_REPLACE_NOT_A_MERGE(client):
    """So "serve only Ikeja now" is expressible. A merge would make removal impossible
    through this endpoint."""
    option = _option()
    _state, ikeja, eti_osa = _regions()
    option.regions.set([ikeja, eti_osa])

    client.put(
        f"/api/v1/admin/delivery-options/{option.pk}/coverage/",
        {"region_ids": [ikeja.pk]},
        format="json",
    )

    assert list(option.regions.values_list("id", flat=True)) == [ikeja.pk]


def test_an_omitted_key_leaves_that_half_alone(client):
    """The reason coverage is not on the price PATCH: a client that omits a key must not
    silently clear it. Here omission is explicit — sending only regions leaves countries."""
    option = _option()
    option.countries.set(Country.objects.filter(code="NG"))
    _state, ikeja, _eti = _regions()

    client.put(
        f"/api/v1/admin/delivery-options/{option.pk}/coverage/",
        {"region_ids": [ikeja.pk]},
        format="json",
    )

    assert list(option.countries.values_list("code", flat=True)) == ["NG"]


def test_the_price_patch_still_cannot_touch_coverage(client):
    """A PATCH carrying coverage keys is now REFUSED outright (400) rather than
    half-applied — the client learns it is doing something unsupported, and neither
    the price nor the coverage moves."""
    option = _option()
    option.countries.set(Country.objects.filter(code="NG"))

    response = client.patch(
        f"/api/v1/admin/delivery-options/{option.pk}/",
        {"price": "1800", "country_codes": []},
        format="json",
    )

    assert response.status_code == 400
    option.refresh_from_db()
    assert str(option.price) == "1500.00"
    assert list(option.countries.values_list("code", flat=True)) == ["NG"]
