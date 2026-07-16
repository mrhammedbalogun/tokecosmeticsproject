"""confirm_payment — the gateway-agnostic fulfilment seam. Uses a fake gateway (no
network) to drive every branch: happy path, amount/currency mismatch, unpaid verify,
double payment, payment-on-cancelled-order, and the late-payment re-reserve paths."""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import release, reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import PaymentGateway, VerifyResult
from apps.payments.services import MarkPaidResult, confirm_payment, mark_paid

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    code = "fake"
    supported_currencies = {"NGN"}
    result: VerifyResult = None

    def initiate(self, payment, order, return_url=""):  # pragma: no cover - unused here
        raise NotImplementedError

    def verify(self, payment):
        return self.result


@pytest.fixture
def fake_gateway(monkeypatch):
    gw = _FakeGateway()
    monkeypatch.setitem(registry._REGISTRY, "fake", gw)
    return gw


def _setup(qty=10):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    return ng, ngn, variant


def _order(number, ng, ngn, *, total="1000.00", status="pending_payment"):
    order = OrderFactory(
        number=number, country=ng, currency=ngn, reservation_reference=number,
        grand_total=total, status=status, email="c@x.com",
    )
    return order


def _paid_result(amount="1000.00", currency="NGN", status="succeeded"):
    return VerifyResult(status=status, amount=Decimal(amount), currency=currency, raw={"ok": True})


# --- mark_paid verdicts ------------------------------------------------------


def test_mark_paid_returns_fulfilled_and_fulfils():
    ng, ngn, variant = _setup()
    order = _order("TC-200001", ng, ngn)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-200001")
    payment = PaymentFactory(order=order, currency=ngn)

    assert mark_paid(payment) is MarkPaidResult.FULFILLED
    order.refresh_from_db()
    assert order.status == "processing"


@pytest.mark.parametrize("status,expected", [
    ("processing", MarkPaidResult.NOOP_ALREADY_PROCESSED),
    ("expired", MarkPaidResult.NOOP_EXPIRED),
    ("cancelled", MarkPaidResult.NOOP_CANCELLED),
])
def test_mark_paid_reports_non_pending_states(status, expected):
    ng, ngn, _ = _setup()
    order = _order(f"TC-2001-{status}", ng, ngn, status=status)
    payment = PaymentFactory(order=order, currency=ngn)
    assert mark_paid(payment) is expected


# --- confirm_payment happy + mismatch ---------------------------------------


def test_confirm_happy_path_fulfils(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200010", ng, ngn)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-200010")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")

    confirm_payment(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "processing"
    assert payment.status == "succeeded"
    assert payment.raw_response.get("verify") == {"ok": True}


def test_confirm_amount_mismatch_flags_for_review(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200011", ng, ngn)
    reserve(variant, 2, ng, reference="TC-200011")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("950.00")  # underpaid

    confirm_payment(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    # The flag rides on review_reason; the status stays truthful. Leaving it
    # pending_payment means the expiry task still reclaims the stock, and a later
    # "actually fulfil it" replay lands on the NOOP_EXPIRED re-reserve path.
    assert order.status == "pending_payment"
    assert "order total is 1000.00" in order.review_reason
    assert payment.status != "succeeded"


def test_confirm_currency_mismatch_flags_for_review(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200012", ng, ngn)
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00", currency="USD")

    confirm_payment(payment)

    order.refresh_from_db()
    assert order.status == "pending_payment"
    assert order.review_reason != ""


def test_confirm_unpaid_verify_does_not_fulfil(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200013", ng, ngn)
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result(status="pending")

    confirm_payment(payment)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status == "pending"


# --- confirm_payment recovery paths -----------------------------------------


def test_confirm_double_payment_flags_without_changing_status(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200014", ng, ngn)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-200014")
    # First payment fulfils the order.
    first = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")
    confirm_payment(first)
    # A second, distinct payment for the same order also verifies succeeded.
    second = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    confirm_payment(second)

    order.refresh_from_db()
    assert order.status == "processing"  # unchanged
    assert f"refund payment {second.pk}" in order.review_reason


def test_confirm_same_payment_replay_is_benign(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200015", ng, ngn)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-200015")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")
    confirm_payment(payment)
    confirm_payment(payment)  # webhook + return endpoint both fire

    order.refresh_from_db()
    assert order.status == "processing"
    assert order.review_reason == ""  # NOT flagged as double payment


def test_confirm_payment_on_cancelled_order_flags_refund(fake_gateway):
    ng, ngn, variant = _setup()
    order = _order("TC-200016", ng, ngn, status="cancelled")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")

    confirm_payment(payment)

    order.refresh_from_db()
    assert order.status == "cancelled"  # unchanged
    assert "refund it" in order.review_reason


def test_confirm_late_payment_after_expiry_rereserves(fake_gateway):
    ng, ngn, variant = _setup(qty=10)
    order = _order("TC-200017", ng, ngn, status="expired")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    # Simulate the expiry task having reserved then released.
    reserve(variant, 2, ng, reference="TC-200017")
    release("TC-200017")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")

    confirm_payment(payment)

    order.refresh_from_db()
    assert order.status == "processing"
    assert order.reservation_reference == "TC-200017/2"  # bumped attempt suffix
    si = variant.stock_items.get()
    assert si.quantity == 8 and si.reserved == 0  # re-reserved and committed


def test_confirm_late_payment_after_expiry_insufficient_stock_flags(fake_gateway):
    ng, ngn, variant = _setup(qty=2)
    order = _order("TC-200018", ng, ngn, status="expired")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-200018")
    release("TC-200018")
    # Someone else buys the stock in the meantime — it's gone when the late payment lands.
    from apps.inventory.services import adjust
    adjust(variant.stock_items.get(), 0, reason="correction", note="sold out")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fake", amount="1000.00")
    fake_gateway.result = _paid_result("1000.00")

    confirm_payment(payment)

    order.refresh_from_db()
    # `expired` is the truth — the order really did expire. review_reason says why a
    # human must look (this is auto-refund territory).
    assert order.status == "expired"
    assert "could not re-reserve" in order.review_reason
    # no phantom reservation left behind under the bumped reference
    si = variant.stock_items.get()
    assert si.reserved == 0
