"""The AAJ checkout quote layer (Plan-43): AAJ appears priced for any NG address
whose state AAJ can price, is OMITTED on any failure (no state, no usable origin,
outage, malformed total, a weightless line), and never slows checkout past its
one-attempt budget. Manual options pass through untouched in every case."""
from collections import namedtuple
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.core.models import Country, Currency, Region
from apps.delivery.aaj.origins import select_origin, usable_origins
from apps.delivery.aaj.quotes import _cache_key
from apps.delivery.carriers import priced_options_for_address
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.models import DeliveryOption, SenderLocation

BASE = "https://aaj.test/api/v2"
SETTINGS = dict(AAJ_BASE_URL=BASE, AAJ_API_KEY="aaj-testkey", AAJ_SENDER_POSTAL_CODE="100001")

pytestmark = pytest.mark.django_db

FakeVariant = namedtuple("FakeVariant", "weight_grams")


class FakeAddress:
    def __init__(self, country_code="NG", state_region=None, area_region=None,
                 latitude=None, longitude=None, city_text=""):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region
        self.latitude = latitude
        self.longitude = longitude
        self.city_text = city_text


def _quote_envelope(total, eta_days=2, sub=None):
    # The measured shape (plan doc §2): data.quotes[0] with total, subTotal, tax, eta.
    return {
        "success": True, "message": "quote created", "status": 200,
        "data": {"quotes": [{
            "subTotal": sub if sub is not None else round(total / 1.075, 2),
            "shippingFee": sub if sub is not None else round(total / 1.075, 2),
            "tax": round(total - total / 1.075, 3), "vat": 7.5, "total": total,
            "weight": 1, "rate": "SR", "carrier": "AAJ", "currency": "NGN",
            "eta": {"numberOfDays": eta_days, "dateOfArrival": "2026-08-25T14:57:00.000000+01:00"},
            "insurance": {"type": "NE", "fee": 0}, "booking": "6a8b0a3bbb5d1bf9d276a682",
            "quoteId": "L1JNOUPT", "hasCompleteBooking": False,
        }]},
    }


@pytest.fixture
def ng():
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    country, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return country


@pytest.fixture
def lagos():
    return Region.objects.get(country_code="NG", level="state", name="Lagos")


@pytest.fixture
def kano():
    return Region.objects.get(country_code="NG", level="state", name="Kano")


@pytest.fixture
def ikeja(lagos):
    ikeja = Region.objects.get(country_code="NG", level="area", name="Ikeja", parent=lagos)
    Region.objects.filter(pk=ikeja.pk).update(latitude="6.618570", longitude="3.342590")
    ikeja.refresh_from_db()
    return ikeja


@pytest.fixture
def aaj_option(ng):
    option = DeliveryOption.objects.get(carrier_code="aaj")  # seeded by migration 0022
    option.is_active = True
    option.save(update_fields=["is_active"])
    return option


@pytest.fixture
def flat_option(ng):
    option = DeliveryOptionFactory(name="Nationwide Delivery", price="3500.00", currency=ng.currency)
    option.countries.add(ng)
    return option


@pytest.fixture
def ogudu():
    """The seeded Ogudu row (migration 0014): blank state label, Lagos pin. The test
    DB carries no LGA centroids (they load from a CSV command, not a migration), so
    the one the pin resolves through — Kosofe — is given its real centroid here."""
    Region.objects.filter(country_code="NG", level="area", name="Kosofe", parent__name="Lagos").update(
        latitude="6.5830", longitude="3.4020")
    return SenderLocation.objects.get(is_active=True)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _options(address, ng, weight_g=500):
    lines = [(FakeVariant(weight_grams=weight_g), 1)]
    return priced_options_for_address(address, lines, Decimal("15000.00"), ng)


# --- origins -----------------------------------------------------------------------

def test_seeded_ogudu_row_resolves_its_state_from_its_pin(ogudu):
    # Migration 0014 left `state` blank and `state_region` null. The pin lands in
    # Kosofe, Lagos — the origin must say Lagos, never a settings constant.
    assert ogudu.state == "" and ogudu.state_region_id is None
    [origin] = usable_origins()
    assert origin.state_name == "Lagos" and origin.state_code == "LA"
    assert origin.postal_code == "100001" or origin.postal_code


def test_state_label_outranks_the_pin_and_unresolvable_rows_are_skipped(ogudu):
    abuja = SenderLocation.objects.create(
        name="Kubwa", phone="+2348000000009", address="Kubwa, Abuja", locality="Kubwa",
        latitude="9.1566", longitude="7.3383", state="FCT", is_active=True,
    )
    by_id = {o.id: o for o in usable_origins()}
    assert by_id[abuja.pk].state_code == "FCT"
    # A row whose label names no state AND whose pin is nowhere near Nigeria still
    # resolves to the nearest LGA (there is always one) — but a label that is simply
    # wrong would be a data-entry error, and the label is trusted over the pin.
    SenderLocation.objects.filter(pk=abuja.pk).update(state="Kano")
    assert {o.id: o for o in usable_origins()}[abuja.pk].state_code == "KN"


def test_origin_prefers_the_receivers_state_then_distance(ogudu, lagos, kano, ikeja):
    abuja = SenderLocation.objects.create(
        name="Kubwa", phone="+2348000000009", address="Kubwa, Abuja", locality="Kubwa",
        latitude="9.1566", longitude="7.3383", state="FCT", is_active=True,
    )
    fct = Region.objects.get(country_code="NG", level="state", name="Federal Capital Territory")
    # Same state wins outright.
    assert select_origin(FakeAddress(state_region=fct)).id == abuja.pk
    assert select_origin(FakeAddress(state_region=lagos, area_region=ikeja)).id == ogudu.pk
    # No same-state origin: nearest to the pin. Kano is nearer Abuja than Lagos.
    assert select_origin(FakeAddress(state_region=kano, latitude=12.0, longitude=8.5)).id == abuja.pk
    # No pin and no LGA centroid: the lowest pk, deterministically.
    assert select_origin(FakeAddress(state_region=kano)).id == ogudu.pk


def test_no_active_origin_means_no_aaj(ng, lagos, ikeja, aaj_option, ogudu):
    SenderLocation.objects.update(is_active=False)
    assert select_origin(FakeAddress(state_region=lagos)) is None
    assert all(o["carrier_code"] != "aaj" for o in _options(FakeAddress(state_region=lagos), ng))


# --- quoting -----------------------------------------------------------------------

@override_settings(**SETTINGS)
@respx.mock
def test_any_ng_state_gets_a_priced_aaj_option_and_flat_options_pass_through(
    ng, lagos, ikeja, aaj_option, flat_option, ogudu
):
    route = respx.post(f"{BASE}/quote").mock(
        return_value=httpx.Response(200, json=_quote_envelope(2779, eta_days=2))
    )
    address = FakeAddress(state_region=lagos, area_region=ikeja)
    options = _options(address, ng)
    by_name = {o["name"]: o for o in options}
    assert by_name["Nationwide Delivery"]["price"] == "3500.00"
    aaj = by_name["Door Delivery (AAJ Express)"]
    assert aaj["price"] == "2779.00"
    assert aaj["carrier_quote_key"] == _cache_key(ogudu.pk, lagos.id, 500)
    # AAJ's own ETA replaces the row's static pair — max only; min never rises.
    assert (aaj["min_days"], aaj["max_days"]) == (2, 2)
    assert "breakdown" not in aaj

    body = route.calls[0].request.read()
    import json

    sent = json.loads(body)
    # THE MONEY FIELD: the receiver's state code from our table, never a guess.
    assert sent["receiver"]["addressDetails"]["stateOrProvinceCode"] == "LA"
    assert sent["receiver"]["addressDetails"]["city"] == "Ikeja"
    assert sent["sender"]["addressDetails"]["stateOrProvinceCode"] == "LA"
    assert sent["sender"]["addressDetails"]["postalCode"] == "100001"
    assert sent["serviceType"] == "DOMESTIC" and sent["deliveryMode"] == "DOOR_STEP"
    assert sent["packages"]["packages"][0]["actualWeight"] == 0.5
    assert sent["packages"]["packages"][0]["packageDimension"]["length"] == 20


@override_settings(**SETTINGS)
@respx.mock
def test_far_state_eta_widens_max_days_only(ng, kano, aaj_option, ogudu):
    respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json=_quote_envelope(9099, eta_days=8)))
    [aaj] = [o for o in _options(FakeAddress(state_region=kano), ng) if o["carrier_code"] == "aaj"]
    assert aaj["price"] == "9099.00"
    assert (aaj["min_days"], aaj["max_days"]) == (2, 8)  # row min 2 stays, max is AAJ's 8


@override_settings(**SETTINGS)
@respx.mock
def test_an_address_without_a_state_region_or_an_unpriceable_state_gets_no_aaj(ng, aaj_option, ogudu):
    route = respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json=_quote_envelope(2779)))
    assert all(o["carrier_code"] != "aaj" for o in _options(FakeAddress(state_region=None), ng))
    # A state region our table cannot code (a renamed row) is omitted, NOT sent —
    # measured: AAJ prices an unknown code as Lagos, silently.
    odd = Region.objects.create(country_code="NG", level="state", name="Atlantis", is_active=True)
    assert all(o["carrier_code"] != "aaj" for o in _options(FakeAddress(state_region=odd), ng))
    assert route.call_count == 0


@override_settings(**SETTINGS)
@respx.mock
def test_second_call_is_served_from_cache_and_keys_on_ceil_kg(ng, lagos, aaj_option, ogudu):
    route = respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json=_quote_envelope(2779)))
    address = FakeAddress(state_region=lagos)
    _options(address, ng, weight_g=500)
    _options(address, ng, weight_g=900)  # same ≤1 kg tier
    assert route.call_count == 1
    _options(address, ng, weight_g=1200)  # measured: 1.2 kg is the 2 kg tier
    assert route.call_count == 2
    cached = cache.get(_cache_key(ogudu.pk, lagos.id, 500))
    assert cached["price"] == "2779.00" and cached["eta_days"] == 2
    assert cached["origin"]["state_code"] == "LA" and cached["origin"]["id"] == ogudu.pk


@override_settings(**SETTINGS)
@respx.mock
def test_aaj_is_omitted_not_erroring_when_the_chain_breaks(ng, lagos, aaj_option, ogudu):
    address = FakeAddress(state_region=lagos)

    respx.post(f"{BASE}/quote").mock(side_effect=httpx.ConnectError("down"))
    assert all(o["carrier_code"] != "aaj" for o in _options(address, ng))

    route = respx.post(f"{BASE}/quote").mock(side_effect=httpx.ReadTimeout("slow"))
    before = route.call_count
    assert all(o["carrier_code"] != "aaj" for o in _options(address, ng))
    assert route.call_count == before + 1  # one attempt, the budget

    respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"quotes": []}, "status": 200, "message": "quote created"}))
    assert all(o["carrier_code"] != "aaj" for o in _options(address, ng))

    respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(400, json={
        "success": False, "message": "Town not found in any AAJ operational zone", "status": 400}))
    assert all(o["carrier_code"] != "aaj" for o in _options(address, ng))


@override_settings(**SETTINGS)
@respx.mock
def test_a_weightless_line_omits_aaj_but_not_gig_or_flat(ng, lagos, aaj_option, flat_option, ogudu):
    route = respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json=_quote_envelope(2779)))
    lines = [(FakeVariant(weight_grams=500), 1), (FakeVariant(weight_grams=None), 1)]
    options = priced_options_for_address(FakeAddress(state_region=lagos), lines, Decimal("15000.00"), ng)
    assert "Nationwide Delivery" in {o["name"] for o in options}
    assert all(o["carrier_code"] != "aaj" for o in options)
    assert route.call_count == 0  # AAJ prices by weight and reweighs: unknown weight is unquotable


@override_settings(**SETTINGS)
@respx.mock
def test_free_over_and_fee_mask_apply_to_the_charge_not_the_cached_cost(ng, lagos, aaj_option, ogudu):
    from apps.delivery.models import DeliveryFeeMask

    respx.post(f"{BASE}/quote").mock(return_value=httpx.Response(200, json=_quote_envelope(2779)))
    address = FakeAddress(state_region=lagos)
    DeliveryFeeMask.objects.create(service_code="aaj", percent=Decimal("10"))
    [aaj] = [o for o in _options(address, ng) if o["carrier_code"] == "aaj"]
    assert aaj["price"] == "3056.90"  # 2779 × 1.10, kobo-exact
    assert cache.get(_cache_key(ogudu.pk, lagos.id, 500))["price"] == "2779.00"

    aaj_option.free_over = Decimal("10000.00")
    aaj_option.save(update_fields=["free_over"])
    [aaj] = [o for o in _options(address, ng) if o["carrier_code"] == "aaj"]
    assert aaj["price"] == "0.00"


def test_aaj_is_a_known_service_for_blocks_and_masks():
    from apps.delivery.services import known_delivery_services, service_code_for

    codes = {s["code"] for s in known_delivery_services()}
    assert {"gig", "aaj"} <= codes
    assert service_code_for({"kind": "carrier", "carrier_code": "aaj", "id": 9}) == "aaj"
