"""AAJ push tracking (Plan-43b). AAJ publishes no webhook scheme, so the receiver is
built to be usable today (a secret in the path) and to LEARN theirs (a signature is
verified when sent, and how it matched is logged). The rules that keep that honest:
a signature that matches nothing is a rejection, and a payload we cannot map moves
nothing — the 2-hourly poll stays the source of truth."""
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
