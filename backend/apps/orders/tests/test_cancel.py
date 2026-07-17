"""Cancelling an order. The stock release is the whole point: expire_pending_orders only
ever sweeps `pending_payment`, so a cancelled order that keeps its reservation holds that
stock away from real buyers forever, with nothing left in the system to reclaim it."""
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.orders.services import cancel_order
from apps.orders.state import IllegalTransition

pytestmark = pytest.mark.django_db


def _reserved_order(number="TC-400001", status="pending_payment", qty=2):
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    order = OrderFactory(number=number, country=ng, currency=ng.currency, status=status,
                         reservation_reference=number)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=qty)
    reserve(variant, qty, ng, reference=number)
    return order, variant


def test_cancelling_a_pending_order_releases_its_reservation():
    order, variant = _reserved_order()
    assert variant.stock_items.get().reserved == 2

    cancel_order(order.pk, message="customer changed their mind")

    order.refresh_from_db()
    assert order.status == "cancelled"
    si = variant.stock_items.get()
    assert si.reserved == 0  # freed for real buyers
    assert si.quantity == 10  # never sold — on-hand untouched


def test_cancelling_writes_the_reason_to_the_timeline(django_user_model):
    staff = django_user_model.objects.create_user(email="ops2@x.com", password="x")
    order, _ = _reserved_order(number="TC-400002")

    cancel_order(order.pk, actor=staff, message="duplicate of TC-400001")

    event = order.events.get(type="status:cancelled")
    assert event.actor == staff
    assert event.message == "duplicate of TC-400001"


def test_cancelling_a_paid_order_is_refused_and_frees_nothing():
    """`cancelled` means no money was ever captured — a paid order exits via `refunded`.
    Critically the refusal must leave the stock committed: a cancel that released stock
    it had already SOLD would let the same unit be sold twice."""
    order, variant = _reserved_order(number="TC-400003", status="processing")
    before = variant.stock_items.get().reserved

    with pytest.raises(IllegalTransition):
        cancel_order(order.pk)

    order.refresh_from_db()
    assert order.status == "processing"
    assert variant.stock_items.get().reserved == before


def test_cancelling_twice_is_refused_not_double_released():
    order, variant = _reserved_order(number="TC-400004")
    cancel_order(order.pk)

    with pytest.raises(IllegalTransition):
        cancel_order(order.pk)

    assert variant.stock_items.get().reserved == 0  # not driven negative
