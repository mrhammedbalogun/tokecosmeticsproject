"""The launch gateway state.

What may still be CONFIRMED — a deactivated gateway must remain able to confirm money
it already took. is_active gates the menu and initiate(); if it ever reached
confirm_payment(), a customer who paid minutes before the deploy would be stranded
holding a charge against an order that can never fulfil.

NOTE: this file originally also pinned "every market offers bank transfer and only bank
transfer" (the 0007 launch state, before the networked gateways' sandbox checkpoint was
driven). Migration 0009_reactivate_online_gateways (Plan-14b) turns Paystack/Flutterwave/
PayPal back on per-country, so that assertion is no longer true and has been REMOVED here
rather than updated — it would just duplicate apps/payments/tests/test_reactivate_gateways.py,
which already asserts the exact post-reactivation menu per country. The confirm-payment
guarantee below is untouched by the reactivation and remains pinned here.
"""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.base import VerifyResult
from apps.payments.gateways.paystack import PaystackGateway
from apps.payments.services import confirm_payment

pytestmark = pytest.mark.django_db


def test_a_deactivated_gateway_can_still_confirm_money_it_took(monkeypatch):
    """paystack is off, but a customer who paid before the deploy must still be fulfilled."""
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)

    order = OrderFactory(
        number="TC-209001", country=ng, currency=ng.currency,
        reservation_reference="TC-209001", grand_total="1000.00",
        status="pending_payment", email="c@x.com",
    )
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-209001")
    payment = PaymentFactory(order=order, currency=ng.currency, gateway="paystack",
                             amount="1000.00")

    monkeypatch.setattr(
        PaystackGateway, "verify",
        lambda self, p: VerifyResult(
            status="succeeded", amount=Decimal(p.amount), currency=p.currency_id, raw={}
        ),
    )

    confirm_payment(payment)

    order.refresh_from_db()
    assert order.status == "processing"


def test_reverse_does_not_reactivate_the_networked_gateways(db):
    """`migrate payments 0006` happens for reasons unrelated to gateways — bisecting a bad
    later migration, an incident rollback. Reverse is a deliberate no-op so that no such
    run can silently put four uncertified gateways back in front of customers.

    Uses the plain `db` fixture, not `transactional_db`: Postgres supports transactional
    DDL, so MigrationExecutor's schema+data changes roll back cleanly with the rest of the
    test's transaction. `transactional_db` was tried here first but its post-test flush
    truncates ALL tables session-wide — including the baseline Country/CountryPaymentGateway
    rows seeded once by data migrations when the test DB was built — and those rows are
    never reseeded (the migrations are already marked applied, so they don't rerun). With a
    second migration-exercising test added in test_reactivate_gateways.py, whichever of the
    two ran second was left with an empty Country table. `db` avoids the flush entirely."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.payments.models import CountryPaymentGateway

    executor = MigrationExecutor(connection)
    executor.migrate([("payments", "0006_bankaccount")])
    try:
        assert not CountryPaymentGateway.objects.filter(
            gateway__in=["paystack", "flutterwave", "stripe", "paypal"], is_active=True
        ).exists()
    finally:
        # Leave the DB at head — later tests in this run share it.
        MigrationExecutor(connection).migrate([("payments", "0009_reactivate_online_gateways")])
