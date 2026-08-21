"""PartnerShipment: the placement snapshot, the delivered stamp, the history
backfill, and GET /admin/partner-shipments/ — the GIG deliveries table's sibling
for couriers with no API (BrandnPack).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.apps import apps as live_apps
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country
from apps.delivery.models import DeliveryPartner, PartnerShipment, PartnerZone
from apps.delivery.partners import create_partner_shipment, mark_delivered
from apps.orders.models import Order, OrderEvent
from apps.orders.state import _effects_for

pytestmark = pytest.mark.django_db

BASE = "/api/v1/admin/partner-shipments/"

ADDRESS = {
    "first_name": "Bola", "last_name": "Ade", "phone": "+2348012345678",
    "line1": "12 Sabo Rd", "line2": "", "country_code": "NG",
    "state": "Lagos", "area": "Ikorodu", "postcode": "",
}


def _partner() -> DeliveryPartner:
    return DeliveryPartner.objects.get(code="brandnpack")


def _zone(lcda="Ikorodu Central") -> PartnerZone:
    return PartnerZone.objects.get(partner=_partner(), lcda_name=lcda)


def _order(number: str, *, placed_at=None, status="processing",
           option_name="", shipping=Decimal("0.00")) -> Order:
    ng = Country.objects.get(code="NG")
    return Order.objects.create(
        number=number, email="c@x.com", country=ng, currency=ng.currency,
        status=status, grand_total=Decimal("5000.00"), shipping_total=shipping,
        delivery_option_name=option_name, shipping_address=dict(ADDRESS),
        placed_at=placed_at or timezone.now(),
    )


def _chosen(zone: PartnerZone, price="3300.00") -> dict:
    """The option dict services.py builds — price is POST-MASK on purpose, to prove
    the helper snapshots the raw zone price as cost, not this number."""
    return {
        "id": f"pz:{zone.pk}",
        "name": f"Door Delivery - {zone.lcda_name} ({zone.partner.name})",
        "kind": "partner", "carrier_code": zone.partner.code,
        "carrier_service": "home", "currency": "NGN", "price": price,
        "min_days": zone.min_days, "max_days": zone.max_days,
        "areas_covered": zone.areas_covered,
    }


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


# --- placement snapshot ---------------------------------------------------------


def test_snapshot_takes_raw_zone_price_as_cost_and_charged_separately():
    zone = _zone()
    order = _order("TC-920001")

    shipment = create_partner_shipment(order, _chosen(zone), charged=Decimal("3300.00"))

    assert shipment.partner == zone.partner
    assert shipment.cost == zone.price  # RAW price, not the masked 3300.00
    assert shipment.charged == Decimal("3300.00")
    assert shipment.zone == {
        "id": zone.pk, "lcda": zone.lcda_name, "areas": zone.areas_covered,
        "dispatch_zone": zone.dispatch_zone,
        "min_days": zone.min_days, "max_days": zone.max_days,
    }
    assert shipment.delivered_at is None


def test_vanished_zone_still_records_the_shipment_from_the_option_dict():
    """The race: zone deleted between pricing and placement. The order IS going out
    via the partner — that fact must not depend on a rate-card row."""
    zone = _zone()
    chosen = _chosen(zone)
    chosen["id"] = "pz:999999"  # no such row
    order = _order("TC-920002")

    shipment = create_partner_shipment(order, chosen, charged=Decimal("3300.00"))

    assert shipment.partner == _partner()
    assert shipment.cost is None  # unknowable, never guessed
    assert shipment.zone["lcda"] == zone.lcda_name  # parsed back out of the name
    assert "dispatch_zone" not in shipment.zone  # the dict never carried it


def test_unnameable_partner_records_nothing():
    order = _order("TC-920003")
    chosen = {"id": "pz:999999", "carrier_code": "nobody", "name": "x"}

    assert create_partner_shipment(order, chosen, charged=Decimal("0.00")) is None
    assert not PartnerShipment.objects.filter(order=order).exists()


# --- the delivered stamp --------------------------------------------------------


def test_mark_delivered_stamps_once_and_keeps_the_first_timestamp():
    zone = _zone()
    order = _order("TC-920004")
    shipment = create_partner_shipment(order, _chosen(zone), charged=Decimal("3300.00"))

    mark_delivered(order.pk)
    shipment.refresh_from_db()
    first = shipment.delivered_at
    assert first is not None

    mark_delivered(order.pk)  # legal second pass (on_hold triage) must not restamp
    shipment.refresh_from_db()
    assert shipment.delivered_at == first


def test_delivered_effect_is_wired_into_the_state_machine():
    """The stamp rides the deferred-effects lane, AFTER the customer's email (the
    on_commit ordering note in state.py — a raise must not cost them the email)."""
    effects = _effects_for("delivered")
    assert effects[-1] is mark_delivered
    assert len(effects) == 2


# --- the backfill ---------------------------------------------------------------


def test_backfill_recovers_zone_cost_and_delivered_at_from_the_name_and_timeline():
    from importlib import import_module

    backfill = import_module(
        "apps.delivery.migrations.0020_partnershipment"
    ).backfill_partner_shipments

    zone = _zone()
    order = _order(
        "TC-920005", status="refunded",
        option_name=f"Door Delivery - {zone.lcda_name} (BrandnPack)",
        shipping=Decimal("3000.00"),
    )
    event = OrderEvent.objects.create(order=order, type="status:delivered")
    unmatched = _order(
        "TC-920006", option_name="Door Delivery - Atlantis (BrandnPack)",
        shipping=Decimal("2500.00"),
    )
    _order("TC-920007", option_name="Standard Delivery")  # not a partner order

    backfill(live_apps, None)

    row = PartnerShipment.objects.get(order=order)
    assert row.cost == zone.price
    assert row.zone["id"] == zone.pk
    # Refunded-after-delivery history still answers the invoice question.
    assert row.delivered_at == event.created_at

    ghost = PartnerShipment.objects.get(order=unmatched)
    assert ghost.cost is None
    assert ghost.zone == {"lcda": "Atlantis"}

    assert not PartnerShipment.objects.filter(order__number="TC-920007").exists()

    backfill(live_apps, None)  # re-run must not duplicate (OneToOne would raise)
    assert PartnerShipment.objects.count() == 2


# --- GET /admin/partner-shipments/ ----------------------------------------------


def _shipment(number: str, *, status="processing", placed_at=None, **fields):
    zone = _zone()
    order = _order(number, status=status, placed_at=placed_at)
    shipment = create_partner_shipment(order, _chosen(zone), charged=Decimal("3300.00"))
    if fields:
        for key, value in fields.items():
            setattr(shipment, key, value)
        shipment.save()
    return shipment


def test_requires_staff():
    assert APIClient().get(BASE).status_code in (401, 403)


def test_rows_compose_order_zone_and_money(client):
    _shipment("TC-930001", delivered_at=timezone.now())

    rows = client.get(BASE).data["results"]
    assert len(rows) == 1
    row = rows[0]
    assert row["order_number"] == "TC-930001"
    assert row["status"] == "processing"
    assert row["partner"] == {"code": "brandnpack", "name": "BrandnPack"}
    assert row["lcda"] == "Ikorodu Central"
    assert row["destination"] == "Ikorodu, Lagos"
    assert row["customer_name"] == "Bola Ade"
    assert row["customer_phone"] == "+2348012345678"
    assert row["charged"] == "3300.00"
    assert row["cost"] == "3000.00"
    assert row["delivered_at"] is not None


def test_filters(client):
    early = timezone.now() - timedelta(days=10)
    _shipment("TC-930002", status="shipped", delivered_at=timezone.now())
    _shipment("TC-930003", status="refunded", placed_at=early)

    def numbers(query=""):
        return [r["order_number"] for r in client.get(BASE + query).data["results"]]

    assert numbers("?status=shipped") == ["TC-930002"]
    assert numbers("?delivered=yes") == ["TC-930002"]
    assert numbers("?delivered=no") == ["TC-930003"]
    assert numbers("?partner=brandnpack") == ["TC-930002", "TC-930003"]
    assert numbers("?partner=nobody") == []
    cutoff = (timezone.now() - timedelta(days=5)).date().isoformat()
    assert numbers(f"?placed_after={cutoff}") == ["TC-930002"]
    assert numbers("?placed_after=garbage") == []  # honest empty, not a 500
