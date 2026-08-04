"""Centre sync + nearest-centres helper (Plan-32b slice 1): upsert, deactivate-
never-delete, string-or-number coordinates, distance sorting, and the seeded dark
pickup option."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.delivery.gig import client
from apps.delivery.gig.centres import haversine_km, nearest_centres, sync_gig_centres
from apps.delivery.models import DeliveryOption, GigCentre

BASE = "https://gig.test"
SETTINGS = dict(GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw")

pytestmark = pytest.mark.django_db


def _envelope(rows):
    return {"message": "Success", "apiId": "c-1", "status": 200, "data": {"data": rows, "count": len(rows)}}


@pytest.fixture(autouse=True)
def _token():
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)
    yield
    cache.delete(client.TOKEN_CACHE_KEY)


def _mock(stations, centres_by_station):
    respx.get(f"{BASE}/localstations/get").mock(
        return_value=httpx.Response(200, json=_envelope(stations))
    )

    def _answer(request):
        sid = int(request.url.params["StationId"])
        return httpx.Response(200, json=_envelope(centres_by_station.get(sid, [])))

    respx.get(f"{BASE}/serviceCentresByStation").mock(side_effect=_answer)


@override_settings(**SETTINGS)
@respx.mock
def test_sync_upserts_handles_string_coords_and_deactivates_vanished():
    _mock(
        [{"StationId": 4, "StationName": "LAGOS"}],
        {4: [
            {"ServiceCentreId": 540, "Name": "Alausa", "Address": "Plot Y, Alausa Ikeja",
             "Latitude": "6.6146", "Longitude": 3.3568},
            {"ServiceCentreId": 541, "Name": "Gbagada", "Address": "1 Road, Gbagada",
             "Latitude": 6.556, "Longitude": "3.3888"},
        ]},
    )
    counts = sync_gig_centres()
    assert counts["created"] == 2
    alausa = GigCentre.objects.get(gig_centre_id=540)
    assert alausa.latitude == Decimal("6.614600")  # string coord taken

    # Next sweep: Gbagada vanishes -> deactivated, never deleted.
    respx.reset()
    _mock([{"StationId": 4}], {4: [
        {"ServiceCentreId": 540, "Name": "Alausa", "Address": "Plot Y, Alausa Ikeja",
         "Latitude": "6.6146", "Longitude": 3.3568},
    ]})
    counts = sync_gig_centres()
    assert counts["deactivated"] == 1
    assert not GigCentre.objects.get(gig_centre_id=541).is_active
    assert GigCentre.objects.get(gig_centre_id=540).is_active


def test_nearest_centres_sorts_by_distance_and_skips_coordless(db):
    from django.utils import timezone

    now = timezone.now()
    GigCentre.objects.create(gig_centre_id=1, gig_station_id=4, name="Ikeja",
                             latitude="6.6186", longitude="3.3426", synced_at=now)
    GigCentre.objects.create(gig_centre_id=2, gig_station_id=4, name="Lekki",
                             latitude="6.4478", longitude="3.4723", synced_at=now)
    GigCentre.objects.create(gig_centre_id=3, gig_station_id=4, name="No coords", synced_at=now)
    GigCentre.objects.create(gig_centre_id=4, gig_station_id=1, name="Aba (inactive)",
                             latitude="5.1", longitude="7.3", is_active=False, synced_at=now)

    # From Ogba (near Ikeja): Ikeja first, Lekki second; coordless and inactive absent.
    result = nearest_centres(6.6280, 3.3410)
    assert [c["name"] for c in result] == ["Ikeja", "Lekki"]
    assert result[0]["distance_km"] < result[1]["distance_km"]
    # Haversine sanity: Ikeja->Lekki is ~24 km as measured on a map.
    assert 20 < haversine_km(6.6186, 3.3426, 6.4478, 3.4723) < 30


def test_the_pickup_option_is_seeded_dark_and_the_home_row_is_named(db):
    home = DeliveryOption.objects.get(carrier_code="gig", carrier_service="home")
    pickup = DeliveryOption.objects.get(carrier_code="gig", carrier_service="pickup")
    assert home.name == "Door Delivery (GIG)"
    assert pickup.is_active is False  # dark until the 32b go-live addendum
    assert list(pickup.countries.values_list("code", flat=True)) == ["NG"]


def test_the_centre_sync_is_scheduled():
    from django.conf import settings as dj

    tasks = {entry["task"] for entry in dj.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.delivery.tasks.sync_gig_centres_task" in tasks
