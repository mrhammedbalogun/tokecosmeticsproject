"""Gateway-agnostic webhook endpoint: signature gate, idempotency ledger, fast ack, and
(via eager Celery) end-to-end fulfilment. A fake gateway stands in for the real ones so
this suite proves the infrastructure independently of any single gateway's quirks."""
import json
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
from apps.payments.gateways import registry
from apps.payments.gateways.base import (
    InvalidSignature,
    ParsedEvent,
    PaymentGateway,
    VerifyResult,
)
from apps.payments.models import WebhookEvent

pytestmark = pytest.mark.django_db


class _FakeWebhookGateway(PaymentGateway):
    code = "fakehook"
    supported_currencies = {"NGN"}
    verify_result = VerifyResult("succeeded", Decimal("1000.00"), "NGN", {"ok": True})

    def initiate(self, payment, order, return_url=""):  # pragma: no cover
        raise NotImplementedError

    def verify(self, payment):
        return self.verify_result

    def parse_webhook(self, request):
        if request.headers.get("X-Fake-Signature") != "good":
            raise InvalidSignature("bad sig")
        body = json.loads(request.body)
        return ParsedEvent(
            event_id=body["id"], event_type=body["type"],
            gateway_reference=body["reference"], raw=body,
        )


@pytest.fixture
def fakehook(monkeypatch):
    gw = _FakeWebhookGateway()
    monkeypatch.setitem(registry._REGISTRY, "fakehook", gw)
    return gw


def _order_with_payment(number, ref):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    order = OrderFactory(number=number, country=ng, currency=ngn, reservation_reference=number,
                         grand_total="1000.00", email="c@x.com")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference=number)
    payment = PaymentFactory(order=order, currency=ngn, gateway="fakehook",
                             gateway_reference=ref, amount="1000.00")
    return order, payment


def _post(client, body, signature="good"):
    return client.post(
        "/api/v1/webhooks/fakehook/",
        data=json.dumps(body), content_type="application/json",
        HTTP_X_FAKE_SIGNATURE=signature,
    )


def test_valid_webhook_fulfils_order(fakehook):
    order, payment = _order_with_payment("TC-300001", "REF-1")
    resp = _post(APIClient(), {"id": "evt-1", "type": "charge.success", "reference": "REF-1"})

    assert resp.status_code == 200
    order.refresh_from_db()
    assert order.status == "processing"  # eager task ran confirm_payment end-to-end
    ev = WebhookEvent.objects.get(gateway="fakehook", event_id="evt-1")
    assert ev.processed_at is not None


def test_duplicate_webhook_is_ignored(fakehook):
    order, payment = _order_with_payment("TC-300002", "REF-2")
    client = APIClient()
    body = {"id": "evt-2", "type": "charge.success", "reference": "REF-2"}
    first = _post(client, body)
    second = _post(client, body)

    assert first.status_code == 200 and first.json()["status"] == "accepted"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert WebhookEvent.objects.filter(gateway="fakehook", event_id="evt-2").count() == 1


def test_invalid_signature_rejected(fakehook):
    _order_with_payment("TC-300003", "REF-3")
    resp = _post(APIClient(), {"id": "evt-3", "type": "charge.success", "reference": "REF-3"},
                 signature="bad")

    assert resp.status_code == 400
    assert not WebhookEvent.objects.filter(event_id="evt-3").exists()


def test_unknown_gateway_404():
    resp = APIClient().post("/api/v1/webhooks/nosuchgw/", data="{}",
                            content_type="application/json")
    assert resp.status_code == 404


def test_unmatched_reference_is_acked_and_processed(fakehook):
    resp = _post(APIClient(), {"id": "evt-9", "type": "charge.success", "reference": "NOPE"})
    assert resp.status_code == 200
    ev = WebhookEvent.objects.get(event_id="evt-9")
    assert ev.processed_at is not None  # recorded + acked, never retried
