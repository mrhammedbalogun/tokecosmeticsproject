"""Expiry-sweep behaviour that only matters for manual (bank-transfer) orders.

Two separate concerns share this file because they share the same loop:
  * the customer who wired money and whose reservation lapsed must be told, because their
    money may already be sitting in our account;
  * one order the loop cannot understand must not take the sweep — and therefore every
    other due order — down with it.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.catalog.factories import ProductVariantFactory
from apps.checkout import tasks as tasks_module
from apps.checkout.tasks import expire_pending_orders
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def _ng():
    # Seed migration already created NG + NGN — fetch, don't re-create.
    ng = Country.objects.get(code="NG")
    return ng, ng.currency


def _due_order(number, gateway, *, overdue=timedelta(minutes=1)):
    """An order sitting exactly where checkout left it, but past its reservation TTL."""
    ng, ngn = _ng()
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    reserve(variant, 2, ng, reference=number)
    order = OrderFactory(
        number=number, country=ng, currency=ngn, status="pending_payment",
        reservation_reference=number, grand_total="10000.00", email="c@x.com",
        reservation_expires_at=timezone.now() - overdue,
    )
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="5000.00", line_total="10000.00", quantity=2)
    PaymentFactory(order=order, currency=ngn, amount=Decimal("10000.00"),
                   gateway=gateway, status="initiated")
    return order


def test_expired_bank_transfer_order_tells_the_customer(django_capture_on_commit_callbacks):
    """Silence is the worst possible answer here: this customer may have wired the money
    25 hours ago and it may already be in our account."""
    order = _due_order("TC-320001", "bank_transfer")

    with django_capture_on_commit_callbacks(execute=True):
        assert expire_pending_orders() == 1

    order.refresh_from_db()
    assert order.status == "expired"
    assert len(mail.outbox) == 1
    assert "TC-320001" in mail.outbox[0].body


def test_expired_card_order_says_nothing(django_capture_on_commit_callbacks):
    """A card that never completed means the customer never sent money — there is no
    payment in limbo to explain, and an email would only invent a problem."""
    order = _due_order("TC-320002", "paystack")

    with django_capture_on_commit_callbacks(execute=True):
        assert expire_pending_orders() == 1

    order.refresh_from_db()
    assert order.status == "expired"
    assert mail.outbox == []


def test_an_unknown_gateway_code_cannot_starve_the_orders_behind_it(
    django_capture_on_commit_callbacks,
):
    """Plan-21/23 migrate 879 legacy NG orders whose gateway codes this registry has never
    heard of. If the sweep decides manual-ness by asking the registry per order, the first
    such order raises UnknownGateway, kills the run, and every due order behind it starves
    — on every five-minute beat, forever."""
    poison = _due_order("TC-320003", "woocommerce_legacy")
    good = _due_order("TC-320004", "bank_transfer")

    with django_capture_on_commit_callbacks(execute=True):
        expire_pending_orders()  # must not raise

    good.refresh_from_db()
    poison.refresh_from_db()
    assert good.status == "expired"
    # The legacy order expires too: an unrecognised code is simply not a manual code, so
    # it releases its stock like any other and mails nobody.
    assert poison.status == "expired"
    assert len(mail.outbox) == 1
    assert "TC-320004" in mail.outbox[0].body


def test_an_order_that_raises_mid_sweep_does_not_starve_its_siblings(monkeypatch):
    """The belt to _manual_gateway_codes' braces. That fix removes the one raise we know
    about; this pins the promise the docstring has always made — whatever the NEXT raise
    turns out to be, the sweep keeps going rather than parking every due order behind the
    bad one on every five-minute beat, forever."""
    bad = _due_order("TC-320005", "bank_transfer")
    good = _due_order("TC-320006", "bank_transfer")

    real_release = tasks_module.release

    def exploding_release(reference: str) -> None:
        # Mirrors release()'s real signature and returns None like it does — a stub that
        # silently returned something else could make this pass for the wrong reason.
        if reference == "TC-320005":
            raise RuntimeError("ledger replay blew up on this one order")
        return real_release(reference=reference)

    monkeypatch.setattr(tasks_module, "release", exploding_release)

    assert expire_pending_orders() == 1  # must not raise; the good one still counted

    bad.refresh_from_db()
    good.refresh_from_db()
    assert bad.status == "pending_payment"  # rolled back — its own transaction, alone
    assert good.status == "expired"
