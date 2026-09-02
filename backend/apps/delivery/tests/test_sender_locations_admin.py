"""Plan-34 slice 3: pickup-origin CRUD. The pin and the phone are validated hard
(both are load-bearing at GIG), and delete is refused once any shipment's origin
snapshot references the row — "this shop closed" is a deactivation."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.delivery.models import SenderLocation

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/sender-locations/"

ABUJA = {
    "name": "Kubwa (Abuja)", "phone": "+2347074800702",
    "address": "Shop 7, Lane 3, Gate 1 Phase 2 F01 Building Materials Market, Kubwa, FCT",
    "locality": "Kubwa", "latitude": "9.138000", "longitude": "7.322000",
}


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_requires_staff():
    assert APIClient().get(BASE).status_code in (401, 403)


def test_the_seeded_ogudu_row_lists_and_a_second_origin_can_be_added(client):
    assert [row["name"] for row in client.get(BASE).data] == ["Ogudu Mall (Lagos)"]

    response = client.post(BASE, ABUJA, format="json")
    assert response.status_code == 201, response.data
    assert SenderLocation.objects.filter(is_active=True).count() == 2


def test_phone_is_normalized_and_required(client):
    created = client.post(BASE, {**ABUJA, "phone": "+234 707 480 0702"}, format="json")
    assert created.status_code == 201
    assert created.data["phone"] == "+2347074800702"

    # A local-format number would need a country guess — refused, same rule as
    # everywhere else in the platform (core.phones).
    local = client.post(BASE, {**ABUJA, "name": "Two", "phone": "07074800702"}, format="json")
    assert local.status_code == 400 and "phone" in local.data

    missing = client.post(BASE, {**ABUJA, "name": "Three", "phone": ""}, format="json")
    assert missing.status_code == 400 and "phone" in missing.data


def test_the_pin_must_be_inside_nigeria(client):
    # London: a pasted-from-the-wrong-tab pin would re-price every quote and send
    # a rider to a coordinate GIG can't serve.
    response = client.post(
        BASE, {**ABUJA, "latitude": "51.507400", "longitude": "-0.127800"}, format="json"
    )
    assert response.status_code == 400
    assert "latitude" in response.data and "longitude" in response.data


def test_delete_is_refused_once_a_shipment_was_quoted_from_the_row(client):

    from apps.core.models import Country
    from apps.delivery.models import GigShipment
    from apps.orders.models import Order

    row = SenderLocation.objects.create(**{k: v for k, v in ABUJA.items()})
    ng = Country.objects.get(code="NG")
    order = Order.objects.create(
        number="TC-900200", email="del@x.com", country=ng, currency=ng.currency,
        status="processing", grand_total=Decimal("1000.00"),
    )
    GigShipment.objects.create(order=order, status="quoted", charged=Decimal("0.00"),
                               origin={"id": row.pk, "name": row.name})

    refused = client.delete(f"{BASE}{row.pk}/")
    assert refused.status_code == 400
    assert "deactivate" in refused.data["detail"]

    # Deactivation is the sanctioned move, and selection survives it (env fallback).
    off = client.patch(f"{BASE}{row.pk}/", {"is_active": False}, format="json")
    assert off.status_code == 200 and off.data["is_active"] is False


def test_state_and_lga_are_stored_and_returned_but_never_route(client):
    """Plan-35: display-only filing labels. The round-trip proves they persist; the
    routing assertion proves a label can never move a quote — selection stays pure
    haversine over the pin."""
    created = client.post(
        BASE, {**ABUJA, "state": "FCT", "lga": "Bwari"}, format="json"
    )
    assert created.status_code == 201
    assert created.data["state"] == "FCT" and created.data["lga"] == "Bwari"

    listed = next(r for r in client.get(BASE).data if r["id"] == created.data["id"])
    assert listed["state"] == "FCT" and listed["lga"] == "Bwari"

    # A wildly wrong label changes nothing about selection: the pin routes.
    from apps.delivery.gig.origins import select_origin

    client.patch(f"{BASE}{created.data['id']}/", {"state": "Lagos", "lga": "Ikeja"},
                 format="json")
    near_abuja = select_origin(9.10, 7.30)
    assert near_abuja.id == created.data["id"]  # still chosen by distance, not label


def test_a_never_used_row_can_be_deleted(client):
    row = SenderLocation.objects.create(**{**ABUJA, "name": "Typo Row"})
    assert client.delete(f"{BASE}{row.pk}/").status_code == 204
    assert not SenderLocation.objects.filter(pk=row.pk).exists()
