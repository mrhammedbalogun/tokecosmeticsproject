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
from apps.payments.gateways.base import GatewayError, InitiateResult, PaymentGateway
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


# --- same-gateway retry: the reference is the transaction identity ---------------------
#
# The FAKE-{pk} gateway above accidentally mints attempt-unique references, which is how
# the 2026-08-12 bug survived its tests: the REAL adapters send the reference the service
# minted on the row, and retrying the same gateway collided with
# uniq_payment_gateway_reference (Flutterwave order TC-100056, HTTP 500). The service now
# owns minting: bare order reference for the first goods attempt (the exact bytes Paystack
# was certified on), "-P<pk>"-suffixed for every later attempt.


class _EchoRefGateway(PaymentGateway):
    """Shaped like the real adapters post-fix: sends payment.gateway_reference verbatim."""

    code = "fakecho"
    supported_currencies = {"NGN"}
    calls: list = []
    fail_next = False

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        type(self).calls.append(
            {"pk": payment.pk, "reference": payment.gateway_reference, "return_url": return_url}
        )
        if type(self).fail_next:
            type(self).fail_next = False
            raise GatewayError("gateway 5xx")
        return InitiateResult(action="redirect", reference=payment.gateway_reference,
                              data={"redirect_url": "https://gw/pay"})


@pytest.fixture
def fakecho(monkeypatch):
    _EchoRefGateway.calls = []
    _EchoRefGateway.fail_next = False
    gw = _EchoRefGateway()
    monkeypatch.setitem(registry._REGISTRY, "fakecho", gw)
    ng = Country.objects.get(code="NG")
    from apps.payments.models import CountryPaymentGateway

    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="fakecho", defaults={"is_active": True, "sort_order": 10})
    return gw


@pytest.fixture
def declined_order(django_user_model):
    """An order whose FIRST attempt already holds the bare order reference — exactly what
    production rows look like after a declined card."""
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="d@x.com", password="pw")
    order = OrderFactory(number="TC-800002", user=user, country=ng, currency=ng.currency,
                         reservation_reference="TC-800002", grand_total="5000.00",
                         status="pending_payment", email="d@x.com",
                         reservation_expires_at=timezone.now() + timedelta(minutes=15))
    PaymentFactory(order=order, currency=ng.currency, gateway="fakecho",
                   amount="5000.00", gateway_reference="TC-800002", status="initiated",
                   raw_response={"redirect_url": "https://gw/old"})
    return order


def test_retrying_the_same_gateway_does_not_collide(declined_order, fakecho):
    """The live bug: same gateway, same order -> IntegrityError -> 500."""
    result = retry_payment(user=declined_order.user, order_number="TC-800002",
                           payment_gateway="fakecho", key="retry-same-1")

    assert result.payment.gateway == "fakecho"
    assert result.payment.gateway_reference == f"TC-800002-P{result.payment.pk}"
    # The declined attempt survives untouched — its decline evidence and its identity
    # at the gateway must never be recycled.
    old = declined_order.payments.exclude(pk=result.payment.pk).get()
    assert old.gateway_reference == "TC-800002"
    assert old.raw_response == {"redirect_url": "https://gw/old"}
    assert declined_order.payments.count() == 2


def test_retry_return_url_carries_the_attempt_reference(declined_order, fakecho):
    """The customer must come back to the verify of THIS attempt, not the declined one —
    PaymentStatusView resolves ?ref= by gateway_reference."""
    result = retry_payment(user=declined_order.user, order_number="TC-800002",
                           payment_gateway="fakecho", key="retry-same-2")

    assert _EchoRefGateway.calls[-1]["return_url"].endswith(
        f"/checkout/return?ref={result.payment.gateway_reference}"
    )


def test_bank_transfer_same_gateway_retry_does_not_collide(pending_order):
    """bank_transfer had the identical latent collision (its adapter returned the bare
    order number). A card customer switching to bank transfer, abandoning, and choosing
    bank transfer again must not 500."""
    ng = Country.objects.get(code="NG")
    BankAccount.objects.create(country=ng, currency=ng.currency, bank_name="GTB",
                               account_name="Toke", account_number="0123456789",
                               is_active=True)

    first = retry_payment(user=pending_order.user, order_number="TC-800001",
                          payment_gateway="bank_transfer", key="retry-bt-1")
    again = retry_payment(user=pending_order.user, order_number="TC-800001",
                          payment_gateway="bank_transfer", key="retry-bt-2")

    assert first.payment.pk != again.payment.pk
    refs = {first.payment.gateway_reference, again.payment.gateway_reference}
    assert len(refs) == 2  # attempt-unique, no constraint violation


def test_crashed_initiate_replays_with_the_same_key_and_reference(declined_order, fakecho):
    """Intent-then-act: the reference is persisted BEFORE the gateway call, so a crashed
    initiate leaves a row that a replay of the SAME key resumes — same row, same
    reference, and this time with SDK material."""
    _EchoRefGateway.fail_next = True
    with pytest.raises(GatewayError):
        retry_payment(user=declined_order.user, order_number="TC-800002",
                      payment_gateway="fakecho", key="retry-crash-1")

    crashed = declined_order.payments.exclude(gateway_reference="TC-800002").get()
    assert crashed.gateway_reference == f"TC-800002-P{crashed.pk}"  # persisted pre-crash
    assert crashed.raw_response == {}  # but no SDK material yet

    replay = retry_payment(user=declined_order.user, order_number="TC-800002",
                           payment_gateway="fakecho", key="retry-crash-1")
    assert replay.payment.pk == crashed.pk
    assert replay.payment.gateway_reference == crashed.gateway_reference
    assert replay.payment.raw_response == {"redirect_url": "https://gw/pay"}
    assert declined_order.payments.count() == 2  # no third row
