"""Sender-origin selection (Plan-34 slice 1): nearest active row wins, ties are
deterministic, inactive rows never ship, and an empty table degrades to the
`GIG_SENDER_*` settings — byte-for-byte the pre-Plan-34 behaviour."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.core.models import Country, Currency, Region
from apps.delivery.gig.origins import SETTINGS_ORIGIN_ID, select_origin, settings_origin
from apps.delivery.gig.quotes import quote_home_delivery
from apps.delivery.models import GigLga, SenderLocation

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_slate():
    # Migration 0014 seeds the Ogudu row; these tests build their own worlds.
    SenderLocation.objects.all().delete()

OGUDU = dict(name="Ogudu Mall (Lagos)", phone="+2347074800702",
             address="Shop No 1, Ogudu Mall, Kosofe, Ogudu, Lagos", locality="Ogudu",
             latitude="6.576522", longitude="3.389387")
ABUJA = dict(name="Kubwa (Abuja)", phone="+2347074800702",
             address="Shop 7, Lane 3, Building Materials Market, Kubwa, FCT",
             locality="Kubwa", latitude="9.138000", longitude="7.322000")

SENDER_SETTINGS = dict(
    GIG_SENDER_NAME="Toke Cosmetics", GIG_SENDER_PHONE="+2340000000000",
    GIG_SENDER_ADDRESS="Env St, Lagos", GIG_SENDER_LOCALITY="Env",
    GIG_SENDER_LATITUDE=6.5560, GIG_SENDER_LONGITUDE=3.3888,
)

IKEJA = (6.6018, 3.3515)      # Lagos-side receiver
GWARINPA = (9.1108, 7.4165)   # Abuja-side receiver


def test_nearest_origin_wins_per_receiver():
    ogudu = SenderLocation.objects.create(**OGUDU)
    abuja = SenderLocation.objects.create(**ABUJA)
    assert select_origin(*IKEJA).id == ogudu.pk
    assert select_origin(*GWARINPA).id == abuja.pk


def test_inactive_rows_are_skipped():
    SenderLocation.objects.create(**{**ABUJA, "is_active": False})
    ogudu = SenderLocation.objects.create(**OGUDU)
    # Abuja is far closer to Gwarinpa, but it's off — Lagos ships it.
    assert select_origin(*GWARINPA).id == ogudu.pk


@override_settings(**SENDER_SETTINGS)
def test_empty_table_falls_back_to_settings():
    origin = select_origin(*IKEJA)
    assert origin.id == SETTINGS_ORIGIN_ID
    assert origin == settings_origin()
    assert origin.address == "Env St, Lagos"
    assert origin.latitude == 6.5560


@override_settings(**SENDER_SETTINGS)
def test_all_rows_inactive_falls_back_to_settings():
    SenderLocation.objects.create(**{**OGUDU, "is_active": False})
    assert select_origin(*IKEJA).id == SETTINGS_ORIGIN_ID


def test_tie_breaks_to_lowest_pk():
    first = SenderLocation.objects.create(**OGUDU)
    SenderLocation.objects.create(**{**ABUJA, "latitude": OGUDU["latitude"],
                                        "longitude": OGUDU["longitude"]})
    assert select_origin(*IKEJA).id == first.pk


def test_snapshot_shape_is_the_capture_contract():
    SenderLocation.objects.create(**OGUDU)
    snap = select_origin(*IKEJA).as_snapshot()
    assert set(snap) == {"id", "name", "phone", "address", "locality", "latitude", "longitude"}
    assert isinstance(snap["latitude"], float) and isinstance(snap["longitude"], float)
    assert snap["name"] == "Ogudu Mall (Lagos)"


# --- Slice 2: the origin flows through quoting --------------------------------------

BASE = "https://gig.test"
GIG_SETTINGS = dict(
    GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw", GIG_VEHICLE_TYPE=1,
    **SENDER_SETTINGS,
)


class PinnedAddress:
    """An address with a door pin — receiver_point() prefers it, which lets one
    covered region host receivers on either side of the country."""

    def __init__(self, region, lat, lng):
        self.country_code = "NG"
        self.state_region = region.parent
        self.area_region = region
        self.latitude, self.longitude = lat, lng


@pytest.fixture
def covered_ikeja():
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria", "currency": ngn,
                                                       "is_default": True})
    ikeja = Region.objects.get(country_code="NG", level="area", name="Ikeja",
                               parent__name="Lagos")
    Region.objects.filter(pk=ikeja.pk).update(latitude="6.618570", longitude="3.342590")
    ikeja.refresh_from_db()
    GigLga.objects.create(state_name="Lagos", lga_name="Ikeja", gig_state_id=24,
                          is_active=True, home_delivery=True, region=ikeja,
                          synced_at=timezone.now())
    return ikeja


def _quote_envelope(grand_total):
    return {"message": "Success", "apiId": "quote-api-id", "status": 200,
            "data": {"data": {"GrandTotal": grand_total}}}


@override_settings(**GIG_SETTINGS)
@respx.mock
def test_quote_ships_the_selected_origins_coordinates_and_keys_the_cache_by_origin(covered_ikeja):
    import json as jsonlib

    cache.clear()
    cache.set("gig:access-token", "jwt", 300)
    ogudu = SenderLocation.objects.create(**OGUDU)
    abuja = SenderLocation.objects.create(**ABUJA)
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(4175.2))
    )

    lagos_quote = quote_home_delivery(PinnedAddress(covered_ikeja, *IKEJA), 500,
                                      declared_value=Decimal("15000.00"))
    abuja_quote = quote_home_delivery(PinnedAddress(covered_ikeja, *GWARINPA), 500,
                                      declared_value=Decimal("15000.00"))

    # Different origins → different cache keys → two live calls, no cross-poisoning.
    assert route.call_count == 2
    assert lagos_quote.cache_key != abuja_quote.cache_key
    assert f":{ogudu.pk}:" in lagos_quote.cache_key
    assert f":{abuja.pk}:" in abuja_quote.cache_key

    first = jsonlib.loads(route.calls[0].request.content)["SenderLocation"]
    second = jsonlib.loads(route.calls[1].request.content)["SenderLocation"]
    assert first == {"Latitude": 6.576522, "Longitude": 3.389387}
    assert second == {"Latitude": 9.138, "Longitude": 7.322}

    # The cached payload carries the origin snapshot placement will lift (ruling 3).
    cached = cache.get(abuja_quote.cache_key)
    assert cached["origin"]["id"] == abuja.pk
    assert cached["origin"]["name"] == "Kubwa (Abuja)"


@override_settings(**GIG_SETTINGS)
@respx.mock
def test_quote_with_no_rows_sends_the_env_origin_with_id_zero(covered_ikeja):
    import json as jsonlib

    cache.clear()
    cache.set("gig:access-token", "jwt", 300)
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(4175.2))
    )
    quote = quote_home_delivery(PinnedAddress(covered_ikeja, *IKEJA), 500,
                                declared_value=Decimal("15000.00"))
    assert ":0:" in quote.cache_key
    body = jsonlib.loads(route.calls[0].request.content)
    assert body["SenderLocation"] == {"Latitude": 6.5560, "Longitude": 3.3888}
    assert cache.get(quote.cache_key)["origin"]["id"] == SETTINGS_ORIGIN_ID
