"""The warehouse admin surface (Plan-17c Task 1).

Two of these tests are about the model rather than the HTTP: `serves_countries` decides
which warehouse `reserve()` may draw from, so unticking a country is not an ordinary edit.
`inventory/services.reserve()` filters on `warehouse__is_active=True,
warehouse__serves_countries=country` — untick NG on Lagos HQ and every checkout in the only
sellable market fails, with no error anywhere until a customer tries to buy something.

The endpoint does NOT refuse that edit. Reorganising warehouses is legitimate and the
backend cannot know whether the operator is midway through a two-step move. What it does is
publish the consequence — `countries_left_unserved` — so the admin can name it in the
confirmation ruling 1b requires, computed rather than asserted.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country
from apps.inventory.models import Warehouse

pytestmark = pytest.mark.django_db


def _only_these_warehouses():
    """Plan-06 seeds Lagos HQ and the UK Warehouse by data migration, so a test that
    reasons about "is any OTHER warehouse covering this country" must start from a known
    set rather than from whatever the seed left behind."""
    Warehouse.objects.all().delete()


def _countries():
    ng, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency_id": "NGN"}
    )
    gb, _ = Country.objects.get_or_create(
        code="GB", defaults={"name": "United Kingdom", "currency_id": "GBP"}
    )
    return ng, gb


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_warehouses_require_staff():
    assert APIClient().get("/api/v1/admin/warehouses/").status_code in (401, 403)


def test_list_and_create(client):
    ng, gb = _countries()

    created = client.post(
        "/api/v1/admin/warehouses/",
        {"name": "Abuja Depot", "location_country": "NG", "serves_countries": [ng.code],
         "priority": 2, "is_active": True},
        format="json",
    )

    assert created.status_code == 201, created.data
    assert Warehouse.objects.filter(name="Abuja Depot").exists()
    listed = client.get("/api/v1/admin/warehouses/")
    assert listed.status_code == 200
    assert any(row["name"] == "Abuja Depot" for row in listed.data["results"])


def test_serves_countries_is_writable(client):
    ng, gb = _countries()
    warehouse = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    warehouse.serves_countries.set([ng])

    response = client.patch(
        f"/api/v1/admin/warehouses/{warehouse.pk}/",
        {"serves_countries": [ng.code, gb.code]},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert set(warehouse.serves_countries.values_list("code", flat=True)) == {"NG", "GB"}


def test_DELETE_IS_NOT_OFFERED(client):
    """`StockItem.warehouse` is CASCADE, so deleting a warehouse silently destroys every
    stock row it holds and every movement's context. Deactivating is what "remove this
    warehouse" actually means, and it keeps the history."""
    ng, _ = _countries()
    warehouse = Warehouse.objects.create(name="Doomed", location_country="NG")

    response = client.delete(f"/api/v1/admin/warehouses/{warehouse.pk}/")

    assert response.status_code == 405
    assert Warehouse.objects.filter(pk=warehouse.pk).exists()


def test_publishes_which_countries_this_warehouse_is_the_last_one_serving(client):
    """The number ruling 1b's confirmation is built from. Lagos HQ is the only warehouse
    serving NG, so deactivating it strands Nigeria — and the operator must be told in those
    words, not left to infer it from a checkbox."""
    ng, gb = _countries()
    _only_these_warehouses()
    lagos = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    lagos.serves_countries.set([ng, gb])
    uk = Warehouse.objects.create(name="UK Warehouse", location_country="GB", priority=1)
    uk.serves_countries.set([gb])

    row = client.get(f"/api/v1/admin/warehouses/{lagos.pk}/").data

    # GB survives without Lagos because the UK warehouse also serves it. NG does not.
    assert row["countries_left_unserved"] == ["NG"]


def test_an_inactive_warehouse_does_not_count_as_cover(client):
    """`reserve()` filters on `is_active=True`, so an inactive warehouse serving a country
    is not serving it. Counting it would make the confirmation reassure and be wrong."""
    ng, _ = _countries()
    _only_these_warehouses()
    lagos = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    lagos.serves_countries.set([ng])
    backup = Warehouse.objects.create(
        name="Mothballed Depot", location_country="NG", is_active=False
    )
    backup.serves_countries.set([ng])

    row = client.get(f"/api/v1/admin/warehouses/{lagos.pk}/").data

    assert row["countries_left_unserved"] == ["NG"]


def test_a_warehouse_that_strands_nobody_says_so(client):
    ng, gb = _countries()
    _only_these_warehouses()
    first = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    first.serves_countries.set([ng])
    second = Warehouse.objects.create(name="Ikeja Annex", location_country="NG", priority=2)
    second.serves_countries.set([ng])

    row = client.get(f"/api/v1/admin/warehouses/{second.pk}/").data

    assert row["countries_left_unserved"] == []
