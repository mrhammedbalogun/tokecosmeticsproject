import pytest
from datetime import timedelta
from django.utils import timezone

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.tasks import expire_pending_orders
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory

pytestmark = pytest.mark.django_db


def _reserved_order(number, expires_delta):
    # Seed migration already created NG + NGN — fetch, don't re-create (avoids PK collision).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(location_country="NG", priority=1); wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    reserve(variant, 3, ng, reference=number)
    order = OrderFactory(number=number, country=ng, currency=ngn, status="pending_payment",
                         reservation_reference=number,
                         reservation_expires_at=timezone.now() + expires_delta)
    return order, variant


def test_past_due_pending_order_expires_and_releases_stock():
    order, variant = _reserved_order("TC-100001", -timedelta(minutes=1))
    assert variant.stock_items.get().reserved == 3

    n = expire_pending_orders()

    assert n == 1
    order.refresh_from_db()
    assert order.status == "expired"
    assert variant.stock_items.get().reserved == 0  # released


def test_not_yet_due_order_untouched():
    order, variant = _reserved_order("TC-100002", timedelta(minutes=10))
    assert expire_pending_orders() == 0
    order.refresh_from_db()
    assert order.status == "pending_payment"
    assert variant.stock_items.get().reserved == 3
