"""Duplicate handling: one hard rule, one soft warning, and the line between them.

THE HARD RULE refuses the same name AND the same address in the same place. That is
the definition of an accidental re-entry — a double-submitted form, a spreadsheet
pasted twice — and there is no legitimate row it blocks.

THE SOFT WARNING fires on anything fuzzier: a shared name in one LGA, a shared
address, a shared phone. Every one of those has a legitimate shape (a chain's two
branches, a mall's two counters, a distributor who also runs a salon), so it is a
409 the operator can override, never a refusal.
"""

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.stores.factories import region, store
from apps.stores.models import StoreLocation
from apps.stores.normalize import address_key, name_key

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/stores/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def body(**overrides):
    out = {
        "name": "Beauty Hub",
        "store_type": "distributor",
        "country": "NG",
        "state_region": region("Lagos").pk,
        "area_region": region("Lagos", "Alimosho").pk,
        "address": "15 Example Street",
        "phone": "+2348000000000",
    }
    out.update(overrides)
    return out


# --- normalisation ---------------------------------------------------------


def test_the_match_keys_ignore_the_noise_people_actually_type():
    assert name_key("  Beauty   HUB ") == name_key("beauty hub")
    assert name_key("Bó’s Beauty") == name_key("Bo's Beauty")
    assert address_key("12, Hassan Balogun St.") == address_key("12 Hassan Balogun Street")
    assert address_key("4 Allen Ave") == address_key("4 Allen Avenue")
    # Different shops stay different.
    assert address_key("12 Hassan Balogun Street") != address_key("14 Hassan Balogun Street")


def test_the_keys_are_maintained_by_the_model_not_the_serializer():
    row = store("  Beauty   Hub ", address="12, Hassan Balogun St.")
    assert row.name_key == "beauty hub"
    assert row.address_key == "12 hassan balogun street"
    row.name = "Renamed"
    row.save()
    assert StoreLocation.objects.get(pk=row.pk).name_key == "renamed"


# --- the hard rule ---------------------------------------------------------


def test_the_same_name_at_the_same_address_in_the_same_lga_cannot_exist_twice(client):
    first = client.post(BASE, body(), format="json")
    assert first.status_code == 201

    # Even with the override — the constraint is not a warning.
    again = client.post(
        BASE, body(name="beauty   hub", address="15, Example St.", confirm_duplicate=True),
        format="json",
    )
    assert again.status_code == 409, again.data
    assert StoreLocation.objects.count() == 1


def test_two_branches_of_one_chain_in_one_lga_are_allowed(client):
    """The reason the hard rule needs the address in it. Refusing this is how an
    operator learns to type "Beauty Hub 2"."""
    assert client.post(BASE, body(), format="json").status_code == 201
    second = client.post(
        BASE, body(address="9 Other Road", confirm_duplicate=True), format="json"
    )
    assert second.status_code == 201, second.data
    assert StoreLocation.objects.count() == 2


def test_two_counters_at_one_address_are_allowed(client):
    assert client.post(BASE, body(), format="json").status_code == 201
    second = client.post(
        BASE, body(name="Different Shop", confirm_duplicate=True), format="json"
    )
    assert second.status_code == 201


def test_the_same_shop_in_two_different_lgas_is_two_shops(client):
    assert client.post(BASE, body(), format="json").status_code == 201
    ikeja = client.post(
        BASE, body(area_region=region("Lagos", "Ikeja").pk, confirm_duplicate=True),
        format="json",
    )
    assert ikeja.status_code == 201


def test_the_constraint_frees_up_when_a_row_is_archived(client):
    """Archiving is how a shop leaves the directory, so re-adding it afterwards has
    to work — a partial index (`WHERE archived_at IS NULL`) is what makes it."""
    first = client.post(BASE, body(), format="json").data
    client.delete(f"{BASE}{first['id']}/")
    again = client.post(BASE, body(confirm_duplicate=True), format="json")
    assert again.status_code == 201


def test_the_rule_also_holds_where_there_is_no_lga(client):
    """GB rows have `area_region = NULL`, and SQL unique indexes treat NULLs as
    distinct — a single constraint naming `area_region` would enforce nothing at
    all outside Nigeria. Two constraints is why this fails."""
    from apps.core.models import Region

    england = Region.objects.get(country_code="GB", level="state", name="England")
    gb = {
        "name": "London Stockist", "store_type": "distributor", "country": "GB",
        "state_region": england.pk, "city_text": "London",
        "address": "4 Regent Street", "phone": "+442079460000",
    }
    assert client.post(BASE, gb, format="json").status_code == 201
    again = client.post(BASE, {**gb, "confirm_duplicate": True}, format="json")
    assert again.status_code == 409
    assert StoreLocation.objects.filter(country__code="GB").count() == 1


# --- the soft warning ------------------------------------------------------


def test_a_shared_name_in_the_same_lga_warns_and_can_be_overridden(client):
    client.post(BASE, body(), format="json")

    warned = client.post(BASE, body(address="9 Other Road"), format="json")
    assert warned.status_code == 409
    hints = warned.data["possible_duplicates"]
    assert [h["reason"] for h in hints] == ["name"]
    assert hints[0]["label"] == "Beauty Hub"
    assert StoreLocation.objects.count() == 1, "nothing is written while warning"

    accepted = client.post(
        BASE, body(address="9 Other Road", confirm_duplicate=True), format="json"
    )
    assert accepted.status_code == 201
    assert StoreLocation.objects.count() == 2


def test_a_shared_name_in_a_different_lga_does_not_warn(client):
    """A chain with a branch per LGA would otherwise warn on every single row, and a
    warning that always fires is a warning nobody reads."""
    client.post(BASE, body(), format="json")
    other = client.post(
        BASE,
        body(area_region=region("Lagos", "Ikeja").pk, address="9 Allen Avenue",
             phone="+2348011111111"),
        format="json",
    )
    assert other.status_code == 201, other.data


def test_a_shared_phone_warns_anywhere_in_the_state(client):
    client.post(BASE, body(phone="+2348023900964"), format="json")
    response = client.post(
        BASE,
        body(name="Totally Different", address="9 Allen Avenue",
             area_region=region("Lagos", "Ikeja").pk, phone="+2348023900964"),
        format="json",
    )
    assert response.status_code == 409
    assert response.data["possible_duplicates"][0]["reason"] == "phone"


def test_an_archived_look_alike_is_reported_as_archived(client):
    """"You archived this last month" is exactly what somebody re-typing it needs
    to hear — and the hard constraint no longer blocks them, so the warning is the
    only thing that will say it."""
    first = client.post(BASE, body(), format="json").data
    client.delete(f"{BASE}{first['id']}/")

    response = client.post(BASE, body(), format="json")
    assert response.status_code == 409
    assert "archived" in response.data["possible_duplicates"][0]["detail"]


def test_an_existing_pickup_location_is_flagged(client):
    """The divergence this feature is most likely to cause: our own Ogudu counter
    filed here a second time, unnoticed, while checkout goes on offering pickup from
    the `SenderLocation` row. Nothing links the two tables, so the warning is the
    control."""
    from apps.delivery.models import SenderLocation

    SenderLocation.objects.create(
        name="Ogudu Mall (Lagos)", phone="+2347074800702",
        address="15 Example Street", locality="Ogudu",
        latitude="6.586000", longitude="3.263000", customer_pickup=True,
    )
    response = client.post(BASE, body(name="Toke Ogudu Store"), format="json")
    assert response.status_code == 409
    hint = next(h for h in response.data["possible_duplicates"]
                if h["kind"] == "pickup_location")
    assert "checkout" in hint["detail"]

    assert client.post(
        BASE, body(name="Toke Ogudu Store", confirm_duplicate=True), format="json"
    ).status_code == 201


def test_editing_an_unrelated_field_never_re_warns(client):
    """A row with a look-alike next door must stay editable. Deactivating it is not
    a decision about the look-alike, and a warning there would have to be clicked
    through every time — which is how operators learn to ignore them."""
    created = client.post(BASE, body(), format="json").data
    client.post(BASE, body(address="9 Other Road", confirm_duplicate=True), format="json")

    off = client.patch(f"{BASE}{created['id']}/", {"is_active": False}, format="json")
    assert off.status_code == 200

    hours = client.patch(
        f"{BASE}{created['id']}/", {"opening_hours": "Mon–Sat, 9–7"}, format="json"
    )
    assert hours.status_code == 200


def test_a_store_is_never_its_own_duplicate(client):
    created = client.post(BASE, body(), format="json").data
    same = client.patch(f"{BASE}{created['id']}/", {"name": "Beauty Hub"}, format="json")
    assert same.status_code == 200


def test_renaming_onto_a_neighbour_warns(client):
    client.post(BASE, body(name="Beauty Hub"), format="json")
    created = client.post(
        BASE, body(name="Glow Room", address="9 Other Road", phone="+2348011111111"),
        format="json",
    )
    assert created.status_code == 201, created.data
    other = created.data

    response = client.patch(f"{BASE}{other['id']}/", {"name": "Beauty Hub"}, format="json")
    assert response.status_code == 409
    assert response.data["possible_duplicates"][0]["reason"] == "name"

    forced = client.patch(
        f"{BASE}{other['id']}/", {"name": "Beauty Hub", "confirm_duplicate": True},
        format="json",
    )
    assert forced.status_code == 200
