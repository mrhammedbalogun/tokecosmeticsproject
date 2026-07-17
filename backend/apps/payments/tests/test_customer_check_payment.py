"""The customer clicking "has my money arrived?" on a bank transfer.

There is no machine to ask — bank_transfer is confirmed by a staff member reading the
statement — so the verify endpoint must not go looking for one. It still has to answer in
the same shape as every other payment method: the storefront polls ONE url and must not
get a different response depending on how the customer chose to pay.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.bank_transfer import BankTransferGateway
from apps.payments.gateways.base import ManualVerificationOnly

pytestmark = pytest.mark.django_db


def test_checking_a_bank_transfer_does_not_ask_the_gateway(monkeypatch, django_user_model):
    calls = []

    def _record_then_decline(self, payment):
        # Mimics the real verify() rather than returning a stub result, so this test fails
        # on the call being made at all — not on an artificial return value.
        calls.append(payment)
        raise ManualVerificationOnly("bank_transfer is confirmed by a human")

    monkeypatch.setattr(BankTransferGateway, "verify", _record_then_decline)

    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="buyer@x.com", password="pw")
    order = OrderFactory(
        number="TC-320001", country=ng, currency=ng.currency, user=user,
        reservation_reference="TC-320001", grand_total="10000.00",
        status="pending_payment", email="buyer@x.com",
    )
    payment = PaymentFactory(
        order=order, currency=ng.currency, amount=Decimal("10000.00"),
        gateway="bank_transfer", gateway_reference=order.number, status="initiated",
    )
    client = APIClient()
    client.force_authenticate(user)

    r = client.post(f"/api/v1/payments/{payment.gateway_reference}/verify/", format="json")

    assert r.status_code == 200, r.data
    assert calls == []
    # The storefront polls one url for every payment method — the shape must not fork.
    assert set(r.data) == {"order_number", "order_status", "payment_status"}
    assert r.data["order_status"] == "pending_payment"
