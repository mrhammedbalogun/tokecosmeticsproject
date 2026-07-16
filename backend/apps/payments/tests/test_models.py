import pytest
from django.db import IntegrityError

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory

pytestmark = pytest.mark.django_db


def _order():
    # Seed migration (core 0003) already created NG + NGN — fetch, don't re-create
    # (a create() would collide on the PK). Intent unchanged: an Order to hang a Payment on.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    return OrderFactory(number="TC-100001", country=ng, currency=ngn, reservation_reference="TC-100001")


def test_payment_idempotency_key_unique():
    order = _order()
    PaymentFactory(order=order, currency=order.currency, idempotency_key="dup")
    with pytest.raises(IntegrityError):
        PaymentFactory(order=order, currency=order.currency, idempotency_key="dup")
