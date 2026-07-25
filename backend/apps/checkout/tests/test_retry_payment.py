"""retry_payment: re-open the MONEY leg of an order that is still awaiting payment,
optionally on a different gateway.

The gap this closes: place_order converts the cart before initiating payment, so a
customer whose card fails has no bag to go back to and no way to switch method — the
order exists, holds stock, and is unpayable. Nothing about the order (lines, totals,
addresses, reservation) may change here; only a new Payment attempt is opened.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.checkout.services.checkout import CheckoutError, retry_payment
from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import InitiateResult, PaymentGateway
from apps.payments.models import BankAccount, Payment

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    """Stands in for a networked gateway: records the initiate call, mints a reference."""

    code = "faketry"
    supported_currencies = {"NGN"}
    reservation_ttl_minutes = 4320  # deliberately LONGER than the default, for the TTL test
    calls: list = []

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        type(self).calls.append(payment.pk)
        return InitiateResult(action="redirect", reference=f"FAKE-{payment.pk}",
                              data={"redirect_url": "https://gw/pay"})


@pytest.fixture
def faketry(monkeypatch):
    _FakeGateway.calls = []
    gw = _FakeGateway()
    monkeypatch.setitem(registry._REGISTRY, "faketry", gw)
    ng = Country.objects.get(code="NG")
    from apps.payments.models import CountryPaymentGateway

    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="faketry", defaults={"is_active": True, "sort_order": 9})
    return gw


@pytest.fixture
def pending_order(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="r@x.com", password="pw")
    order = OrderFactory(number="TC-800001", user=user, country=ng, currency=ng.currency,
                         reservation_reference="TC-800001", grand_total="5000.00",
                         status="pending_payment", email="r@x.com",
                         reservation_expires_at=timezone.now() + timedelta(minutes=15))
    PaymentFactory(order=order, currency=ng.currency, gateway="paystack",
                   amount="5000.00", gateway_reference="PS-ABANDONED", status="initiated")
    return order


def test_opens_a_new_attempt_on_a_different_gateway(pending_order, faketry):
    result = retry_payment(user=pending_order.user, order_number="TC-800001",
                           payment_gateway="faketry", key="retry-1")

    assert result.payment.gateway == "faketry"
    assert result.payment.gateway_reference == f"FAKE-{result.payment.pk}"
    # A NEW attempt, not a mutation of the abandoned one — the old row must survive
    # untouched, because its transaction may still settle at the gateway.
    assert pending_order.payments.count() == 2
    old = pending_order.payments.get(gateway="paystack")
    assert old.gateway_reference == "PS-ABANDONED"
    assert _FakeGateway.calls == [result.payment.pk]


def test_reuses_the_previous_attempts_amount_not_the_order_total(pending_order, faketry):
    """A quote-required (RoW) order is paid goods-only, so its payment is deliberately
    LESS than grand_total. Re-charging grand_total would ask for freight nobody quoted."""
    pending_order.payments.update(amount=Decimal("4000.00"))

    result = retry_payment(user=pending_order.user, order_number="TC-800001",
                           payment_gateway="faketry", key="retry-2")

    assert result.payment.amount == Decimal("4000.00")


def test_extends_the_reservation_when_the_new_gateway_holds_stock_longer(pending_order, faketry):
    before = pending_order.reservation_expires_at

    retry_payment(user=pending_order.user, order_number="TC-800001",
                  payment_gateway="faketry", key="retry-3")

    pending_order.refresh_from_db()
    # Switching to a slower method (e.g. bank transfer) must not leave the order expiring
    # in minutes — the customer would lose the stock they are actively paying for.
    assert pending_order.reservation_expires_at > before


def test_never_shortens_a_reservation(pending_order, faketry):
    far = timezone.now() + timedelta(days=30)
    pending_order.reservation_expires_at = far
    pending_order.save(update_fields=["reservation_expires_at"])

    retry_payment(user=pending_order.user, order_number="TC-800001",
                  payment_gateway="faketry", key="retry-4")

    pending_order.refresh_from_db()
    assert pending_order.reservation_expires_at == far


def test_same_key_replays_instead_of_opening_a_second_attempt(pending_order, faketry):
    first = retry_payment(user=pending_order.user, order_number="TC-800001",
                          payment_gateway="faketry", key="retry-5")
    again = retry_payment(user=pending_order.user, order_number="TC-800001",
                          payment_gateway="faketry", key="retry-5")

    assert again.payment.pk == first.payment.pk
    assert Payment.objects.filter(idempotency_key="retry-5").count() == 1
    assert _FakeGateway.calls == [first.payment.pk]  # not initiated twice


def test_rejects_a_gateway_not_offered_in_the_orders_country(pending_order, faketry):
    with pytest.raises(CheckoutError) as exc:
        retry_payment(user=pending_order.user, order_number="TC-800001",
                      payment_gateway="stripe", key="retry-6")
    assert exc.value.code == "gateway_unavailable"


def test_rejects_an_order_that_is_no_longer_awaiting_payment(pending_order, faketry):
    pending_order.status = "processing"
    pending_order.save(update_fields=["status"])

    with pytest.raises(CheckoutError) as exc:
        retry_payment(user=pending_order.user, order_number="TC-800001",
                      payment_gateway="faketry", key="retry-7")
    assert exc.value.code == "order_not_payable"
    assert exc.value.http == 409
    assert pending_order.payments.count() == 1  # nothing opened


def test_cannot_reach_another_customers_order(pending_order, faketry, django_user_model):
    other = django_user_model.objects.create_user(email="thief@x.com", password="pw")

    with pytest.raises(CheckoutError) as exc:
        retry_payment(user=other, order_number="TC-800001",
                      payment_gateway="faketry", key="retry-8")
    assert exc.value.code == "order_not_found"
    assert exc.value.http == 404


def test_manual_gateway_without_a_bank_account_is_refused(pending_order):
    """Same guard as place_order: bank transfer with no configured account would hand the
    customer a blank payment page."""
    ng = Country.objects.get(code="NG")
    BankAccount.objects.filter(country=ng).delete()

    with pytest.raises(CheckoutError) as exc:
        retry_payment(user=pending_order.user, order_number="TC-800001",
                      payment_gateway="bank_transfer", key="retry-9")
    assert exc.value.code == "gateway_unavailable"
