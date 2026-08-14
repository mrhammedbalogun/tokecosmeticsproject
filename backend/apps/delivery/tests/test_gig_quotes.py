"""The checkout quote layer (Plan-32a slice 3): GIG appears priced where the
whole precondition chain holds, is OMITTED on any failure (coverage, centroid,
outage, malformed price), and never slows checkout past its one-attempt budget.
Manual options pass through untouched in every case."""
from collections import namedtuple
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.core.models import Country, Currency, Region
from apps.delivery.carriers import priced_options_for_address
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.gig import client
from apps.delivery.gig.quotes import _cache_key
from apps.delivery.models import DeliveryOption, GigLga

BASE = "https://gig.test"
SETTINGS = dict(
    GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw",
    GIG_SENDER_LATITUDE=6.556, GIG_SENDER_LONGITUDE=3.3888, GIG_VEHICLE_TYPE=1,
)

pytestmark = pytest.mark.django_db

FakeVariant = namedtuple("FakeVariant", "weight_grams")


def _seeded_origin_id() -> int:
    # Migration 0014 seeds the Ogudu sender row (Plan-34); with one active row it
    # is always the selected origin, whatever the receiver.
    from apps.delivery.models import SenderLocation
    return SenderLocation.objects.get(is_active=True).pk


class FakeAddress:
    def __init__(self, country_code="NG", state_region=None, area_region=None):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region


def _quote_envelope(grand_total):
    return {
        "message": "Success", "apiId": "quote-api-id", "status": 200,
        "data": {"data": {"GrandTotal": grand_total, "DeliveryPrice": grand_total - 1000,
                          "SurchargeFee": 1000, "Discount": 0}},
    }


@pytest.fixture
def ng():
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    country, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return country


@pytest.fixture
def covered_ikeja(ng):
    """Ikeja with centroid + active home-delivery GigLga: fully covered."""
    from django.utils import timezone

    ikeja = Region.objects.get(country_code="NG", level="area", name="Ikeja", parent__name="Lagos")
    Region.objects.filter(pk=ikeja.pk).update(latitude="6.618570", longitude="3.342590")
    ikeja.refresh_from_db()
    GigLga.objects.create(
        state_name="Lagos", lga_name="Ikeja", gig_state_id=24, is_active=True,
        home_delivery=True, region=ikeja, synced_at=timezone.now(),
    )
    return ikeja


@pytest.fixture
def gig_option(ng):
    option = DeliveryOption.objects.get(carrier_code="gig", carrier_service="home")  # seeded by migration 0006
    option.is_active = True
    option.save(update_fields=["is_active"])
    return option


@pytest.fixture
def flat_option(ng):
    option = DeliveryOptionFactory(name="Nationwide Delivery", price="3500.00", currency=ng.currency)
    option.countries.add(ng)
    return option


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _token():
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)


def _options(address, ng, weight_g=500):
    lines = [(FakeVariant(weight_grams=weight_g), 1)]
    return priced_options_for_address(address, lines, Decimal("15000.00"), ng)


@override_settings(**SETTINGS)
@respx.mock
def test_covered_lga_gets_a_priced_gig_option_and_flat_options_pass_through(
    ng, covered_ikeja, gig_option, flat_option
):
    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(4175.2)))
    address = FakeAddress(area_region=covered_ikeja, state_region=covered_ikeja.parent)
    options = _options(address, ng)
    by_name = {o["name"]: o for o in options}
    assert by_name["Nationwide Delivery"]["price"] == "3500.00"
    gig = by_name["Door Delivery (GIG)"]
    assert gig["price"] == "4175.20"
    assert gig["carrier_quote_key"] == _cache_key(_seeded_origin_id(), covered_ikeja.id, 500)
    # The customer-facing dict never carries GIG's breakdown (our discount rank).
    assert "carrier_quote" not in gig and "breakdown" not in gig


@override_settings(**SETTINGS)
@respx.mock
def test_second_call_is_served_from_cache(ng, covered_ikeja, gig_option):
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(4175.2))
    )
    address = FakeAddress(area_region=covered_ikeja, state_region=covered_ikeja.parent)
    first = _options(address, ng)
    second = _options(address, ng)
    assert route.call_count == 1
    assert [o["price"] for o in first] == [o["price"] for o in second]
    # The cached payload keeps the full breakdown for slice 4's placement snapshot.
    cached = cache.get(_cache_key(_seeded_origin_id(), covered_ikeja.id, 500))
    assert cached["breakdown"]["SurchargeFee"] == 1000
    assert cached["api_id"] == "quote-api-id"


@override_settings(**SETTINGS)
@respx.mock
def test_gig_is_omitted_not_erroring_when_the_chain_breaks(ng, covered_ikeja, gig_option):
    address = FakeAddress(area_region=covered_ikeja, state_region=covered_ikeja.parent)

    # Outage: connection refused -> omitted, no exception, checkout carries on.
    respx.post(f"{BASE}/price/v3").mock(side_effect=httpx.ConnectError("down"))
    assert all(o["carrier_code"] != "gig" for o in _options(address, ng))

    # Read timeout: one attempt only (budget), omitted.
    route = respx.post(f"{BASE}/price/v3").mock(side_effect=httpx.ReadTimeout("slow"))
    before = route.call_count
    assert all(o["carrier_code"] != "gig" for o in _options(address, ng))
    assert route.call_count == before + 1

    # Malformed price payload: omitted.
    respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json={"message": "Success", "apiId": "x", "status": 200, "data": {}})
    )
    assert all(o["carrier_code"] != "gig" for o in _options(address, ng))


@override_settings(**SETTINGS)
@respx.mock
def test_no_coverage_no_centroid_or_no_home_delivery_means_no_gig(ng, gig_option):
    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(4175.2)))
    from django.utils import timezone

    epe = Region.objects.get(country_code="NG", level="area", name="Epe", parent__name="Lagos")

    # Covered LGA but no centroid.
    GigLga.objects.create(state_name="Lagos", lga_name="Epe", gig_state_id=24, is_active=True,
                          home_delivery=True, region=epe, synced_at=timezone.now())
    address = FakeAddress(area_region=epe, state_region=epe.parent)
    assert all(o["carrier_code"] != "gig" for o in _options(address, ng))

    # Centroid but the GigLga is centre-pickup only (home_delivery=False).
    Region.objects.filter(pk=epe.pk).update(latitude="6.6", longitude="3.98")
    epe.refresh_from_db()
    GigLga.objects.filter(lga_name="Epe").update(home_delivery=False)
    address = FakeAddress(area_region=epe, state_region=epe.parent)
    assert all(o["carrier_code"] != "gig" for o in _options(address, ng))


@override_settings(**SETTINGS)
@respx.mock
def test_free_over_zeroes_the_charge_but_not_the_cached_cost(ng, covered_ikeja, gig_option):
    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(4175.2)))
    gig_option.free_over = Decimal("10000.00")
    gig_option.save(update_fields=["free_over"])
    address = FakeAddress(area_region=covered_ikeja, state_region=covered_ikeja.parent)
    options = _options(address, ng)  # subtotal 15000 >= 10000
    gig = next(o for o in options if o["carrier_code"] == "gig")
    assert gig["price"] == "0.00"  # customer pays nothing...
    cached = cache.get(_cache_key(_seeded_origin_id(), covered_ikeja.id, 500))
    assert cached["price"] == "4175.20"  # ...but what GIG will cost us is unchanged


# --- Plan-32b slice 2: pickup quoting, the pin, and the centres endpoint -------------


@pytest.fixture
def pickup_world(ng):
    """Epe: active GIG LGA WITHOUT home delivery, centroid set, one nearby centre."""
    from django.utils import timezone

    epe = Region.objects.get(country_code="NG", level="area", name="Epe", parent__name="Lagos")
    Region.objects.filter(pk=epe.pk).update(latitude="6.584200", longitude="3.983500")
    epe.refresh_from_db()
    GigLga.objects.create(state_name="Lagos", lga_name="Epe", gig_state_id=24, is_active=True,
                          home_delivery=False, region=epe, synced_at=timezone.now())
    from apps.delivery.models import GigCentre

    centre = GigCentre.objects.create(gig_centre_id=901, gig_station_id=4, name="EPE CENTRE",
                                      address="1 Epe Rd", latitude="6.5900", longitude="3.9800",
                                      synced_at=timezone.now())
    GigCentre.objects.create(gig_centre_id=902, gig_station_id=4, name="IKEJA FAR",
                             address="Far", latitude="6.6186", longitude="3.3426",
                             synced_at=timezone.now())
    pickup = DeliveryOption.objects.get(carrier_code="gig", carrier_service="pickup")
    pickup.is_active = True
    pickup.save(update_fields=["is_active"])
    return epe, centre


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_only_lga_offers_pickup_priced_to_the_nearest_centre(ng, gig_option, pickup_world):
    epe, centre = pickup_world
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(2500.0))
    )
    address = FakeAddress(area_region=epe, state_region=epe.parent)
    options = _options(address, ng)
    services = {o.get("carrier_service") for o in options if o["carrier_code"] == "gig"}
    assert services == {"pickup"}  # home omitted: the LGA has no home delivery
    import json as jsonlib

    body = jsonlib.loads(route.calls[0].request.content)
    assert body["PickUpOptions"] == 1
    # Priced to the NEAREST centre's own coordinates (Epe, not Ikeja).
    assert body["ReceiverLocation"] == {"Latitude": 6.59, "Longitude": 3.98}


@override_settings(**SETTINGS)
@respx.mock
def test_the_pin_overrides_the_centroid_for_home_delivery(ng, covered_ikeja, gig_option):
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(4175.2))
    )

    class PinnedAddress(FakeAddress):
        latitude = "6.601000"
        longitude = "3.351000"

    address = PinnedAddress(area_region=covered_ikeja, state_region=covered_ikeja.parent)
    _options(address, ng)
    import json as jsonlib

    body = jsonlib.loads(route.calls[0].request.content)
    assert body["ReceiverLocation"] == {"Latitude": 6.601, "Longitude": 3.351}  # the pin
    assert body["PickUpOptions"] == 0


@override_settings(**SETTINGS)
@respx.mock
def test_gig_centres_endpoint_owns_addresses_and_sorts(ng, pickup_world, django_user_model):
    from rest_framework.test import APIClient

    from apps.accounts.models import Address

    epe, centre = pickup_world
    user = django_user_model.objects.create_user(email="pick@x.com", password="pw")
    other = django_user_model.objects.create_user(email="other@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 Epe Road", country_code="NG",
                                  state_region=epe.parent, area_region=epe)
    api = APIClient()
    api.force_authenticate(user)
    r = api.get(f"/api/v1/checkout/gig-centres/?address_id={addr.id}")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert names[0] == "EPE CENTRE"  # nearest first, address included
    assert r.json()[0]["address"] == "1 Epe Rd"

    api.force_authenticate(other)
    assert api.get(f"/api/v1/checkout/gig-centres/?address_id={addr.id}").status_code == 404
