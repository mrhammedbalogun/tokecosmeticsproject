"""The tracking poll and the wallet monitor (Plan-32a slice 6).

The poll's contract: known codes move the shipment and TRY to move the order
(never argue with a human who got there first); unknown codes update the scan
verbatim and move nothing; the label URL is harvested the moment GIG's response
grows one. The monitor's contract: alert on the crossing into low, once, and
re-arm on recovery — unknown is not low."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.core.models import Country, SiteSetting
from apps.delivery.gig import client
from apps.delivery.models import GigShipment
from apps.delivery.tasks import _WALLET_ALERT_STATE_KEY, monitor_gig_wallet, poll_gig_tracking
from apps.orders.models import Order

BASE = "https://gig.test"
SETTINGS = dict(GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw",
                GIG_WALLET_ALERT_THRESHOLD=50_000)

pytestmark = pytest.mark.django_db


def _envelope(data):
    return {"message": "Success", "apiId": "trk-1", "status": 200, "data": data}


def _entry(waybill, code, label=None, when="2026-08-02 18:00:00 WAT"):
    return {
        "Waybill": waybill, "WaybillLabel": label, "Amount": 2691.11,
        "MobileShipmentTrackings": [
            {"Status": "MCRT", "DateTime": "2026-08-02 08:00:00 WAT"},
            {"Status": code, "DateTime": when, "Location": "GBAGADA"},
        ],
    }


@pytest.fixture(autouse=True)
def _token():
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)
    yield
    cache.clear()


def _shipment(number, ship_status="created", order_status="processing", waybill="WB1"):
    ng = Country.objects.get(code="NG")
    order = Order.objects.create(number=number, email="t@x.com", country=ng,
                                 currency=ng.currency, status=order_status)
    return GigShipment.objects.create(order=order, status=ship_status, waybill=waybill,
                                      charged=Decimal("4175.20"))


@override_settings(**SETTINGS)
@respx.mock
def test_movement_ships_the_order_and_dlp_delivers_it(django_capture_on_commit_callbacks):
    moving = _shipment("TC-910001", waybill="WB-A")
    arriving = _shipment("TC-910002", ship_status="in_transit", order_status="shipped", waybill="WB-B")
    route = respx.post(f"{BASE}/track/multipleMobileShipment").mock(
        return_value=httpx.Response(200, json=_envelope([
            _entry("WB-A", "MAHD"), _entry("WB-B", "DLP"),
        ]))
    )
    with django_capture_on_commit_callbacks(execute=True):
        counts = poll_gig_tracking.apply().result

    assert counts == {"polled": 2, "in_transit": 1, "delivered": 1, "scan_only": 0}
    import json as jsonlib

    sent = jsonlib.loads(route.calls[0].request.content)
    assert sorted(sent["Waybill"]) == ["WB-A", "WB-B"]  # the measured batch shape

    moving.refresh_from_db(); arriving.refresh_from_db()
    assert moving.status == "in_transit"
    assert moving.order.status == "shipped"
    assert moving.last_scan["Status"] == "MAHD"  # newest by DateTime, verbatim
    assert arriving.status == "delivered"
    assert arriving.order.status == "delivered"


@override_settings(**SETTINGS)
@respx.mock
def test_unknown_codes_update_the_scan_and_move_nothing():
    s = _shipment("TC-910003", ship_status="in_transit", order_status="shipped")
    respx.post(f"{BASE}/track/multipleMobileShipment").mock(
        return_value=httpx.Response(200, json=_envelope([_entry("WB1", "ZZZZ-NEW-CODE")]))
    )
    counts = poll_gig_tracking.apply().result
    assert counts["scan_only"] == 1
    s.refresh_from_db()
    assert s.status == "in_transit"           # unmoved
    assert s.order.status == "shipped"        # unmoved
    assert s.last_scan["Status"] == "ZZZZ-NEW-CODE"  # but the truth is stored


@override_settings(**SETTINGS)
@respx.mock
def test_label_is_harvested_and_a_human_moved_order_is_not_argued_with(django_capture_on_commit_callbacks):
    # Admin already marked the order delivered; GIG's DLP scan arrives later.
    s = _shipment("TC-910004", ship_status="in_transit", order_status="delivered")
    respx.post(f"{BASE}/track/multipleMobileShipment").mock(
        return_value=httpx.Response(200, json=_envelope([
            _entry("WB1", "DLP", label="https://s3.example/wb1.png"),
        ]))
    )
    with django_capture_on_commit_callbacks(execute=True):
        counts = poll_gig_tracking.apply().result
    assert counts["delivered"] == 1
    s.refresh_from_db()
    assert s.status == "delivered"                      # shipment truth updated
    assert s.order.status == "delivered"                # order untouched, no error
    assert s.label_url == "https://s3.example/wb1.png"  # harvested from the poll


@override_settings(**SETTINGS)
@respx.mock
def test_outage_skips_the_pass_without_touching_shipments():
    s = _shipment("TC-910005")
    respx.post(f"{BASE}/track/multipleMobileShipment").mock(side_effect=httpx.ConnectError("down"))
    result = poll_gig_tracking.apply().result
    assert "skipped" in result
    s.refresh_from_db()
    assert s.last_tracked_at is None  # nothing pretended to have polled


@override_settings(**SETTINGS)
@respx.mock
def test_wallet_alert_fires_on_the_crossing_only_and_rearms_on_recovery():
    # The alert is addressed to the "GIG wallet running low" list on the Email
    # Notifications screen (`apps/notifications/events.py`) rather than to
    # `DEFAULT_FROM_EMAIL`, which had no inbox. This test is about the CROSSING logic,
    # not about who hears it, so it needs one subscriber to have anything to count.
    from apps.notifications.models import NotificationRecipient

    NotificationRecipient.objects.create(event="delivery.gig_wallet_low",
                                         email="ops@x.com")

    def balance_response(amount):
        return httpx.Response(200, json=_envelope({"data": [{"WalletAmount": amount}]}))

    route = respx.get(f"{BASE}/companyDetails/get").mock(return_value=balance_response(10_000))
    r1 = monitor_gig_wallet.apply().result
    assert r1["alerted"] is True
    assert len(mail.outbox) == 1
    assert "GIG wallet low" in mail.outbox[0].subject

    r2 = monitor_gig_wallet.apply().result  # still low: no second email
    assert r2["alerted"] is False
    assert len(mail.outbox) == 1

    route.return_value = balance_response(90_000)  # recovered: re-arms
    monitor_gig_wallet.apply()
    route.return_value = balance_response(10_000)  # crosses again: alerts again
    r4 = monitor_gig_wallet.apply().result
    assert r4["alerted"] is True
    assert len(mail.outbox) == 2

    state = SiteSetting.objects.get(key=_WALLET_ALERT_STATE_KEY)
    assert state.value == "low"


@override_settings(**SETTINGS)
@respx.mock
def test_null_balance_never_alerts():
    respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(200, json=_envelope({"data": [{"WalletAmount": None}]}))
    )
    assert monitor_gig_wallet.apply().result == {"balance": None}
    assert mail.outbox == []


def test_both_tasks_are_on_the_beat_schedule():
    from django.conf import settings as dj

    tasks = {entry["task"] for entry in dj.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.delivery.tasks.poll_gig_tracking" in tasks
    assert "apps.delivery.tasks.monitor_gig_wallet" in tasks
