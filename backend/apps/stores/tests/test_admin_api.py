"""Store-directory admin: CRUD, validation, filtering, archive/restore.

`test_admin_role_matrix.py` proves WHO may reach these routes. This file proves
what happens once they are in — and in particular that every rule the admin form
pre-checks is re-proved here from ids the client supplied, because that is the only
copy of the rule an attacker cannot skip.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country, Region
from apps.stores.factories import region, store
from apps.stores.models import StoreLocation

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/stores/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def lagos():
    return region("Lagos")


@pytest.fixture
def alimosho():
    return region("Lagos", "Alimosho")


def payload(lagos, alimosho, **overrides):
    body = {
        "name": "Beauty Hub Alimosho",
        "store_type": "distributor",
        "country": "NG",
        "state_region": lagos.pk,
        "area_region": alimosho.pk,
        "address": "15 Example Street, Alimosho",
        "phone": "+2348000000000",
    }
    body.update(overrides)
    return body


# --- the fence -------------------------------------------------------------


def test_anonymous_callers_get_nothing():
    assert APIClient().get(BASE).status_code in (401, 403)
    assert APIClient().post(BASE, {}, format="json").status_code in (401, 403)


# --- create ----------------------------------------------------------------


def test_a_store_can_be_created_and_comes_back_listed(client, lagos, alimosho):
    created = client.post(BASE, payload(lagos, alimosho), format="json")
    assert created.status_code == 201, created.data
    assert created.data["status"] == "active"
    assert created.data["area_name"] == "Alimosho"
    assert created.data["state_label"] == "State" and created.data["area_label"] == "LGA"

    listed = client.get(BASE).data
    assert listed["count"] == 1
    assert listed["results"][0]["name"] == "Beauty Hub Alimosho"


def test_the_place_chain_is_re_proved_from_the_submitted_ids(client, lagos, alimosho):
    """Nigeria -> Lagos -> an LGA of Kano's. The admin form cannot produce this; a
    curl can, and the row it would create is findable by a state search and
    invisible to an LGA search — present and unreachable at the same time."""
    kano_lga = region("Kano", "Dala")
    bad_area = client.post(
        BASE, payload(lagos, alimosho, area_region=kano_lga.pk), format="json"
    )
    assert bad_area.status_code == 400 and "area_region" in bad_area.data

    gb = Country.objects.get(code="GB")
    bad_state = client.post(
        BASE, payload(lagos, alimosho, country=gb.code), format="json"
    )
    assert bad_state.status_code == 400 and "state_region" in bad_state.data


def test_the_finest_place_available_is_mandatory(client, lagos, alimosho):
    """Nigeria has LGAs, so an LGA is required. England has none, so a city is."""
    missing_lga = client.post(BASE, payload(lagos, alimosho, area_region=None), format="json")
    assert missing_lga.status_code == 400 and "area_region" in missing_lga.data
    assert "LGA" in missing_lga.data["area_region"][0].lower().replace("lga", "LGA")

    england = Region.objects.get(country_code="GB", level="state", name="England")
    missing_city = client.post(BASE, {
        "name": "London Stockist", "store_type": "distributor", "country": "GB",
        "state_region": england.pk, "address": "4 Regent Street",
        "phone": "+442079460000",
    }, format="json")
    assert missing_city.status_code == 400 and "city_text" in missing_city.data

    ok = client.post(BASE, {
        "name": "London Stockist", "store_type": "distributor", "country": "GB",
        "state_region": england.pk, "city_text": "London",
        "address": "4 Regent Street", "phone": "+442079460000",
    }, format="json")
    assert ok.status_code == 201, ok.data


def test_an_lga_cannot_be_attached_to_a_state_that_has_none(client, alimosho):
    england = Region.objects.get(country_code="GB", level="state", name="England")
    response = client.post(BASE, {
        "name": "Confused", "store_type": "distributor", "country": "GB",
        "state_region": england.pk, "area_region": alimosho.pk, "city_text": "London",
        "address": "4 Regent Street", "phone": "+442079460000",
    }, format="json")
    assert response.status_code == 400 and "area_region" in response.data


def test_phones_are_normalised_and_the_main_one_is_required(client, lagos, alimosho):
    spaced = client.post(
        BASE, payload(lagos, alimosho, phone="+234 802 390 0964"), format="json"
    )
    assert spaced.status_code == 201
    assert spaced.data["phone"] == "+2348023900964"

    # A local-format number needs a country guess, and a wrong guess dials a
    # stranger. Refused here exactly as everywhere else (core.phones).
    local = client.post(
        BASE, payload(lagos, alimosho, name="Two", phone="08023900964"), format="json"
    )
    assert local.status_code == 400 and "phone" in local.data

    blank = client.post(
        BASE, payload(lagos, alimosho, name="Three", phone=""), format="json"
    )
    assert blank.status_code == 400 and "phone" in blank.data

    nonsense = client.post(
        BASE, payload(lagos, alimosho, name="Four", phone="+1111"), format="json"
    )
    assert nonsense.status_code == 400 and "phone" in nonsense.data


def test_the_optional_numbers_may_be_blank_but_not_wrong(client, lagos, alimosho):
    ok = client.post(BASE, payload(lagos, alimosho, phone_alt="", whatsapp_phone=""),
                     format="json")
    assert ok.status_code == 201

    bad = client.post(
        BASE, payload(lagos, alimosho, name="Two", whatsapp_phone="0802"), format="json"
    )
    assert bad.status_code == 400 and "whatsapp_phone" in bad.data


def test_names_and_addresses_are_length_capped_and_whitespace_tidied(
    client, lagos, alimosho
):
    long_name = client.post(
        BASE, payload(lagos, alimosho, name="x" * 200), format="json"
    )
    assert long_name.status_code == 400 and "name" in long_name.data

    long_address = client.post(
        BASE, payload(lagos, alimosho, name="Two", address="y" * 400), format="json"
    )
    assert long_address.status_code == 400 and "address" in long_address.data

    tidied = client.post(
        BASE, payload(lagos, alimosho, name="  Beauty   Hub  "), format="json"
    )
    assert tidied.status_code == 201 and tidied.data["name"] == "Beauty Hub"


def test_special_characters_survive_a_round_trip_unmangled(client, lagos, alimosho):
    """Edge cases 11 and 12. The value is stored verbatim; nothing here escapes or
    strips it, because the storefront renders it as TEXT (React escapes) and the
    admin never interpolates it into HTML."""
    tricky = "Bó’s Beauty & Co. <Ikotun> — 100% Naturals"
    created = client.post(
        BASE, payload(lagos, alimosho, name=tricky, address="12A, Àjàò Rd. (opp. GTB)"),
        format="json",
    )
    assert created.status_code == 201
    assert created.data["name"] == tricky
    assert StoreLocation.objects.get(pk=created.data["id"]).name == tricky


def test_a_store_type_outside_the_choices_is_refused(client, lagos, alimosho):
    response = client.post(
        BASE, payload(lagos, alimosho, store_type="wholesale_partner"), format="json"
    )
    assert response.status_code == 400 and "store_type" in response.data


def test_a_pin_is_both_coordinates_or_neither(client, lagos, alimosho):
    """`maps_url` uses the pin only when BOTH are set, so a half-pin LOOKS placed in the
    admin and silently is not — the directions link falls back to the address text and
    nobody finds out until a customer lands on the wrong street."""
    half = client.post(BASE, payload(lagos, alimosho, latitude="6.601838"), format="json")
    assert half.status_code == 400
    assert "longitude" in half.data

    other_half = client.post(
        BASE, payload(lagos, alimosho, name="Two", longitude="3.351486"), format="json"
    )
    assert other_half.status_code == 400
    assert "latitude" in other_half.data

    whole = client.post(
        BASE, payload(lagos, alimosho, name="Three", latitude="6.601838",
                      longitude="3.351486"),
        format="json",
    )
    assert whole.status_code == 201, whole.data

    # Clearing one half on edit is the same half-pin by another route.
    cleared = client.patch(f"{BASE}{whole.data['id']}/", {"longitude": None}, format="json")
    assert cleared.status_code == 400 and "longitude" in cleared.data
    both_cleared = client.patch(
        f"{BASE}{whole.data['id']}/", {"latitude": None, "longitude": None}, format="json"
    )
    assert both_cleared.status_code == 200
    assert both_cleared.data["latitude"] is None


def test_a_pin_off_the_planet_is_refused(client, lagos, alimosho):
    """`DecimalField(max_digits=9)` stores 999.000000 without complaint; a latitude
    of 999 is not a place."""
    bad_lat = client.post(
        BASE, payload(lagos, alimosho, latitude="95", longitude="3.35"), format="json"
    )
    assert bad_lat.status_code == 400 and "latitude" in bad_lat.data
    bad_lng = client.post(
        BASE, payload(lagos, alimosho, latitude="6.6", longitude="-181"), format="json"
    )
    assert bad_lng.status_code == 400 and "longitude" in bad_lng.data


def test_the_rest_of_world_pseudo_market_is_not_a_place(client, lagos, alimosho):
    """"ZZ / International" prices orders from countries with no market of their
    own. It has no geography, so a shop cannot be in it."""
    response = client.post(BASE, payload(lagos, alimosho, country="ZZ"), format="json")
    assert response.status_code == 400 and "country" in response.data


def test_status_and_archived_at_cannot_be_set_by_the_client(client, lagos, alimosho):
    """Archiving is an endpoint, not a field. A writable `archived_at` would let a
    client bypass the DELETE route and the audit row it writes."""
    created = client.post(
        BASE, payload(lagos, alimosho, archived_at=timezone.now(), status="archived"),
        format="json",
    )
    assert created.status_code == 201
    assert created.data["archived_at"] is None and created.data["status"] == "active"


# --- update ----------------------------------------------------------------


def test_a_store_can_be_edited_and_deactivated_and_reactivated(client, lagos, alimosho):
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    url = f"{BASE}{created['id']}/"

    edited = client.patch(url, {"name": "Beauty Hub (New Site)"}, format="json")
    assert edited.status_code == 200 and edited.data["name"] == "Beauty Hub (New Site)"

    off = client.patch(url, {"is_active": False}, format="json")
    assert off.status_code == 200 and off.data["status"] == "inactive"
    # Still fully present in the admin — that is the whole point of the state.
    assert client.get(BASE).data["count"] == 1

    on = client.patch(url, {"is_active": True}, format="json")
    assert on.status_code == 200 and on.data["status"] == "active"


def test_a_patch_that_touches_one_field_is_still_judged_against_the_whole_row(
    client, lagos, alimosho
):
    """The classic partial-update hole: move the store to a Kano LGA while sending
    nothing else, and a validator that only looked at `attrs` would wave it through."""
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    kano_lga = region("Kano", "Dala")
    response = client.patch(
        f"{BASE}{created['id']}/", {"area_region": kano_lga.pk}, format="json"
    )
    assert response.status_code == 400 and "area_region" in response.data


# --- archive / restore -----------------------------------------------------


def test_delete_archives_rather_than_deleting(client, lagos, alimosho):
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    assert client.delete(f"{BASE}{created['id']}/").status_code == 204

    row = StoreLocation.objects.get(pk=created["id"])
    assert row.archived_at is not None and row.is_active is False

    # Gone from the default list, reachable when asked for.
    assert client.get(BASE).data["count"] == 0
    assert client.get(BASE, {"status": "archived"}).data["count"] == 1
    assert client.get(BASE, {"status": "all"}).data["count"] == 1


def test_an_archived_store_is_off_the_public_site_immediately(client, lagos, alimosho):
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    public = APIClient()
    assert public.get("/api/v1/stores/", {"country": "ng"}).data["count"] == 1
    client.delete(f"{BASE}{created['id']}/")
    assert public.get("/api/v1/stores/", {"country": "ng"}).data["count"] == 0
    assert public.get("/api/v1/stores/places/").data["items"] == []


def test_restore_brings_a_store_back_hidden_not_live(client, lagos, alimosho):
    """One more click before customers are sent to an address that was archived for
    a reason."""
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    client.delete(f"{BASE}{created['id']}/")

    restored = client.post(f"{BASE}{created['id']}/restore/")
    assert restored.status_code == 200
    assert restored.data["status"] == "inactive"
    assert APIClient().get("/api/v1/stores/", {"country": "ng"}).data["count"] == 0


def test_restoring_a_store_that_is_not_archived_is_refused(client, lagos, alimosho):
    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    assert client.post(f"{BASE}{created['id']}/restore/").status_code == 400


def test_restore_reports_the_collision_instead_of_500ing(client, lagos, alimosho):
    """Archive a shop, re-type it, then restore the original: the unique index
    refuses the restore. That has to be a sentence, not a stack trace."""
    first = client.post(BASE, payload(lagos, alimosho), format="json").data
    client.delete(f"{BASE}{first['id']}/")
    again = client.post(BASE, payload(lagos, alimosho, confirm_duplicate=True),
                        format="json")
    assert again.status_code == 201, again.data

    collision = client.post(f"{BASE}{first['id']}/restore/")
    assert collision.status_code == 409
    assert "archived" in collision.data["detail"]


# --- filtering, search, pagination -----------------------------------------


def test_the_filters_combine(client):
    store("Toke Ikeja", state="Lagos", area="Ikeja", store_type="toke_store",
          address="9 Allen Avenue")
    store("Beauty Hub", state="Lagos", area="Alimosho", store_type="distributor")
    store("Kano Stockist", state="Kano", area="Dala", store_type="distributor",
          address="4 Zoo Road")

    lagos_id = region("Lagos").pk
    alimosho_id = region("Lagos", "Alimosho").pk

    def names(**params):
        return sorted(r["name"] for r in client.get(BASE, params).data["results"])

    assert names(country="NG") == ["Beauty Hub", "Kano Stockist", "Toke Ikeja"]
    assert names(state_region=lagos_id) == ["Beauty Hub", "Toke Ikeja"]
    assert names(store_type="toke_store") == ["Toke Ikeja"]
    # The brief's example, all four at once.
    assert names(country="NG", state_region=lagos_id, area_region=alimosho_id,
                 store_type="distributor") == ["Beauty Hub"]
    assert names(country="NG", state_region=lagos_id, store_type="toke_store") == \
        ["Toke Ikeja"]


def test_search_covers_name_address_and_the_phone_as_it_is_printed(client):
    store("Beauty Hub", address="15 Example Street", phone="+2348023900964")
    store("Other Shop", address="2 Marina Road", phone="+2347000000001",
          area="Ikeja")

    def names(term):
        return sorted(r["name"] for r in client.get(BASE, {"q": term}).data["results"])

    assert names("beauty") == ["Beauty Hub"]
    assert names("marina") == ["Other Shop"]
    # Typed the way it is written on the shop door, against a value stored as E.164.
    assert names("0802 390 0964") == ["Beauty Hub"]
    assert names("8023900964") == ["Beauty Hub"]
    assert names("nothing here") == []


def test_the_status_filter_separates_the_three_states(client, lagos, alimosho):
    store("Live")
    store("Hidden", address="2 Second Street", is_active=False)
    store("Gone", address="3 Third Street", archived_at=timezone.now())

    def names(**params):
        return sorted(r["name"] for r in client.get(BASE, params).data["results"])

    assert names() == ["Hidden", "Live"]          # the default: not archived
    assert names(status="active") == ["Live"]
    assert names(status="inactive") == ["Hidden"]
    assert names(status="archived") == ["Gone"]
    assert names(status="all") == ["Gone", "Hidden", "Live"]


def test_the_list_is_paginated_on_a_stable_sort(client):
    """PageNumberPagination over a non-unique ORDER BY silently repeats and skips
    rows across page boundaries. Every one of these shares a name."""
    for i in range(30):
        store("Same Name", address=f"{i} Some Street")
    first = client.get(BASE).data
    second = client.get(BASE, {"page": 2}).data
    assert first["count"] == 30
    ids = [r["id"] for r in first["results"]] + [r["id"] for r in second["results"]]
    assert len(set(ids)) == 30, "a page boundary lost or repeated a row"


# --- audit -----------------------------------------------------------------


def test_every_write_leaves_an_audit_row_naming_who_did_it(client, lagos, alimosho):
    from apps.core.models import AuditLog

    created = client.post(BASE, payload(lagos, alimosho), format="json").data
    client.patch(f"{BASE}{created['id']}/", {"name": "Renamed"}, format="json")
    client.delete(f"{BASE}{created['id']}/")

    rows = AuditLog.objects.filter(model_label="stores.storelocation").order_by("id")
    assert [r.action for r in rows] == ["create", "partial_update", "destroy"]
    assert all(r.actor_email == "admin@toke.test" for r in rows)
    assert rows[1].changes["name"] == "Renamed"
    # A DELETE has no body, so the archived row is snapshotted into the trail or
    # the entry would prove only that *something* was archived.
    assert rows[2].changes["archived"]["name"] == "Renamed"
