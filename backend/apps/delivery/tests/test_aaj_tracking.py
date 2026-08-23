"""The AAJ tracking poll (Plan-43): delivered (4) closes the shipment and the
order; movement codes ship the order once; voided (7) and returned (8) are
terminal for the poll, tell staff, and leave the order to a human; exception and
reweigh tell staff once; the pass stops at the first unreachable call; and
`create_unconfirmed` rows are reconciled by reading, never by re-processing."""
from decimal import Decimal
from unittest import mock

import httpx
import pytest
import respx
from django.test import override_settings

from apps.core.models import Country
from apps.delivery.aaj.tracking import poll_tracking
from apps.delivery.models import AajShipment
from apps.orders.models import Order

BASE = "https://aaj.test/api/v2"
SETTINGS = dict(AAJ_BASE_URL=BASE, AAJ_API_KEY="aaj-testkey")
pytestmark = pytest.mark.django_db


def _track(tracking_id, status, scan_type="LABEL_CREATED", description="", when="2026-08-23T16:06:38.000000+01:00"):
    return httpx.Response(200, json={"success": True, "status": 200, "message": "Shipment tracked successfully",
        "data": {"carrier": "AAJ", "trackingNumber": tracking_id, "status": status,
                 "description": description, "timestamp": "2026-08-23T15:06:38.000Z",
                 "events": [{"scanType": "LABEL_CREATED", "dateTime": "2026-08-23T15:00:00.000000+01:00",
                             "description": "Label documents have been created", "meta": {"status": 0, "location": "Online Branch"}},
                            {"scanType": scan_type, "dateTime": when, "description": description,
                             "meta": {"status": status, "location": "yaba Express Centre"}}]}})


def _url(tid):
    return f"{BASE}/partner/shipment/track-shipment/{tid}?extraDetails=false"


@pytest.fixture
def make(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="t@x.com", password="pw")

    def _make(number, tracking_id, status="created", order_status="processing"):
        order = Order.objects.create(
            number=number, user=user, email=user.email, country=ng, currency=ng.currency,
            status=order_status, subtotal=Decimal("10000.00"), grand_total=Decimal("10000.00"),
            tracking_carrier="AAJ", tracking_number=tracking_id,
            shipping_address={"first_name": "T", "last_name": "U", "state": "Lagos", "area": "Ikeja"},
        )
        return AajShipment.objects.create(order=order, status=status, charged=Decimal("2779.00"),
                                          booking_id="bk", tracking_id=tracking_id, cost=Decimal("2392.00"))
    return _make


@override_settings(**SETTINGS)
@respx.mock
def test_movement_ships_the_order_and_delivery_closes_it(make):
    a = make("TC-1", "AAA00001")
    b = make("TC-2", "BBB00002", status="in_transit", order_status="shipped")
    c = make("TC-3", "CCC00003")  # delivered straight from processing: shipped hop first
    respx.get(_url("AAA00001")).mock(return_value=_track("AAA00001", 1, "ORIGIN_SCAN", "Received at yaba"))
    respx.get(_url("BBB00002")).mock(return_value=_track("BBB00002", 4, "DELIVERY_SCAN", "Shipment has been delivered"))
    respx.get(_url("CCC00003")).mock(return_value=_track("CCC00003", 4, "DELIVERY_SCAN", "Shipment has been delivered"))

    with mock.patch("apps.delivery.aaj.tracking.notify_staff", create=True):
        counts = poll_tracking()
    assert counts["in_transit"] == 1 and counts["delivered"] == 2 and not counts["stopped"]
    for row in (a, b, c):
        row.refresh_from_db()
    assert (a.status, a.order.status) == ("in_transit", "shipped")
    assert a.last_status == 1 and a.last_scan["scanType"] == "ORIGIN_SCAN"
    assert (b.status, b.order.status) == ("delivered", "delivered")
    assert (c.status, c.order.status) == ("delivered", "delivered")


@override_settings(**SETTINGS)
@respx.mock
def test_voided_and_returned_are_terminal_tell_staff_and_leave_the_order(make):
    v = make("TC-4", "VVV00004", status="in_transit", order_status="shipped")
    r = make("TC-5", "RRR00005", status="in_transit", order_status="shipped")
    respx.get(_url("VVV00004")).mock(return_value=_track("VVV00004", 7, "LABEL_CREATED", "Label documents have been created"))
    respx.get(_url("RRR00005")).mock(return_value=_track("RRR00005", 8, "RETURN_SCAN", "Shipment has been returned"))
    with mock.patch("apps.notifications.staff.notify_staff") as notify:
        poll_tracking()
    v.refresh_from_db()
    r.refresh_from_db()
    assert v.status == "voided" and v.order.status == "shipped"
    assert (v.order.tracking_carrier, v.order.tracking_number) == ("", "")  # no live-looking dead line
    assert r.status == "returned" and r.order.status == "shipped"
    assert r.order.tracking_number == "RRR00005"
    reasons = {c.args[1]["reason"] for c in notify.call_args_list}
    assert reasons == {"voided at AAJ's end", "returned to sender"}
    assert all(c.args[0] == "delivery.aaj_attention" for c in notify.call_args_list)

    # Terminal: a second pass does not poll them again.
    with mock.patch("apps.notifications.staff.notify_staff") as notify:
        counts = poll_tracking()
    assert counts["polled"] == 0 and notify.call_count == 0


@override_settings(**SETTINGS)
@respx.mock
def test_exception_and_reweigh_tell_staff_once_without_moving_anything(make):
    e = make("TC-6", "EEE00006", status="in_transit", order_status="shipped")
    route = respx.get(_url("EEE00006")).mock(return_value=_track("EEE00006", 5, "EXCEPTION_SCAN", "There is an exception"))
    with mock.patch("apps.notifications.staff.notify_staff") as notify:
        poll_tracking()
        poll_tracking()  # same code again: no second email
    assert notify.call_count == 1 and notify.call_args.args[1]["reason"] == "exception"
    e.refresh_from_db()
    assert e.status == "in_transit" and e.order.status == "shipped"
    route.mock(return_value=_track("EEE00006", 12, "REWEIGH_SCAN", "Shipment has been reweighed"))
    with mock.patch("apps.notifications.staff.notify_staff") as notify:
        poll_tracking()
    assert notify.call_args.args[1]["reason"] == "reweighed"


@override_settings(**SETTINGS)
@respx.mock
def test_an_outage_stops_the_pass_after_one_call(make):
    for number, tid in (("TC-7", "AAA00007"), ("TC-8", "AAA00008"), ("TC-9", "AAA00009")):
        make(number, tid)
    routes = [respx.get(_url(t)).mock(side_effect=httpx.ConnectError("down")) for t in ("AAA00007", "AAA00008", "AAA00009")]
    counts = poll_tracking()
    assert counts["stopped"] is True
    assert sum(r.call_count for r in routes) == 1


@override_settings(**SETTINGS)
@respx.mock
def test_unconfirmed_rows_are_reconciled_by_reading(make):
    u = make("TC-10", "", status="create_unconfirmed")
    respx.get(f"{BASE}/partner/booking/get-booking/bk").mock(return_value=httpx.Response(200, json={
        "success": True, "status": 200, "message": "ok",
        "data": {"foundBooking": {"_id": "bk", "paid": True, "shipmentId": "sh-9"}}}))
    respx.get(f"{BASE}/partner/shipment/get-single-shipment/sh-9").mock(return_value=httpx.Response(200, json={
        "success": True, "status": 200, "message": "ok",
        "data": {"_id": "sh-9", "trackingId": "HEAL0001", "labelDocuments": []}}))
    process = respx.post(f"{BASE}/partner/booking/process-booking/bk")
    # Once healed it is pollable in the SAME pass — the poll picks it up right away.
    respx.get(_url("HEAL0001")).mock(return_value=_track("HEAL0001", 0))
    counts = poll_tracking()
    assert counts["reconciled"] == 1 and counts["polled"] == 1 and process.call_count == 0
    u.refresh_from_db()
    assert u.status == "created" and u.tracking_id == "HEAL0001"
    assert u.order.tracking_number == "HEAL0001"


@override_settings(**SETTINGS)
@respx.mock
def test_an_admin_already_moved_order_is_not_argued_with(make):
    s = make("TC-11", "AAA00011", status="created", order_status="cancelled")
    respx.get(_url("AAA00011")).mock(return_value=_track("AAA00011", 2, "DEPARTURE_SCAN", "departed"))
    poll_tracking()  # cancelled -> shipped is illegal: logged, skipped, never raised
    s.refresh_from_db()
    assert s.status == "in_transit" and s.order.status == "cancelled"
