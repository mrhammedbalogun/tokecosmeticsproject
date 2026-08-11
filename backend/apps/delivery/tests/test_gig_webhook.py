"""The GIG tracking webhook receiver (gig/webhook.py + GigWebhookView).

Contract under test: a body that decrypts with OUR secret is authenticated and
applies through the same state rules as the poll; anything else is a 400 that
touches nothing. Unknown waybills ACK 200 (retries can't fix them); a missing
secret answers 503 so GIG keeps retrying while we finish configuring.
"""
import base64
import hashlib
import json
import os
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.test import override_settings
from django.urls import reverse

from apps.core.models import Country
from apps.delivery.gig.webhook import InvalidWebhookPayload, decrypt_payload
from apps.delivery.models import GigShipment
from apps.orders.models import Order

pytestmark = pytest.mark.django_db

SECRET = "vgWA4WiL1pqtfFCvu3vb"  # shape from GIG's docs example


def encrypt(event: dict, secret: str) -> str:
    """The inverse of GIG's published decryptors: base64(salt+iv+AES-CBC(PKCS7))."""
    salt, iv = os.urandom(16), os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha1", secret.encode(), salt, 10_000, dklen=32)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(event).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(salt + iv + encryptor.update(padded) + encryptor.finalize()).decode()


def event(waybill="WB-1", code="MAHD", status_text="SHIPMENT PICKED UP"):
    # The measured webhook shape: Status is human text, StatusCode is the code.
    return {
        "Waybill": waybill, "SenderAddress": "Gbagada, Lagos",
        "ReceiverAddress": "Ikeja, Lagos", "Location": "GBAGADA",
        "Status": status_text, "UserId": "u-1", "ChannelCode": "ECO078703",
        "StatusCode": code,
    }


def _shipment(number, ship_status="created", order_status="processing", waybill="WB-1"):
    ng = Country.objects.get(code="NG")
    order = Order.objects.create(number=number, email="t@x.com", country=ng,
                                 currency=ng.currency, status=order_status)
    return GigShipment.objects.create(order=order, status=ship_status, waybill=waybill,
                                      charged=Decimal("4175.20"))


def post(client, body):
    return client.post(reverse("gig-webhook"), data=body, content_type="text/plain")


def test_decrypt_round_trip_and_wrong_secret():
    payload = event()
    assert decrypt_payload(encrypt(payload, SECRET), SECRET) == payload
    with pytest.raises(InvalidWebhookPayload):
        decrypt_payload(encrypt(payload, SECRET), "not-the-secret")
    with pytest.raises(InvalidWebhookPayload):
        decrypt_payload("definitely not base64!!!", SECRET)
    with pytest.raises(InvalidWebhookPayload):
        decrypt_payload(base64.b64encode(b"short").decode(), SECRET)


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_movement_event_ships_the_order(client, django_capture_on_commit_callbacks):
    shipment = _shipment("TC-920001")
    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, encrypt(event(code="MAHD"), SECRET))

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    shipment.refresh_from_db()
    assert shipment.status == "in_transit"
    assert shipment.order.status == "shipped"
    # Stored verbatim — the admin panel shows this raw, the storefront picks
    # Location/Status out of it.
    assert shipment.last_scan["StatusCode"] == "MAHD"
    assert shipment.last_scan["Status"] == "SHIPMENT PICKED UP"
    assert shipment.last_tracked_at is not None


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_delivery_event_delivers(client, django_capture_on_commit_callbacks):
    shipment = _shipment("TC-920002", ship_status="in_transit", order_status="shipped")
    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, encrypt(event(code="DLP", status_text="DELIVERED"), SECRET))

    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "delivered"
    assert shipment.order.status == "delivered"


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_created_code_moves_nothing(client):
    shipment = _shipment("TC-920003")
    response = post(client, encrypt(event(code="MCRT", status_text="SHIPMENT CREATED"), SECRET))
    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == "created"
    assert shipment.order.status == "processing"
    assert shipment.last_scan["StatusCode"] == "MCRT"  # the scan still lands


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_garbage_and_wrong_secret_are_400_and_touch_nothing(client):
    shipment = _shipment("TC-920004")
    assert post(client, "not base64 at all").status_code == 400
    assert post(client, encrypt(event(), "attacker-guess")).status_code == 400
    shipment.refresh_from_db()
    assert shipment.status == "created"
    assert shipment.last_scan == {}


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_unknown_waybill_acks_200(client):
    response = post(client, encrypt(event(waybill="NO-SUCH"), SECRET))
    assert response.status_code == 200  # retrying an unmatchable waybill can't help


@override_settings(GIG_WEBHOOK_SECRET=SECRET)
def test_json_quoted_body_is_tolerated(client):
    shipment = _shipment("TC-920005")
    response = post(client, json.dumps(encrypt(event(code="MCRT"), SECRET)))
    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.last_scan["StatusCode"] == "MCRT"


@override_settings(GIG_WEBHOOK_SECRET="")
def test_unconfigured_secret_is_503(client):
    assert post(client, encrypt(event(), SECRET)).status_code == 503
