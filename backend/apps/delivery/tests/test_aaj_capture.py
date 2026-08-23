"""AAJ capture (Plan-43): create-booking is free and records the real cost;
process-booking is the money call, gated by the kill-switch, and EVERY non-success
is reconciled against get-booking before the shipment is parked anywhere; void
reverses and clears the order's tracking; the abandon lane releases `booked` rows
and queues the booking delete."""
import json
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.core.models import Country
from apps.delivery.aaj.capture import (
    CaptureRefused,
    CaptureUnconfirmed,
    can_void,
    capture_shipment,
    check_unconfirmed,
    sanitise_name,
    void_shipment,
)
from apps.delivery.aaj.shipments import abandon_quoted_shipment, create_quoted_shipment
from apps.delivery.models import AajShipment, SenderLocation
from apps.orders.models import Order, OrderEvent

BASE = "https://aaj.test/api/v2"
SETTINGS = dict(
    AAJ_BASE_URL=BASE, AAJ_API_KEY="aaj-testkey", AAJ_ACCOUNT_NUMBER="657357",
    AAJ_PAYMENT_METHOD="CREDIT_FACILITY", AAJ_CATEGORY_ID="cat-non-electronics",
    AAJ_SENDER_EMAIL="orders@toke.test", AAJ_SENDER_POSTAL_CODE="100001",
    AAJ_PROCESS_ENABLED=True,
)
CREATE = f"{BASE}/partner/booking/create-booking"
PROCESS = f"{BASE}/partner/booking/process-booking/bk-1"
GET_BOOKING = f"{BASE}/partner/booking/get-booking/bk-1"

pytestmark = pytest.mark.django_db


def _ok(data, message="ok", http=200):
    return httpx.Response(http, json={"success": True, "data": data, "status": http, "message": message})


def _create_resp(total=2392, booking_id="bk-1"):
    return _ok({"booking": {"_id": booking_id, "totalAmount": total, "paid": False,
                            "bookingStatus": "BOOKED", "searchId": "62001515"},
                "quote": {"total": total, "subTotal": 2225, "tax": 166.875,
                          "eta": {"numberOfDays": 2}}}, http=201)


def _process_resp(tracking="D276AA3D", label="https://aaj-media.test/labels/x/D276AA3D_AAJ_label.pdf"):
    return _ok({"payload": {"shipment": {"tracking_id": tracking,
                                         "labelDocuments": [{"carrier": "AAJ", "url": label}],
                                         "parkingListDocuments": [], "status": "0"}}},
               message="Booking processed successfully")


def _booking_read(paid, shipment_id=""):
    return _ok({"foundBooking": {"_id": "bk-1", "paid": paid, "shipmentId": shipment_id,
                                 "totalAmount": 2392}, "quote": {}, "meta": {}})


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def order(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="ada.obi@x.com", password="pw")
    return Order.objects.create(
        number="TC-900200", user=user, email=user.email, phone="+2348000000002",
        country=ng, currency=ng.currency,
        status="processing", subtotal=Decimal("15000.00"), shipping_total=Decimal("2779.00"),
        grand_total=Decimal("17779.00"),
        shipping_address={"first_name": "Adéolá", "last_name": "O'Brien-Smith",
                          "phone": "+2348000000002", "line1": "12 Allen Ave", "line2": "",
                          "state": "Lagos", "area": "Ikeja", "country_code": "NG"},
    )


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.get(email="ada.obi@x.com")


@pytest.fixture
def quoted(order):
    origin = SenderLocation.objects.get(is_active=True)
    return AajShipment.objects.create(
        order=order, status="quoted", charged=Decimal("2779.00"), quote_total=Decimal("2779.00"),
        quote={"price": "2779.00", "breakdown": {"total": 2779}, "eta_days": 2},
        origin={"id": origin.pk, "name": "Ogudu Mall (Lagos)", "phone": "+2347074800702",
                "address": "Shop No 1, Ogudu Mall, Kosofe, Ogudu, Lagos", "locality": "Ogudu",
                "state_name": "Lagos", "state_code": "LA", "postal_code": "100001",
                "latitude": 6.576522, "longitude": 3.389387},
    )


# --- field shaping -----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Adéolá O'Brien-Smith", "Adeola O Brien Smith"),
    ("  Ada   Obi ", "Ada Obi"),
    ("A" * 80, "A" * 50),
    ("!!", "ada obi"),  # falls to the email local part, punctuation -> space
])
def test_sanitise_name_folds_diacritics_spaces_punctuation_and_falls_back(raw, expected):
    assert sanitise_name(raw, "ada.obi") == expected


def test_sanitise_name_last_resort_is_customer():
    assert sanitise_name("", "", None) == "Customer"


# --- the happy path ----------------------------------------------------------------

@override_settings(**SETTINGS)
@respx.mock
def test_capture_creates_then_processes_and_stamps_both_rows(order, quoted, actor):
    create = respx.post(CREATE).mock(return_value=_create_resp())
    process = respx.post(PROCESS).mock(return_value=_process_resp())

    shipment = capture_shipment(order, actor=actor)

    assert shipment.status == "created"
    assert shipment.booking_id == "bk-1" and shipment.tracking_id == "D276AA3D"
    assert shipment.cost == Decimal("2392.00")  # the ACCOUNT rate, below the ₦2,779 retail quote
    assert shipment.label_url.endswith("D276AA3D_AAJ_label.pdf")
    order.refresh_from_db()
    assert (order.tracking_carrier, order.tracking_number) == ("AAJ", "D276AA3D")
    messages = list(OrderEvent.objects.filter(order=order, type="aaj").values_list("message", flat=True))
    assert any("booking bk-1 created at ₦2392.00" in m and "margin ₦387.00" in m for m in messages)
    assert any("shipment D276AA3D created" in m for m in messages)

    sent = json.loads(create.calls[0].request.read())
    assert sent["receiver"]["contact"] == {"name": "Adeola O Brien Smith", "phone": "+2348000000002",
                                           "email": "ada.obi@x.com"}
    assert sent["receiver"]["addressDetails"]["stateOrProvinceCode"] == "LA"
    assert sent["receiver"]["addressDetails"]["city"] == "Ikeja"
    assert sent["receiver"]["addressDetails"]["addressLine1"] == "12 Allen Ave"
    assert sent["sender"]["addressDetails"]["stateOrProvinceCode"] == "LA"
    assert sent["sender"]["addressDetails"]["postalCode"] == "100001"
    assert sent["sender"]["contact"]["email"] == "orders@toke.test"
    assert sent["payments"] == {"accountNumber": "657357",
                                "transaction": {"generateTransaction": True, "method": "CREDIT_FACILITY"}}
    assert sent["category"] == "cat-non-electronics"
    assert sent["customBookingId"] == "TC-900200"
    assert sent["packageInsurance"] == "FR" and sent["serviceType"] == "DOMESTIC"
    assert process.call_count == 1


@override_settings(**SETTINGS)
@respx.mock
def test_refusals_happen_before_any_call(order, quoted, actor):
    create = respx.post(CREATE).mock(return_value=_create_resp())
    Order.objects.filter(pk=order.pk).update(status="pending_payment")
    order.refresh_from_db()
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "order_not_paid"

    Order.objects.filter(pk=order.pk).update(status="processing")
    order.refresh_from_db()
    order.shipping_address = {**order.shipping_address, "state": "Atlantis"}
    order.save(update_fields=["shipping_address"])
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "state_unmapped"
    assert create.call_count == 0


@override_settings(**{**SETTINGS, "AAJ_PROCESS_ENABLED": False})
@respx.mock
def test_kill_switch_stops_after_the_free_step(order, quoted, actor):
    respx.post(CREATE).mock(return_value=_create_resp())
    process = respx.post(PROCESS).mock(return_value=_process_resp())
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "process_disabled"
    quoted.refresh_from_db()
    assert quoted.status == "booked" and quoted.booking_id == "bk-1" and quoted.cost == Decimal("2392.00")
    assert process.call_count == 0


@override_settings(**SETTINGS)
@respx.mock
def test_recapture_from_booked_never_creates_a_second_booking(order, quoted, actor):
    create = respx.post(CREATE).mock(return_value=_create_resp())
    respx.post(PROCESS).mock(return_value=_process_resp())
    AajShipment.objects.filter(pk=quoted.pk).update(status="booked", booking_id="bk-1", cost=Decimal("2392.00"))
    order.refresh_from_db()
    shipment = capture_shipment(order, actor=actor)
    assert shipment.status == "created" and create.call_count == 0


@override_settings(**SETTINGS)
@respx.mock
def test_create_timeout_stays_quoted_and_is_retryable(order, quoted, actor):
    respx.post(CREATE).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "create_timeout"
    quoted.refresh_from_db()
    assert quoted.status == "quoted" and quoted.booking_id == ""


# --- the reconcile lane: every non-success re-reads get-booking --------------------

@override_settings(**SETTINGS)
@respx.mock
def test_refusal_with_nothing_charged_stays_booked_and_surfaces_the_reason(order, quoted, actor):
    respx.post(CREATE).mock(return_value=_create_resp())
    respx.post(PROCESS).mock(return_value=httpx.Response(400, json={
        "success": False, "message": "Credit facility cannot be charged", "status": 400}))
    read = respx.get(GET_BOOKING).mock(return_value=_booking_read(paid=False))
    with pytest.raises(CaptureRefused) as exc:
        capture_shipment(order, actor=actor)
    assert exc.value.code == "process_refused" and "Credit facility" in exc.value.detail
    assert read.call_count == 1
    quoted.refresh_from_db()
    assert quoted.status == "booked"


@override_settings(**SETTINGS)
@respx.mock
def test_timeout_that_actually_charged_resolves_to_created(order, quoted, actor):
    respx.post(CREATE).mock(return_value=_create_resp())
    respx.post(PROCESS).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get(GET_BOOKING).mock(return_value=_booking_read(paid=True, shipment_id="sh-1"))
    respx.get(f"{BASE}/partner/shipment/get-single-shipment/sh-1").mock(return_value=_ok({
        "_id": "sh-1", "trackingId": "D276AA3D", "status": 0,
        "labelDocuments": [{"carrier": "AAJ", "url": "https://aaj-media.test/l.pdf"}]}))
    shipment = capture_shipment(order, actor=actor)
    assert shipment.status == "created" and shipment.tracking_id == "D276AA3D"
    assert shipment.aaj_shipment_id == "sh-1" and shipment.label_url == "https://aaj-media.test/l.pdf"
    order.refresh_from_db()
    assert order.tracking_number == "D276AA3D"


@override_settings(**SETTINGS)
@respx.mock
def test_the_measured_half_state_parks_unconfirmed(order, quoted, actor):
    # MEASURED: HTTP 500 "cannot be charged" yet a shipment record exists, booking unpaid.
    respx.post(CREATE).mock(return_value=_create_resp())
    respx.post(PROCESS).mock(return_value=httpx.Response(500, json={
        "success": False, "message": "Credit facility cannot be charged", "status": 500}))
    respx.get(GET_BOOKING).mock(return_value=_booking_read(paid=False, shipment_id="sh-ghost"))
    with pytest.raises(CaptureUnconfirmed):
        capture_shipment(order, actor=actor)
    quoted.refresh_from_db()
    assert quoted.status == "create_unconfirmed"
    assert OrderEvent.objects.filter(order=order, message__contains="UNCONFIRMED").exists()


@override_settings(**SETTINGS)
@respx.mock
def test_unreadable_booking_after_failure_parks_unconfirmed_and_check_heals_it(order, quoted, actor):
    respx.post(CREATE).mock(return_value=_create_resp())
    respx.post(PROCESS).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get(GET_BOOKING).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(CaptureUnconfirmed):
        capture_shipment(order, actor=actor)
    quoted.refresh_from_db()
    assert quoted.status == "create_unconfirmed"

    # Later, AAJ answers: the staff check (or the poll) settles it without processing.
    respx.get(GET_BOOKING).mock(return_value=_booking_read(paid=True, shipment_id="sh-1"))
    respx.get(f"{BASE}/partner/shipment/get-single-shipment/sh-1").mock(
        return_value=_ok({"_id": "sh-1", "trackingId": "D276AA3D", "labelDocuments": []}))
    assert check_unconfirmed(order, actor=actor) == "created"
    quoted.refresh_from_db()
    assert quoted.status == "created" and quoted.tracking_id == "D276AA3D"


# --- void ----------------------------------------------------------------------------

@override_settings(**SETTINGS)
@respx.mock
def test_void_reverses_clears_tracking_and_allows_a_fresh_capture(order, quoted, actor):
    respx.post(CREATE).mock(side_effect=[_create_resp(), _create_resp(booking_id="bk-2")])
    respx.post(PROCESS).mock(return_value=_process_resp())
    capture_shipment(order, actor=actor)
    void = respx.delete(f"{BASE}/partner/shipment/void-shipment/D276AA3D").mock(
        return_value=_ok({"message": "Shipment voided"}, message="Success"))

    shipment = void_shipment(order, actor=actor)
    assert shipment.status == "voided" and void.call_count == 1
    order.refresh_from_db()
    assert (order.tracking_carrier, order.tracking_number) == ("", "")

    # Re-capture books afresh (a second create), replacing the voided ids.
    respx.post(f"{BASE}/partner/booking/process-booking/bk-2").mock(
        return_value=_process_resp(tracking="NEW00001"))
    shipment = capture_shipment(order, actor=actor)
    assert shipment.status == "created" and shipment.booking_id == "bk-2"
    assert shipment.tracking_id == "NEW00001"
    assert OrderEvent.objects.filter(order=order, message__contains="replaces voided shipment D276AA3D").exists()


def test_can_void_follows_aajs_first_hub_scan_rule(order, quoted):
    quoted.status = "created"
    assert can_void(quoted) == (True, "")
    quoted.status = "in_transit"
    quoted.last_scan = {"scanType": "PICKUP_SCAN"}
    assert can_void(quoted)[0] is True
    quoted.last_scan = {"scanType": "ORIGIN_SCAN"}
    assert can_void(quoted)[0] is False
    quoted.status = "delivered"
    assert can_void(quoted)[0] is False


# --- placement + abandon -------------------------------------------------------------

def test_create_quoted_shipment_snapshots_the_cached_quote_and_origin(order):
    cache.set("aaj:quote:v1:1:2:1", {"price": "2779.00", "breakdown": {"total": 2779},
                                     "eta_days": 2, "origin": {"id": 1, "state_code": "LA"}}, 60)
    shipment = create_quoted_shipment(order, {"carrier_quote_key": "aaj:quote:v1:1:2:1"},
                                      charged=Decimal("0.00"))
    assert shipment.status == "quoted" and shipment.quote_total == Decimal("2779.00")
    assert shipment.charged == Decimal("0.00") and shipment.origin == {"id": 1, "state_code": "LA"}


def test_abandon_releases_quoted_and_booked_and_queues_the_booking_delete(order, quoted):
    AajShipment.objects.filter(pk=quoted.pk).update(status="booked", booking_id="bk-1")
    with mock.patch("apps.delivery.tasks.delete_aaj_booking.delay") as delay:
        abandon_quoted_shipment(order.pk)
    quoted.refresh_from_db()
    assert quoted.status == "abandoned"
    delay.assert_called_once_with(quoted.pk, "bk-1")

    # A shipment that reached the charge keeps its state: the trail must not be falsified.
    AajShipment.objects.filter(pk=quoted.pk).update(status="created", tracking_id="X")
    with mock.patch("apps.delivery.tasks.delete_aaj_booking.delay") as delay:
        abandon_quoted_shipment(order.pk)
    quoted.refresh_from_db()
    assert quoted.status == "created" and delay.call_count == 0
