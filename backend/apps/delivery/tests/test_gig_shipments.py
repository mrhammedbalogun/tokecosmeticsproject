"""GigShipment lifecycle (Plan-32a slice 4): born quoted with the order,
abandoned when the order dies BEFORE capture, untouched when it dies after —
the waybill and wallet debit are reconciliation facts, not order state."""
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Country
from apps.delivery.gig.shipments import abandon_quoted_shipment, create_quoted_shipment
from apps.delivery.models import GigShipment
from apps.orders.models import Order
from apps.orders.state import transition
from django.db import transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def order(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="s4@x.com", password="pw")
    return Order.objects.create(
        number="TC-900001", user=user, email=user.email, country=ng, currency=ng.currency,
        status="pending_payment", grand_total=Decimal("19175.20"),
        shipping_total=Decimal("4175.20"),
    )


def _quoted(order, status="quoted"):
    return GigShipment.objects.create(
        order=order, status=status, charged=Decimal("4175.20"),
        quote={"price": "4175.20", "breakdown": {"GrandTotal": 4175.2}, "api_id": "q-1"},
    )


def test_placement_snapshot_survives_a_cache_miss(order):
    shipment = create_quoted_shipment(order, {"carrier_quote_key": "gig:quote:v1:gone:1"},
                                      charged=Decimal("4175.20"))
    assert shipment.status == "quoted"
    assert shipment.quote == {}  # empty, logged — capture re-quotes before debiting
    assert shipment.charged == Decimal("4175.20")


@pytest.mark.parametrize("dead_status", ["cancelled", "expired"])
def test_order_dying_before_capture_abandons_the_quoted_shipment(order, dead_status, django_capture_on_commit_callbacks):
    _quoted(order)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            transition(order, dead_status)
    shipment = GigShipment.objects.get(order=order)
    assert shipment.status == "abandoned"


def test_order_refunded_after_capture_keeps_the_shipment_state(order):
    _quoted(order, status="created")
    GigShipment.objects.filter(order=order).update(
        waybill="1349113095", cost=Decimal("4175.20")
    )
    # Walk the legal path to refunded: pending_payment -> processing -> shipped -> refunded.
    with transaction.atomic():
        transition(order, "processing")
        transition(order, "shipped")
        transition(order, "refunded")
    shipment = GigShipment.objects.get(order=order)
    assert shipment.status == "created"       # NOT abandoned
    assert shipment.waybill == "1349113095"   # the debit happened; the trail stays true


def test_abandon_is_a_noop_for_orders_without_a_gig_shipment(order):
    abandon_quoted_shipment(order.pk)  # must not raise
    assert not GigShipment.objects.filter(order=order).exists()


def test_placement_lifts_the_origin_snapshot_from_the_cached_quote(order):
    """Plan-34 ruling 3: the sender origin the quote priced from becomes
    GigShipment.origin, so capture ships from exactly what was priced."""
    from django.core.cache import cache

    origin = {"id": 2, "name": "Kubwa (Abuja)", "phone": "+2347074800702",
              "address": "Shop 7, Lane 3, Building Materials Market, Kubwa, FCT",
              "locality": "Kubwa", "latitude": 9.138, "longitude": 7.322}
    key = "gig:quote:v2:2:99:1"
    cache.set(key, {"price": "4175.20", "breakdown": {"GrandTotal": 4175.2},
                    "api_id": "q-1", "origin": origin}, 60)
    shipment = create_quoted_shipment(order, {"carrier_quote_key": key},
                                      charged=Decimal("4175.20"))
    assert shipment.origin == origin
    cache.delete(key)


def test_placement_cache_miss_leaves_the_origin_empty(order):
    shipment = create_quoted_shipment(order, {"carrier_quote_key": "gig:quote:v2:0:gone:1"},
                                      charged=Decimal("4175.20"))
    assert shipment.origin == {}  # capture falls back to the env origin
