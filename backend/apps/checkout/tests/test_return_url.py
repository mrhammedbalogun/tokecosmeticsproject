"""_initiate_payment builds the gateway return URL server-side from a trusted setting +
the order's own reference, and passes it to the adapter. It must never come from request
data (open-redirect / tampering vector)."""
from decimal import Decimal

import pytest
from django.test import override_settings

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways import registry
from apps.payments.gateways.base import InitiateResult, PaymentGateway

pytestmark = pytest.mark.django_db


class _CapturingGateway(PaymentGateway):
    code = "capret"
    supported_currencies = {"NGN"}
    seen_return_url = None

    def initiate(self, payment, order, return_url=""):
        type(self).seen_return_url = return_url
        return InitiateResult(action="redirect", reference=order.reservation_reference,
                              data={"redirect_url": "https://gw/pay"})


@pytest.fixture
def capret(monkeypatch):
    gw = _CapturingGateway()
    monkeypatch.setitem(registry._REGISTRY, "capret", gw)
    return gw


@override_settings(STOREFRONT_BASE_URL="https://preview.example.com")
def test_initiate_payment_passes_server_built_return_url(capret):
    from apps.checkout.services.checkout import _initiate_payment

    ng = Country.objects.get(code="NG")
    order = OrderFactory(number="TC-700001", country=ng, currency=ng.currency,
                         reservation_reference="TC-700001-1", grand_total="1000.00",
                         email="c@x.com")
    payment = PaymentFactory(order=order, currency=ng.currency, gateway="capret",
                             amount="1000.00")

    _initiate_payment(payment, order)

    assert _CapturingGateway.seen_return_url == (
        "https://preview.example.com/checkout/return?ref=TC-700001-1"
    )
