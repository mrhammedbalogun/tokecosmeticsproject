from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def test_existing_payments_default_to_goods():
    """The default MUST be goods, not null: any .payments read this task missed keeps
    its current meaning by default. Fails safe."""
    assert Payment._meta.get_field("purpose").default == "goods"


def _confirmable_order(number, ng, ngn, variant):
    order = OrderFactory(number=number, country=ng, currency=ngn,
                         reservation_reference=number, grand_total="5000.00",
                         status="pending_payment", email="c@x.com")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="2500.00", line_total="5000.00", quantity=2)
    reserve(variant, 2, ng, reference=number)
    return order


def test_confirm_view_never_picks_a_freight_payment(django_user_model):
    """views confirm selects the NEWEST bank_transfer payment. A freight row is newer
    than the goods row, so without scoping, staff clicking 'confirm payment' would
    confirm freight against the goods total."""
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)

    order = _confirmable_order("TC-700001", ng, ngn, variant)
    goods = Payment.objects.create(
        order=order, gateway="bank_transfer", amount=Decimal("5000.00"),
        currency=ngn, status="initiated", idempotency_key="k-goods", purpose="goods",
    )
    freight = Payment.objects.create(
        order=order, gateway="bank_transfer", amount=Decimal("40.00"),
        currency=ngn, status="succeeded", idempotency_key="k-freight",
        gateway_reference="FREIGHT-REF", purpose="freight",
    )
    assert freight.pk > goods.pk        # the shadowing precondition

    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    r = client.post(f"/api/v1/admin/orders/{order.number}/confirm-payment/",
                    {"amount_received": "5000.00", "bank_reference": "REF-1"},
                    format="json")

    assert r.status_code == 200, r.data
    goods.refresh_from_db()
    freight.refresh_from_db()
    assert goods.status == "succeeded"          # the GOODS payment was confirmed
    assert freight.amount == Decimal("40.00")   # freight untouched
