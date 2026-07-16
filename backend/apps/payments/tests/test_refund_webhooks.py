"""Refund-completion webhooks settle async refunds — and, critically, are NOT routed
through confirm_payment (which would re-verify an already-refunded payment and mis-flag
it as a double payment)."""
import json
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import ParsedEvent, PaymentGateway, VerifyResult
from apps.payments.models import Refund

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    code = "fakerw"
    supported_currencies = {"NGN"}
    verify_calls = 0

    def initiate(self, payment, order, return_url=""):  # pragma: no cover
        raise NotImplementedError

    def verify(self, payment):
        type(self).verify_calls += 1
        return VerifyResult("succeeded", Decimal("1000.00"), "NGN", {})

    def parse_webhook(self, request):
        body = json.loads(request.body)
        return ParsedEvent(
            event_id=body["id"], event_type=body["type"],
            gateway_reference=body["reference"], raw=body,
            kind=body.get("kind", "payment"),
            refund_reference=body.get("refund_reference", ""),
        )


@pytest.fixture
def fakerw(monkeypatch):
    gw = _FakeGateway()
    _FakeGateway.verify_calls = 0
    monkeypatch.setitem(registry._REGISTRY, "fakerw", gw)
    return gw


def _refunded_setup(number="TC-950001"):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    order = OrderFactory(number=number, country=ng, currency=ngn, reservation_reference=number,
                         grand_total="1000.00", status="processing", email="c@x.com")
    payment = PaymentFactory(order=order, currency=ngn, gateway="fakerw",
                             gateway_reference=number, amount="1000.00", status="succeeded")
    refund = Refund.objects.create(payment=payment, amount=Decimal("1000.00"),
                                   status="pending", gateway_reference="rf_1")
    return order, payment, refund


def _post(body):
    return APIClient().post("/api/v1/webhooks/fakerw/", data=json.dumps(body),
                            content_type="application/json")


def test_refund_completion_webhook_settles_pending_refund(fakerw):
    order, payment, refund = _refunded_setup()
    resp = _post({"id": "evt-r1", "type": "refund.processed", "reference": order.number,
                  "kind": "refund", "refund_reference": "rf_1"})

    assert resp.status_code == 200
    refund.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    assert refund.status == "succeeded"
    assert payment.status == "refunded"
    assert order.status == "refunded"


def test_refund_event_never_routed_through_confirm_payment(fakerw):
    """The regression this guards: a refund event reaching confirm_payment would flag a
    bogus 'possible double payment' on a perfectly normal refund."""
    order, payment, refund = _refunded_setup("TC-950002")
    _post({"id": "evt-r2", "type": "refund.processed", "reference": order.number,
           "kind": "refund", "refund_reference": "rf_1"})

    order.refresh_from_db()
    assert _FakeGateway.verify_calls == 0  # confirm_payment never ran
    assert order.review_reason == ""       # NOT flagged as a double payment


def test_failed_refund_event_marks_failed_and_frees_amount(fakerw):
    order, payment, refund = _refunded_setup("TC-950003")
    _post({"id": "evt-r3", "type": "refund.failed", "reference": order.number,
           "kind": "refund", "refund_reference": "rf_1"})

    refund.refresh_from_db()
    payment.refresh_from_db()
    assert refund.status == "failed"
    assert payment.status == "succeeded"  # money never left; payment unchanged


def test_unknown_kind_event_is_acked_without_confirming(fakerw):
    order, payment, refund = _refunded_setup("TC-950004")
    resp = _post({"id": "evt-o1", "type": "customer.created", "reference": order.number,
                  "kind": "other"})

    assert resp.status_code == 200
    assert _FakeGateway.verify_calls == 0
