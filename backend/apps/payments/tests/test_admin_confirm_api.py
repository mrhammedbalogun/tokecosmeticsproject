"""The admin confirm-receipt endpoint: the ONLY way a bank-transfer order can ever be
fulfilled. confirm_manual_receipt holds the money-safety rules; these tests pin the HTTP
contract around them — who may call it, and that a refusal comes back as a decision the
UI can act on rather than an opaque failure.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory

pytestmark = pytest.mark.django_db


def _setup(qty=10):
    # Seed migration already created NG + NGN — fetch, don't re-create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    return ng, ngn, variant


def _order_awaiting_transfer(number, ng, ngn, variant):
    """An order sitting exactly where initiate() leaves it: pending_payment, stock held
    under its reservation reference, payment still 'initiated' because no machine can
    confirm it."""
    order = OrderFactory(
        number=number, country=ng, currency=ngn, reservation_reference=number,
        grand_total="10000.00", status="pending_payment", email="c@x.com",
    )
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="5000.00", line_total="10000.00", quantity=2)
    reserve(variant, 2, ng, reference=number)
    return order, PaymentFactory(
        order=order, currency=ngn, amount=Decimal("10000.00"),
        gateway="bank_transfer", status="initiated",
    )


def _url(order):
    return f"/api/v1/admin/orders/{order.number}/confirm-payment/"


def test_staff_confirming_a_transfer_fulfils_the_order(django_user_model):
    ng, ngn, variant = _setup()
    order, _ = _order_awaiting_transfer("TC-310001", ng, ngn, variant)
    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    r = client.post(_url(order),
                    {"amount_received": "10000.00", "bank_reference": "FT001"},
                    format="json")

    assert r.status_code == 200, r.data
    order.refresh_from_db()
    assert order.status == "processing"


def test_a_customer_cannot_declare_their_own_transfer_landed(django_user_model):
    """The whole control is that a human read the bank statement. A customer asserting it
    would be self-service fulfilment for money that never arrived."""
    ng, ngn, variant = _setup()
    order, _ = _order_awaiting_transfer("TC-310002", ng, ngn, variant)
    user = django_user_model.objects.create_user(email="nobody@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)

    r = client.post(_url(order),
                    {"amount_received": "10000.00", "bank_reference": "FT002"},
                    format="json")

    assert r.status_code == 403
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_a_discrepancy_comes_back_with_the_numbers_the_ui_must_show(django_user_model):
    """Not a system error — a decision the human must make. The "are you sure?" prompt is
    built from this body, so the two numbers have to be in it."""
    ng, ngn, variant = _setup()
    order, _ = _order_awaiting_transfer("TC-310003", ng, ngn, variant)
    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    r = client.post(_url(order),
                    {"amount_received": "6000.00", "bank_reference": "FT003"},
                    format="json")

    assert r.status_code == 400, r.data
    assert r.data["code"] == "amount_discrepancy"
    assert r.data["expected"] == "10000.00"
    assert r.data["received"] == "6000.00"
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_one_statement_line_cannot_release_two_orders(django_user_model):
    ng, ngn, variant = _setup(qty=20)
    first, _ = _order_awaiting_transfer("TC-310004", ng, ngn, variant)
    second, _ = _order_awaiting_transfer("TC-310005", ng, ngn, variant)
    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)

    first_response = client.post(_url(first),
                                 {"amount_received": "10000.00", "bank_reference": "FT-DUP"},
                                 format="json")
    assert first_response.status_code == 200, first_response.data

    r = client.post(_url(second),
                    {"amount_received": "10000.00", "bank_reference": "FT-DUP"},
                    format="json")

    assert r.status_code == 409, r.data
    second.refresh_from_db()
    assert second.status == "pending_payment"
