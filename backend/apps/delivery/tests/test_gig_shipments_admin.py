"""Plan-35 slice 1: the deliveries table — GET /admin/gig-shipments/.

Rows are composed ENTIRELY from snapshots (origin, centre, the order's address),
so the assertions here build shipments whose snapshots disagree with today's
tables on purpose: history must render as it happened. The origin filter's
special case — 0 matches BOTH id-0 snapshots and the empty pre-Plan-34 dict —
is the one that keeps old shipments visible, and it gets its own test.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country
from apps.delivery.models import GigShipment
from apps.orders.models import Order

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/gig-shipments/"

ADDRESS = {
    "first_name": "Bola", "last_name": "Ade", "phone": "+2348012345678",
    "line1": "12 Allen Ave", "line2": "", "country_code": "NG",
    "state": "Lagos", "area": "Ikeja", "postcode": "",
    "latitude": 6.6018, "longitude": 3.3515,
}


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _order(number: str, placed_at=None, address=ADDRESS) -> Order:
    ng = Country.objects.get(code="NG")
    return Order.objects.create(
        number=number, email="c@x.com", country=ng, currency=ng.currency,
        status="processing", grand_total=Decimal("5000.00"),
        shipping_address=dict(address),
        placed_at=placed_at or timezone.now(),
    )


def _shipment(number: str, *, placed_at=None, **fields) -> GigShipment:
    defaults = {"status": "quoted", "charged": Decimal("0.00")}
    defaults.update(fields)
    return GigShipment.objects.create(order=_order(number, placed_at), **defaults)


def test_requires_staff():
    assert APIClient().get(BASE).status_code in (401, 403)


def test_rows_compose_from_snapshots_not_live_tables(client):
    _shipment(
        "TC-910001",
        status="created", waybill="WB123", cost=Decimal("3532.97"),
        charged=Decimal("3532.97"),
        origin={"id": 7, "name": "Kubwa (Abuja)", "phone": "+2347074800702"},
        last_scan={"Status": "In transit"},
    )
    # A pickup shipment with the empty pre-Plan-34 origin snapshot.
    _shipment(
        "TC-910002",
        centre={"id": 42, "name": "Ikeja Service Centre", "address": "1 Oba Akran"},
    )

    rows = client.get(BASE).data["results"]
    by_number = {row["order_number"]: row for row in rows}

    door = by_number["TC-910001"]
    assert door["origin"] == {"id": 7, "name": "Kubwa (Abuja)"}  # no phone leak needed
    assert door["service"] == "door"
    assert door["destination"] == "Ikeja, Lagos"
    assert door["customer_name"] == "Bola Ade"
    assert door["customer_phone"] == "+2348012345678"
    assert door["waybill"] == "WB123"
    assert door["cost"] == "3532.97" and door["charged"] == "3532.97"
    assert door["currency"] == "NGN"
    assert door["last_scan"] == {"Status": "In transit"}

    pickup = by_number["TC-910002"]
    # Empty snapshot = the built-in env origin, labelled so, never resolved
    # against today's settings.
    assert pickup["origin"] == {"id": 0, "name": "Ogudu (built-in)"}
    assert pickup["service"] == "pickup"
    assert pickup["destination"] == "Ikeja Service Centre"


def test_origin_filter_and_the_zero_special_case(client):
    _shipment("TC-910010", origin={"id": 7, "name": "Kubwa (Abuja)"})
    _shipment("TC-910011", origin={})                       # pre-Plan-34
    _shipment("TC-910012", origin={"id": 0, "name": "Ogudu Mall (Lagos)"})  # env fallback

    def numbers(params=""):
        return {r["order_number"] for r in client.get(f"{BASE}{params}").data["results"]}

    assert numbers("?origin=7") == {"TC-910010"}
    # 0 must match BOTH shapes of "the built-in origin" or history vanishes.
    assert numbers("?origin=0") == {"TC-910011", "TC-910012"}
    assert numbers("?origin=999") == set()
    assert numbers("?origin=garbage") == set()
    assert numbers() == {"TC-910010", "TC-910011", "TC-910012"}


def test_status_service_and_date_filters(client):
    old = timezone.now() - timedelta(days=30)
    _shipment("TC-910020", status="delivered", placed_at=old,
              centre={"id": 1, "name": "Centre A"})
    _shipment("TC-910021", status="quoted")

    def numbers(params):
        return {r["order_number"] for r in client.get(f"{BASE}{params}").data["results"]}

    assert numbers("?status=delivered") == {"TC-910020"}
    assert numbers("?service=pickup") == {"TC-910020"}
    assert numbers("?service=door") == {"TC-910021"}
    from urllib.parse import quote

    cutoff = quote((timezone.now() - timedelta(days=1)).isoformat())
    assert numbers(f"?placed_after={cutoff}") == {"TC-910021"}
    assert numbers(f"?placed_before={cutoff}") == {"TC-910020"}
    # Garbage dates match nothing — never a 500, never silently everything.
    assert numbers("?placed_after=not-a-date") == set()


def test_paginated_and_newest_first(client):
    now = timezone.now()
    for i in range(30):
        _shipment(f"TC-9101{i:02d}", placed_at=now - timedelta(minutes=i))

    response = client.get(BASE).data
    # Paginated — this table grows with every order; a raw list would be one-call
    # bulk PII egress.
    assert response["count"] == 30
    assert len(response["results"]) == 24  # global PAGE_SIZE
    assert [r["order_number"] for r in response["results"][:3]] == [
        "TC-910100", "TC-910101", "TC-910102"  # newest first
    ]
    assert client.get(f"{BASE}?page=2").data["results"]
