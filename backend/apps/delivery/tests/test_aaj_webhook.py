"""AAJ push tracking (Plan-43b). The first half of this file dates from when AAJ
published no scheme: the receiver was built to be usable (a secret in the path) and
to LEARN theirs (a signature is verified when sent, and how it matched is logged).
The second half pins the scheme they published on 2026-09-22 — the `scan-notification`
envelope, its BOOKING and SHIPMENT payloads, and the idempotency and ordering their
doc asks consumers to handle. Both halves are kept, because their sender has still
never been seen and a shape we refuse to read is an event lost.

The rules that keep all of it honest: a signature that matches nothing is a rejection,
a booking's own integers are never read as a shipment status, and a payload we cannot
map moves nothing — the 2-hourly poll stays the source of truth."""
import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.delivery.aaj.webhook import extract_event, verify_signature
from apps.delivery.models import AajShipment
from apps.orders.models import Order

pytestmark = pytest.mark.django_db

TOKEN = "tok-abc123"
SIGNING_KEY = "aaj_whsec_testkey"
URL = f"/api/v1/webhooks/aaj/{TOKEN}/"
SETTINGS = dict(AAJ_WEBHOOK_TOKEN=TOKEN, AAJ_WEBHOOK_SIGNING_KEY=SIGNING_KEY)


@pytest.fixture
def shipment():
    ng = Country.objects.get(code="NG")
    order = Order.objects.create(
        number="TC-900700", email="c@x.com", country=ng, currency=ng.currency,
        status="processing", grand_total=Decimal("15000.00"),
        shipping_address={"first_name": "Ada", "last_name": "O", "state": "Lagos",
                          "area": "Ikeja", "country_code": "NG"},
    )
    return AajShipment.objects.create(
        order=order, status="created", charged=Decimal("3474.00"),
        booking_id="bk-9", tracking_id="D276AA3D",
    )


def _post(body: dict, *, sig_header=None, sig_value=None, url=URL):
    raw = json.dumps(body).encode()
    headers = {"HTTP_" + sig_header.upper().replace("-", "_"): sig_value} if sig_header else {}
    return APIClient().post(url, data=raw, content_type="application/json", **headers)


def _hmac_hex(raw: bytes, key=SIGNING_KEY):
    return hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


@override_settings(**SETTINGS)
def test_the_path_token_is_the_credential(shipment):
    assert _post({"trackingId": "D276AA3D", "status": 2}, url="/api/v1/webhooks/aaj/wrong/").status_code == 401
    response = _post({"trackingId": "D276AA3D", "status": 2})
    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "in_transit"


@override_settings(AAJ_WEBHOOK_TOKEN="", AAJ_WEBHOOK_SIGNING_KEY="")
def test_unconfigured_answers_503_so_aaj_keeps_retrying():
    """The same choice GIG's receiver makes: a 503 is visible and retried; a 200
    would silently eat every event until someone noticed the gap."""
    assert _post({"trackingId": "D276AA3D", "status": 2}).status_code == 503


@override_settings(**SETTINGS)
def test_a_signature_that_matches_nothing_is_refused_even_with_the_right_url(shipment):
    """Holding the URL is not a licence to skip a check AAJ performed."""
    response = _post({"trackingId": "D276AA3D", "status": 4},
                     sig_header="x-aaj-signature", sig_value="deadbeef")
    assert response.status_code == 401
    shipment.refresh_from_db()
    assert shipment.status == "created"  # nothing moved


@override_settings(**SETTINGS)
@pytest.mark.parametrize("header", ["x-aaj-signature", "x-webhook-signature", "x-hub-signature-256"])
@pytest.mark.parametrize("wrap", ["{sig}", "sha256={sig}", "t=1756000000,v1={sig}"])
def test_their_signature_verifies_whatever_header_and_wrapper_they_chose(shipment, header, wrap):
    raw = json.dumps({"trackingId": "D276AA3D", "status": 2}).encode()
    sig = wrap.format(sig=_hmac_hex(raw))
    response = APIClient().post(
        URL, data=raw, content_type="application/json",
        **{"HTTP_" + header.upper().replace("-", "_"): sig},
    )
    assert response.status_code == 200


@override_settings(**SETTINGS)
def test_base64_signatures_verify_too_and_the_match_is_logged(shipment, caplog):
    raw = json.dumps({"trackingId": "D276AA3D", "status": 2}).encode()
    sig = base64.b64encode(hmac.new(SIGNING_KEY.encode(), raw, hashlib.sha256).digest()).decode()
    with caplog.at_level(logging.INFO, logger="apps.delivery.views"):
        response = APIClient().post(URL, data=raw, content_type="application/json",
                                    HTTP_X_SIGNATURE=sig)
    assert response.status_code == 200
    # The line that turns their undocumented scheme into a pinned one.
    assert "x-signature" in caplog.text.lower() and "matched" in caplog.text.lower()


@override_settings(**SETTINGS)
def test_an_unmappable_payload_is_logged_and_moves_nothing(shipment, caplog):
    """The rule that protects ORDERS: a wrong code marks a customer delivered, so
    anything we cannot map is a log line and an ack, never a guess."""
    with caplog.at_level(logging.INFO, logger="apps.delivery.aaj.webhook"):
        assert _post({"trackingId": "D276AA3D", "state": "MOVING"}).json()["outcome"] == "unmapped_status"
        assert _post({"trackingId": "NOT-OURS", "status": 4}).json()["outcome"] == "unknown_shipment"
        assert _post({"event": "ping"}).json()["outcome"] == "no_tracking_id"
    shipment.refresh_from_db()
    assert shipment.status == "created"
    assert "unmapped status" in caplog.text and "unknown tracking id" in caplog.text


@override_settings(**SETTINGS)
def test_a_delivered_push_walks_the_order_the_same_way_the_poll_does(shipment):
    assert _post({"data": {"shipment": {"trackingId": "D276AA3D", "statusCode": 4}}}).status_code == 200
    shipment.refresh_from_db()
    shipment.order.refresh_from_db()
    assert shipment.status == "delivered"
    assert shipment.order.status == "delivered"


@override_settings(**SETTINGS)
def test_a_body_that_is_not_json_is_a_400(shipment):
    assert APIClient().post(URL, data=b"<html>nope</html>",
                            content_type="application/json").status_code == 400


def test_extract_event_digs_through_whatever_nesting_they_use():
    assert extract_event({"trackingId": "A1", "status": 2}) == ("A1", 2)
    assert extract_event({"data": [{"tracking_number": "B2", "statusCode": "3"}]}) == ("B2", 3)
    # A boolean `status` is not a code — theirs are ints 0..12.
    assert extract_event({"waybill": "C3", "status": True}) == ("C3", None)
    assert extract_event({"nothing": 1}) == ("", None)


def test_verify_signature_says_why_when_it_cannot():
    ok, how = verify_signature(b"{}", {}, SIGNING_KEY)
    assert not ok and "no signature header" in how
    ok, how = verify_signature(b"{}", {"X-Aaj-Signature": "nope"}, SIGNING_KEY)
    assert not ok and "matched nothing" in how
    # Proxy digest headers are not body HMACs and must not be mistaken for one.
    ok, how = verify_signature(b"{}", {"Content-Digest": "sha-256=:abc:"}, SIGNING_KEY)
    assert not ok and "no signature header" in how


# --- the documented envelope (readme-webhook.markdown, published 2026-09-22) --------

def _envelope(object_type, scan_type, payload):
    return {"event": "scan-notification",
            "data": {"objectType": object_type, "scanType": scan_type, "payload": payload}}


def _shipment_payload(**over):
    """Their SHIPMENT example, trimmed to the fields we read."""
    return {"_id": "sh-oid-1", "booking": "bk-9", "trackingId": "D276AA3D",
            "shipmentType": "DOMESTIC", "status": 6, "carrier": "AAJ",
            "updatedAt": "2026-03-19T04:19:43.846+01:00",
            "events": [{"scanType": "DESTINATION_SCAN", "dateTime": "2026-03-19T04:19:00.000Z",
                        "description": "Available For Pickup by Customer",
                        "objectType": "SHIPMENT", "shipmentTrackingId": "D276AA3D"}],
            **over}


def _booking_payload(**over):
    """Their BOOKING example. Note `humanStatus: 0` on a DELIVERED booking — the
    reason a booking's own integers are never read as a shipment status."""
    return {"_id": "bk-9", "searchId": "89498456", "customBookingId": "TC-900700",
            "deliveryType": "DROP_OFF", "orderState": 2, "bookingState": 3,
            "humanStatus": 0, "partner": True, "paid": True,
            "updatedAt": "2026-03-19T04:19:44.085+01:00",
            "collectionEvents": [{"scanType": "DELIVERY_SCAN", "location": "Delta",
                                  "dateTime": "2026-03-19T03:55:49.610Z",
                                  "description": "Order has been delivered"}],
            **over}


@pytest.fixture(autouse=True)
def _fresh_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@override_settings(**SETTINGS)
def test_their_documented_shipment_envelope_moves_the_shipment(shipment):
    """The payload is nested three deep under `data.payload` and carries their own
    integer `status` — the same 0..12 vocabulary the poll reads."""
    response = _post(_envelope("SHIPMENT", "DESTINATION_SCAN", _shipment_payload()))
    assert response.status_code == 200 and response.json()["outcome"] == "in_transit"
    shipment.refresh_from_db()
    assert shipment.status == "in_transit" and shipment.last_status == 6
    # last_scan keeps the shape the poll writes, so capture.can_void can read scanType.
    assert shipment.last_scan["scanType"] == "DESTINATION_SCAN"


@override_settings(**SETTINGS)
def test_a_booking_event_lands_even_though_bookings_carry_no_tracking_id(shipment):
    """Matched on `payload._id` == our booking_id. The old extractor dropped every
    booking event, because it looked for a tracking id a booking never has."""
    assert _post(_envelope("BOOKING", "DELIVERY_SCAN", _booking_payload())).json()["outcome"] == "delivered"
    shipment.refresh_from_db()
    shipment.order.refresh_from_db()
    assert shipment.status == "delivered" and shipment.order.status == "delivered"


@override_settings(**SETTINGS)
def test_a_booking_is_matched_by_our_order_number_when_the_id_is_unfamiliar(shipment):
    """`customBookingId` is our order number — the handle that still works when the
    booking was recreated at AAJ's end and our stored id is stale."""
    payload = _booking_payload(_id="some-other-booking")
    assert _post(_envelope("BOOKING", "RETURN_SCAN", payload)).json()["outcome"] == "returned"
    shipment.refresh_from_db()
    assert shipment.status == "returned"


@override_settings(**SETTINGS)
def test_a_bookings_own_integers_are_never_read_as_a_shipment_status(shipment):
    """THE trap this mapping exists to avoid: a booking's `humanStatus`/`bookingState`
    are a different vocabulary (their own delivered example carries `humanStatus: 0`),
    so an unknown scanType on a booking must move nothing rather than read an int."""
    payload = _booking_payload(status=4)  # even a literal `status` on a booking
    outcome = _post(_envelope("BOOKING", "SOMETHING_NEW_SCAN", payload)).json()["outcome"]
    assert outcome == "unmapped_status"
    shipment.refresh_from_db()
    assert shipment.status == "created"


@override_settings(**SETTINGS)
def test_a_shipment_is_found_by_its_parent_booking_when_we_hold_no_tracking_id(shipment):
    """The handle that rescues a row parked before capture ever stamped a tracking id
    — the `create_unconfirmed` lane, where AAJ holds a shipment and we do not."""
    shipment.status, shipment.tracking_id = "create_unconfirmed", ""
    shipment.save()
    payload = _shipment_payload(trackingId="", status=2)
    assert _post(_envelope("SHIPMENT", "ORIGIN_SCAN", payload)).status_code == 200
    shipment.refresh_from_db()
    assert shipment.last_status == 2


@override_settings(**SETTINGS)
def test_a_repeat_of_the_same_event_is_acked_without_reapplying(shipment):
    """Their doc: "Do not assume webhooks always arrive once" — five retry attempts,
    and a 200 we send after a slow apply can still time out on their side."""
    body = _envelope("SHIPMENT", "DELIVERY_SCAN", _shipment_payload(status=4))
    assert _post(body).json()["outcome"] == "delivered"
    assert _post(body).json()["outcome"] == "duplicate"


@override_settings(**SETTINGS)
def test_an_event_older_than_the_one_already_applied_is_dropped(shipment):
    """Their doc: "Do not assume strict delivery order". apply_status writes
    last_status unconditionally, so a late ARRIVAL_SCAN would otherwise rewind a
    delivered shipment's scan history."""
    delivered = _shipment_payload(status=4, updatedAt="2026-03-19T10:00:00.000Z")
    assert _post(_envelope("SHIPMENT", "DELIVERY_SCAN", delivered)).json()["outcome"] == "delivered"
    late = _shipment_payload(status=2, updatedAt="2026-03-19T04:00:00.000Z")
    assert _post(_envelope("SHIPMENT", "ARRIVAL_SCAN", late)).json()["outcome"] == "stale"
    shipment.refresh_from_db()
    assert shipment.status == "delivered" and shipment.last_status == 4


@override_settings(**SETTINGS)
def test_a_booking_pickup_scan_is_the_proof_a_rider_collected_from_us(shipment, caplog):
    """`collectionMode: PICKUP` is undocumented and its acceptance is not its action.
    A PICKUP_SCAN on the BOOKING is the only evidence AAJ's API can give that a rider
    actually came to the shop — so it gets its own line to find later."""
    with caplog.at_level(logging.INFO, logger="apps.delivery.aaj.webhook"):
        assert _post(_envelope("BOOKING", "PICKUP_SCAN", _booking_payload())).status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "in_transit"
    assert "a rider collected from us" in caplog.text


@override_settings(**SETTINGS)
def test_the_documented_signature_is_the_one_that_verifies(shipment):
    """Hex HMAC-SHA256 of the RAW body in `x-aaj-signature` — their published scheme."""
    raw = json.dumps(_envelope("SHIPMENT", "DELIVERY_SCAN", _shipment_payload(status=4))).encode()
    response = APIClient().post(URL, data=raw, content_type="application/json",
                                HTTP_X_AAJ_SIGNATURE=_hmac_hex(raw))
    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "delivered"


@override_settings(**SETTINGS, AAJ_WEBHOOK_REQUIRE_SIGNATURE=True)
def test_unsigned_pushes_can_be_refused_once_they_are_known_to_sign(shipment):
    """Off by default: no AAJ webhook has ever arrived here, and 401ing a push they
    really send loses the event after five retries. On, once one has proved they sign."""
    assert _post(_envelope("SHIPMENT", "DELIVERY_SCAN", _shipment_payload())).status_code == 401
    shipment.refresh_from_db()
    assert shipment.status == "created"


@override_settings(**SETTINGS)
def test_the_ordering_guard_never_drops_an_event_from_the_other_object(shipment):
    """A booking's `updatedAt` and its shipment's are two different clocks, and their
    examples do not even agree on the offset format (`+01:00` vs `Z`). Comparing
    across them would silently swallow a real delivery, so the guard refuses to."""
    late_shipment = _shipment_payload(status=2, updatedAt="2026-09-03T23:00:00.816Z")
    assert _post(_envelope("SHIPMENT", "ARRIVAL_SCAN", late_shipment)).json()["outcome"] == "in_transit"
    earlier_booking = _booking_payload(updatedAt="2026-09-03T12:00:00.000+01:00")
    assert _post(_envelope("BOOKING", "DELIVERY_SCAN", earlier_booking)).json()["outcome"] == "delivered"
    shipment.refresh_from_db()
    assert shipment.status == "delivered"
