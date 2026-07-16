import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.factories import CouponFactory
from apps.checkout.models import CouponRedemption
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.services import mark_paid

pytestmark = pytest.mark.django_db


def _setup():
    # Seed migration already created NG + NGN — fetch, don't re-create (avoids PK collision).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    return ng, ngn, variant


def test_mark_paid_commits_stock_and_flags_processing():
    ng, ngn, variant = _setup()
    order = OrderFactory(number="TC-100001", country=ng, currency=ngn,
                         reservation_reference="TC-100001", grand_total="1000.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-100001")
    payment = PaymentFactory(order=order, currency=ngn, status="initiated")

    mark_paid(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == "succeeded"
    assert order.status == "processing"
    # stock committed: on-hand dropped 10 → 8, reserved back to 0.
    si = variant.stock_items.get()
    assert si.quantity == 8 and si.reserved == 0
    # fulfillment recorded on the item.
    assert OrderItem.objects.get(order=order).fulfillment_warehouses == {"Lagos HQ": 2}


def test_mark_paid_writes_coupon_redemption():
    ng, ngn, variant = _setup()
    coupon = CouponFactory(code="TEN", type="percent", value="10.00")
    order = OrderFactory(number="TC-100002", country=ng, currency=ngn,
                         reservation_reference="TC-100002", coupon=coupon,
                         email="c@x.com", grand_total="900.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-100002")
    mark_paid(PaymentFactory(order=order, currency=ngn))

    assert CouponRedemption.objects.filter(coupon=coupon, order_number="TC-100002").exists()


def test_mark_paid_idempotent():
    ng, ngn, variant = _setup()
    order = OrderFactory(number="TC-100003", country=ng, currency=ngn,
                         reservation_reference="TC-100003", grand_total="500.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="500.00", quantity=1)
    reserve(variant, 1, ng, reference="TC-100003")
    p = PaymentFactory(order=order, currency=ngn)
    mark_paid(p)
    mark_paid(p)  # second call must be a no-op
    si = variant.stock_items.get()
    assert si.quantity == 9  # committed once, not twice
