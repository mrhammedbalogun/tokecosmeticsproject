"""The customer-facing half of the store locator, over real HTTP.

The property under test throughout is the one the design rests on: **every option
the cascade offers leads to at least one store, and nothing hidden ever leaks.**
"""

import pytest
from rest_framework.test import APIClient

from apps.stores.factories import store
from apps.stores.models import STORE_TYPE_DISTRIBUTOR, STORE_TYPE_TOKE

pytestmark = pytest.mark.django_db

PLACES = "/api/v1/stores/places/"
STORES = "/api/v1/stores/"


@pytest.fixture
def client():
    return APIClient()


# --- the cascade -----------------------------------------------------------


def test_an_empty_directory_offers_no_countries(client):
    """The launch state. It must be an empty list and a 200, not a 404 and not a
    list of every market — the storefront renders "the directory is being
    compiled" off exactly this."""
    response = client.get(PLACES)
    assert response.status_code == 200
    assert response.data == {"level": "country", "parent": None, "items": []}


def test_only_countries_states_and_areas_that_hold_a_store_are_offered(client):
    store("Beauty Hub", state="Lagos", area="Alimosho")

    countries = client.get(PLACES).data
    assert [c["slug"] for c in countries["items"]] == ["nigeria"]
    assert countries["items"][0]["code"] == "NG"
    assert countries["items"][0]["store_count"] == 1
    # The labels ride along so the storefront can say "State" for NG and
    # "Province" for CA without a second request.
    assert countries["items"][0]["state_label"] == "State"

    states = client.get(PLACES, {"country": "ng"}).data
    assert states["level"] == "state"
    assert [s["slug"] for s in states["items"]] == ["lagos"]
    assert states["items"][0]["has_children"] is True  # so the UI knows to ask for an LGA

    areas = client.get(PLACES, {"country": "ng", "state": "lagos"}).data
    assert areas["level"] == "area"
    assert [a["slug"] for a in areas["items"]] == ["alimosho"]
    # Nigeria has 57 Lagos LGAs and 774 in total. The cascade offered one.


def test_a_country_can_be_named_by_slug_or_by_iso_code(client):
    store(state="Lagos", area="Alimosho")
    for spelling in ("ng", "NG", "nigeria", "Nigeria"):
        response = client.get(PLACES, {"country": spelling})
        assert response.status_code == 200, spelling
        assert [s["slug"] for s in response.data["items"]] == ["lagos"]


def test_hidden_stores_are_invisible_to_the_cascade_and_the_results(client):
    """The three states of a row, from the outside. Inactive and archived rows are
    fully present in the admin and must not exist at all out here — including as a
    dropdown option, which would strand a customer on an empty result."""
    store("Hidden", state="Kano", area="Dala", is_active=False)
    from django.utils import timezone
    store("Gone", state="Oyo", area="Ibadan North", archived_at=timezone.now())
    store("Open", state="Lagos", area="Alimosho")

    states = client.get(PLACES, {"country": "ng"}).data
    assert [s["slug"] for s in states["items"]] == ["lagos"]

    results = client.get(STORES, {"country": "ng"}).data
    assert [r["name"] for r in results["results"]] == ["Open"]


def test_an_unknown_place_is_a_404_with_a_customer_safe_message(client):
    store(state="Lagos", area="Alimosho")
    missing = client.get(PLACES, {"country": "atlantis"})
    assert missing.status_code == 404
    assert "atlantis" not in str(missing.data).lower()  # never echo the input back

    wrong_state = client.get(PLACES, {"country": "ng", "state": "narnia"})
    assert wrong_state.status_code == 404


# --- the results -----------------------------------------------------------


def test_results_put_our_own_counters_first_then_alphabetical(client):
    store("Zenith Beauty", store_type=STORE_TYPE_DISTRIBUTOR)
    store("Ada Cosmetics", store_type=STORE_TYPE_DISTRIBUTOR, address="2 Other Street")
    store("Toke Ogudu Store", store_type=STORE_TYPE_TOKE, address="3 Third Street")

    names = [
        row["name"]
        for row in client.get(
            STORES, {"country": "ng", "state": "lagos", "area": "alimosho"}
        ).data["results"]
    ]
    assert names == ["Toke Ogudu Store", "Ada Cosmetics", "Zenith Beauty"]


def test_a_store_card_carries_everything_it_renders_and_nothing_it_should_not(client):
    store(
        "Toke Ogudu Store",
        store_type=STORE_TYPE_TOKE,
        address="12 Hassan Balogun Street, Isheri-Olofin, Ikotun",
        phone="+2348023900964",
        whatsapp_phone="+2348023900965",
        opening_hours="Mon–Sat, 9am – 7pm",
        notes="Ask for Chidi. Keys with the security post.",
    )
    row = client.get(
        STORES, {"country": "ng", "state": "lagos", "area": "alimosho"},
        headers={"X-Country": "NG"},
    ).data["results"][0]

    assert row["store_type_label"] == "Toke Store"
    assert row["area"] == "Alimosho" and row["state"] == "Lagos"
    # The DIALLABLE form and the READABLE form are both present and different.
    assert row["phone"] == "+2348023900964"
    assert row["phone_display"] == "0802 390 0964"
    assert row["whatsapp_url"] == "https://wa.me/2348023900965"
    assert row["directions_url"].startswith("https://www.google.com/maps/search/")
    assert "Hassan+Balogun" in row["directions_url"]
    # Staff-only columns never cross the boundary.
    assert "notes" not in row
    assert "name_key" not in row and "address_key" not in row


def test_a_reader_abroad_gets_the_international_form_of_the_number(client):
    store(phone="+2348023900964")
    row = client.get(
        STORES, {"country": "ng"}, headers={"X-Country": "GB"}
    ).data["results"][0]
    assert row["phone_display"] == "+234 802 390 0964"
    assert row["phone"] == "+2348023900964", "the dialled value never changes"


def test_directions_prefer_the_pin_when_there_is_one(client):
    store(latitude="6.586000", longitude="3.263000")
    row = client.get(STORES, {"country": "ng"}).data["results"][0]
    assert "6.586000%2C3.263000" in row["directions_url"]


def test_a_state_query_returns_every_store_in_the_state(client):
    """The shared-link fallback: an LGA that has emptied out still leaves the
    state-level answer useful rather than blank."""
    store("A", state="Lagos", area="Alimosho")
    store("B", state="Lagos", area="Ikeja", address="9 Allen Avenue")
    assert len(client.get(STORES, {"country": "ng", "state": "lagos"}).data["results"]) == 2


def test_a_place_with_no_stores_left_answers_an_empty_list_not_an_error(client):
    """Edge case 4 and 20 at once: a bookmarked link to an LGA whose last store was
    archived. The place still resolves — it is a real LGA — and the answer is zero
    rows, which is what the empty state renders."""
    store(state="Lagos", area="Ikeja", address="9 Allen Avenue")
    response = client.get(STORES, {"country": "ng", "state": "lagos", "area": "alimosho"})
    assert response.status_code == 200
    assert response.data["count"] == 0 and response.data["results"] == []


def test_results_are_paginated_rather_than_capped(client):
    """A silent cap would read as "that is all of them". 30 rows in one LGA is not
    a realistic Alimosho, and it is exactly the shape the brief says not to assume
    away."""
    for i in range(30):
        store(f"Shop {i:02d}", address=f"{i} Some Street")
    first = client.get(STORES, {"country": "ng", "state": "lagos", "area": "alimosho"}).data
    assert first["count"] == 30
    assert len(first["results"]) == 24 and first["next"] is not None
    second = client.get(
        STORES, {"country": "ng", "state": "lagos", "area": "alimosho", "page": 2}
    ).data
    assert len(second["results"]) == 6


def test_the_endpoints_are_anonymous_and_accept_no_credentials(client):
    """A public page must not have an authenticated variant — that is how a
    "public" endpoint quietly starts leaking staff-only fields to a signed-in
    reader. Both views declare `authentication_classes = []`."""
    from apps.stores.views import StoreListView, StorePlacesView

    assert StorePlacesView.authentication_classes == []
    assert StoreListView.authentication_classes == []


# --- countries with no LGA tree (GB/US/CA) ---------------------------------


def test_a_country_whose_states_have_no_areas_stops_the_cascade_at_the_state(client):
    """GB/US/CA were seeded with level-1 regions only. The cascade must say so
    (`has_children: false`) rather than offering a third dropdown that can only
    ever be empty."""
    store("London Stockist", state="England", area=None, country_code="GB",
          city_text="London", address="4 Regent Street")

    states = client.get(PLACES, {"country": "gb"}).data
    assert [s["slug"] for s in states["items"]] == ["england"]
    assert states["items"][0]["has_children"] is False

    areas = client.get(PLACES, {"country": "gb", "state": "england"}).data
    assert areas["items"] == []

    row = client.get(STORES, {"country": "gb", "state": "england"}).data["results"][0]
    assert row["city"] == "London" and row["area"] == ""
