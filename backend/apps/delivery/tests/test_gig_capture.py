"""Waybill capture (Plan-32a slice 5): every refusal happens BEFORE money moves,
a timeout parks the shipment where no retry can reach it, and success stamps the
waybill onto both the shipment and the order's generic tracking fields."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.core.models import Country, Region
from apps.delivery.gig import client
from apps.delivery.gig.capture import (
    WALLET_CACHE_KEY,
    CaptureRefused,
    CaptureUnconfirmed,
    capture_shipment,
    fetch_label,
    wallet_balance,
)
from apps.delivery.models import GigShipment
from apps.orders.models import Order, OrderEvent

BASE = "https://gig.test"
SETTINGS = dict(
    GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw",
    GIG_SENDER_LATITUDE=6.556, GIG_SENDER_LONGITUDE=3.3888, GIG_VEHICLE_TYPE=1,
    GIG_SENDER_NAME="Toke Cosmetics", GIG_SENDER_PHONE="+2348000000001",
    GIG_SENDER_ADDRESS="Gbagada, Lagos", GIG_SENDER_LOCALITY="Gbagada",
)

pytestmark = pytest.mark.django_db


def _envelope(data, status=200, message="Success", api_id="cap-1"):
    return {"message": message, "apiId": api_id, "status": status, "data": data}


def _company(balance):
    return _envelope({"data": [{"CustomerCode": "ECO1", "WalletAmount": balance}]})


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)
    yield
    cache.clear()


@pytest.fixture
def order(django_user_model):
    ng = Country.objects.get(code="NG")
    ikeja = Region.objects.get(country_code="NG", level="area", name="Ikeja", parent__name="Lagos")
    Region.objects.filter(pk=ikeja.pk).update(latitude="6.618570", longitude="3.342590")
    user = django_user_model.objects.create_user(email="cap@x.com", password="pw")
    return Order.objects.create(
        number="TC-900100", user=user, email=user.email, country=ng, currency=ng.currency,
        status="processing", subtotal=Decimal("15000.00"), shipping_total=Decimal("4175.20"),
        grand_total=Decimal("19175.20"),
        shipping_address={"first_name": "Ada", "last_name": "O", "phone": "+2348000000002",
                          "line1": "12 Allen Ave", "state": "Lagos", "area": "Ikeja",
                          "country_code": "NG"},
    )


@pytest.fixture
def quoted(order):
    return GigShipment.objects.create(
        order=order, status="quoted", charged=Decimal("4175.20"),
        quote={"price": "4175.20", "breakdown": {"GrandTotal": 4175.2}, "api_id": "q-1"},
    )


@override_settings(**SETTINGS)
@respx.mock
def test_refusals_happen_before_any_capture_call(order, quoted, django_user_model):
    actor = django_user_model.objects.get(email="cap@x.com")
    capture_route = respx.post(f"{BASE}/capture/preshipment")

    # Wrong order state.
    Order.objects.filter(pk=order.pk).update(status="pending_payment")
    order.refresh_from_db()
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "order_not_paid"

    # Insufficient wallet.
    Order.objects.filter(pk=order.pk).update(status="processing")
    order.refresh_from_db()
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(100))
    )
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "wallet_insufficient"

    # Missing centroid.
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    Region.objects.filter(name="Ikeja").update(latitude=None, longitude=None)
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "no_centroid"

    assert capture_route.call_count == 0  # money never moved
    quoted.refresh_from_db()
    assert quoted.status == "quoted"


@override_settings(**SETTINGS)
@respx.mock
def test_timeout_parks_in_create_unconfirmed_with_one_attempt(order, quoted, django_user_model):
    actor = django_user_model.objects.get(email="cap@x.com")
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(None))  # sandbox: no wallet record
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(CaptureUnconfirmed):
        capture_shipment(order, actor=actor)
    assert route.call_count == 1  # the whole point
    quoted.refresh_from_db()
    assert quoted.status == "create_unconfirmed"
    assert OrderEvent.objects.filter(order=order, type="gig",
                                     message__icontains="unconfirmed").exists()
    # And the parked state refuses a second capture outright.
    order.refresh_from_db()
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "wrong_state"
    assert route.call_count == 1


@override_settings(**SETTINGS)
@respx.mock
def test_successful_capture_stamps_everything(order, quoted, django_user_model):
    actor = django_user_model.objects.get(email="cap@x.com")
    cache.set(WALLET_CACHE_KEY, "50000", 900)
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113095"}))
    )
    shipment = capture_shipment(order, actor=actor)

    assert shipment.status == "created"
    assert shipment.waybill == "1349113095"
    assert shipment.cost == Decimal("4175.20")
    assert shipment.capture_api_id == "cap-1"
    order.refresh_from_db()
    assert order.tracking_carrier == "GIG"
    assert order.tracking_number == "1349113095"
    assert cache.get(WALLET_CACHE_KEY) is None  # balance invalidated: it just changed

    sent = route.calls[0].request
    import json as jsonlib

    body = jsonlib.loads(sent.content)
    assert body["ReceiverDetails"]["ReceiverLocation"] == {"Latitude": 6.61857, "Longitude": 3.34259}
    assert body["ReceiverDetails"]["ReceiverName"] == "Ada O"
    assert body["ShipmentDetails"]["IsCashOnDelivery"] is False
    assert body["ShipmentItems"][0]["ShipmentType"] == 1


@override_settings(**SETTINGS)
@respx.mock
def test_snapshot_pin_replaces_the_centroid_in_receiver_location(order, quoted, django_user_model):
    """Plan-32b ruling 2: with a pin, the WAYBILL ships door coordinates — read from
    the placement snapshot, not the live Address row."""
    actor = django_user_model.objects.get(email="cap@x.com")
    order.shipping_address = {**order.shipping_address, "latitude": 6.601838, "longitude": 3.351486}
    order.save(update_fields=["shipping_address"])
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113097"}))
    )
    capture_shipment(order, actor=actor)
    import json as jsonlib

    body = jsonlib.loads(route.calls[0].request.content)
    assert body["ReceiverDetails"]["ReceiverLocation"] == {
        "Latitude": 6.601838, "Longitude": 3.351486,
    }


@override_settings(**SETTINGS)
@respx.mock
def test_company_not_found_precheck_does_not_block_capture(order, quoted, django_user_model):
    """Production (measured 2026-08-11): /companyDetails/get answers 401 "Company not
    found." for our account while the shipment endpoints work. The pre-check is
    advisory — it must degrade to balance-unknown, exactly like the sandbox's null."""
    actor = django_user_model.objects.get(email="cap@x.com")
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(401, json=_envelope(None, status=401, message="Company not found."))
    )
    # The client's 401 re-login path runs for reads; feed it a token.
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=_envelope({"access-token": "jwt-2"}))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113096"}))
    )
    shipment = capture_shipment(order, actor=actor)
    assert route.call_count == 1
    assert shipment.status == "created"


@override_settings(**SETTINGS)
@respx.mock
def test_gig_unreachable_precheck_still_refuses_capture(order, quoted, django_user_model):
    actor = django_user_model.objects.get(email="cap@x.com")
    respx.get(f"{BASE}/companyDetails/get").mock(side_effect=httpx.ConnectError("down"))
    route = respx.post(f"{BASE}/capture/preshipment")
    with pytest.raises(client.GigUnavailable):
        capture_shipment(order, actor=actor)
    assert route.call_count == 0  # money-moving call never attempted at a down API
    quoted.refresh_from_db()
    assert quoted.status == "quoted"


@override_settings(**SETTINGS)
@respx.mock
def test_label_not_ready_is_none_and_success_stores_the_url(order, quoted):
    quoted.status, quoted.waybill = "created", "1349113095"
    quoted.save(update_fields=["status", "waybill"])

    # GIG answers 401 for "not processed yet" — the client's ambiguity rule re-logs-in
    # once (harmless for a read) and the second 401 surfaces, which fetch_label reads
    # as the normal not-ready state.
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=_envelope({"access-token": "jwt-2"}))
    )
    respx.post(f"{BASE}/invoice/generate").mock(
        return_value=httpx.Response(200, json=_envelope({}, status=401,
                                                        message="Shipment Details Not Found."))
    )
    assert fetch_label(quoted) is None  # normal pre-processing state, not an error

    respx.post(f"{BASE}/invoice/generate").mock(
        return_value=httpx.Response(200, json=_envelope("https://s3.example/label.pdf"))
    )
    assert fetch_label(quoted) == "https://s3.example/label.pdf"
    quoted.refresh_from_db()
    assert quoted.label_url == "https://s3.example/label.pdf"


@override_settings(**SETTINGS)
@respx.mock
def test_wallet_balance_caches_and_reports_unknown_honestly():
    route = respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(12345.5))
    )
    assert wallet_balance() == Decimal("12345.50")
    assert wallet_balance() == Decimal("12345.50")
    assert route.call_count == 1  # cached

    cache.clear()
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(None))
    )
    assert wallet_balance() is None  # unknown is unknown, not zero


# --- Centre-pickup capture (32b slice 5; shape measured in research §2g) ---

def _make_pickup(quoted, centre_snap):
    quoted.centre = centre_snap
    quoted.save(update_fields=["centre"])
    return quoted


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_capture_sends_destination_centre_and_centre_coordinates(order, quoted, django_user_model):
    actor = django_user_model.objects.get(email="cap@x.com")
    _make_pickup(quoted, {"id": 540, "station_id": 4, "name": "GIG Alausa",
                          "address": "Plot Y, Mobolaji Johnson, Alausa Ikeja",
                          "latitude": 6.6078944, "longitude": 3.3693221})
    # A pickup-only LGA: kill the region centroid to prove capture no longer needs it.
    Region.objects.filter(name="Ikeja").update(latitude=None, longitude=None)
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113394"}))
    )
    shipment = capture_shipment(order, actor=actor)
    assert shipment.status == "created"

    import json as jsonlib
    body = jsonlib.loads(route.calls[0].request.content)
    rd = body["ReceiverDetails"]
    assert rd["DestinationServiceCenterId"] == 540  # the measured field, measured place
    assert rd["ReceiverLocation"] == {"Latitude": 6.6078944, "Longitude": 3.3693221}
    assert rd["ReceiverAddress"] == "Plot Y, Mobolaji Johnson, Alausa Ikeja"
    assert rd["ReceiverName"] == "Ada O"  # the COLLECTOR stays the named receiver
    assert "DestinationServiceCenterId" not in body.get("ShipmentDetails", {})


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_capture_refuses_malformed_or_coordinateless_snapshots(order, quoted, django_user_model):
    """GIG accepts ANY DestinationServiceCenterId without validation (measured:
    999999 minted a waybill) — so a bad snapshot must refuse, never guess, and
    NEVER quietly fall back to door delivery."""
    actor = django_user_model.objects.get(email="cap@x.com")
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment")

    _make_pickup(quoted, {"name": "GIG Alausa", "address": "x"})  # no id
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "centre_snapshot_invalid"

    # Old snapshot without coordinates and no synced row either → refuse.
    _make_pickup(quoted, {"id": 540, "name": "GIG Alausa", "address": "x"})
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "centre_coordinates_missing"

    # Same snapshot, but the nightly sync knows the centre → capture proceeds on
    # the live coordinates.
    from apps.delivery.models import GigCentre
    GigCentre.objects.create(gig_centre_id=540, gig_station_id=4, name="GIG Alausa",
                             address="x", latitude="6.607894", longitude="3.369322",
                             is_active=True, synced_at=timezone.now())
    route.mock(return_value=httpx.Response(200, json=_envelope({"Waybill": "WB-PICKUP"})))
    shipment = capture_shipment(order, actor=actor)
    assert shipment.waybill == "WB-PICKUP"
    import json as jsonlib
    rd = jsonlib.loads(route.calls[-1].request.content)["ReceiverDetails"]
    assert rd["ReceiverLocation"] == {"Latitude": 6.607894, "Longitude": 3.369322}


@override_settings(**SETTINGS)
@respx.mock
def test_capture_ships_from_the_origin_snapshot_not_the_env(order, quoted, django_user_model):
    """Plan-34: SenderDetails come from GigShipment.origin — the row the customer
    was quoted from — even though the env still points at the old sender."""
    actor = django_user_model.objects.get(email="cap@x.com")
    GigShipment.objects.filter(pk=quoted.pk).update(origin={
        "id": 2, "name": "Kubwa (Abuja)", "phone": "+2347074800702",
        "address": "Shop 7, Lane 3, Building Materials Market, Kubwa, FCT",
        "locality": "Kubwa", "latitude": 9.138, "longitude": 7.322,
    })
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113200"}))
    )
    capture_shipment(order, actor=actor)
    import json as jsonlib

    sender = jsonlib.loads(route.calls[0].request.content)["SenderDetails"]
    assert sender["SenderName"] == "Kubwa (Abuja)"
    assert sender["SenderPhoneNumber"] == "+2347074800702"
    assert sender["SenderAddress"] == "Shop 7, Lane 3, Building Materials Market, Kubwa, FCT"
    assert sender["InputtedSenderAddress"] == sender["SenderAddress"]
    assert sender["SenderLocality"] == "Kubwa"
    assert sender["SenderLocation"] == {"Latitude": 9.138, "Longitude": 7.322}


@override_settings(**SETTINGS)
@respx.mock
def test_capture_with_no_origin_snapshot_uses_the_env_sender(order, quoted, django_user_model):
    """Pre-Plan-34 shipments (empty origin dict) keep today's behaviour exactly."""
    actor = django_user_model.objects.get(email="cap@x.com")
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113201"}))
    )
    capture_shipment(order, actor=actor)
    import json as jsonlib

    sender = jsonlib.loads(route.calls[0].request.content)["SenderDetails"]
    assert sender["SenderName"] == "Toke Cosmetics"
    assert sender["SenderAddress"] == "Gbagada, Lagos"
    assert sender["SenderLocation"] == {"Latitude": 6.556, "Longitude": 3.3888}


@override_settings(**SETTINGS)
@respx.mock
def test_capture_never_mixes_a_partial_origin_snapshot_with_env_coordinates(
    order, quoted, django_user_model
):
    """A snapshot missing its coordinate pair is treated as absent wholesale —
    the env sender ships, never a hybrid of snapshot address + env pin."""
    actor = django_user_model.objects.get(email="cap@x.com")
    GigShipment.objects.filter(pk=quoted.pk).update(origin={
        "id": 2, "name": "Kubwa (Abuja)", "address": "Somewhere, Kubwa", "latitude": 9.138,
    })
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_company(50000))
    )
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({"Waybill": "1349113202"}))
    )
    capture_shipment(order, actor=actor)
    import json as jsonlib

    sender = jsonlib.loads(route.calls[0].request.content)["SenderDetails"]
    assert sender["SenderName"] == "Toke Cosmetics"
    assert sender["SenderLocation"] == {"Latitude": 6.556, "Longitude": 3.3888}
