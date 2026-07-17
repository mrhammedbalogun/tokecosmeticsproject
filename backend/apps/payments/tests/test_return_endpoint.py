"""POST /api/v1/payments/{reference}/verify/ — the customer return-from-redirect check.
Runs the same confirm_payment the webhook does; scoped to the user's own orders."""
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
from apps.payments.gateways.base import PaymentGateway, VerifyResult

pytestmark = pytest.mark.django_db


class _FakeGateway(PaymentGateway):
    code = "fakeret"
    supported_currencies = {"NGN"}
    result = VerifyResult("succeeded", Decimal("1000.00"), "NGN", {"ok": True})

    def initiate(self, payment, order, return_url=""):  # pragma: no cover
        raise NotImplementedError

    def verify(self, payment):
        return self.result


@pytest.fixture
def fakeret(monkeypatch):
    gw = _FakeGateway()
    monkeypatch.setitem(registry._REGISTRY, "fakeret", gw)
    return gw


def _order(user, number="TC-500001"):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    order = OrderFactory(number=number, user=user, country=ng, currency=ngn,
                         reservation_reference=number, grand_total="1000.00", email=user.email)
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference=number)
    payment = PaymentFactory(order=order, currency=ngn, gateway="fakeret",
                             gateway_reference=number, amount="1000.00")
    return order, payment


def test_return_endpoint_confirms_and_reports_status(fakeret, django_user_model):
    user = django_user_model.objects.create_user(email="r@x.com", password="pw")
    order, payment = _order(user)
    client = APIClient()
    client.force_authenticate(user)

    resp = client.post(f"/api/v1/payments/{payment.gateway_reference}/verify/")

    assert resp.status_code == 200
    assert resp.data["order_status"] == "processing"
    assert resp.data["payment_status"] == "succeeded"


def test_return_endpoint_scoped_to_owner(fakeret, django_user_model):
    owner = django_user_model.objects.create_user(email="o@x.com", password="pw")
    intruder = django_user_model.objects.create_user(email="i@x.com", password="pw")
    order, payment = _order(owner)
    client = APIClient()
    client.force_authenticate(intruder)

    resp = client.post(f"/api/v1/payments/{payment.gateway_reference}/verify/")
    assert resp.status_code == 404  # not the intruder's order
