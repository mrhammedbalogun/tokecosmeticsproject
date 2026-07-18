"""HTTP contract around the freight-quote lifecycle services. The services (Task 1–10)
own the money-safety rules; these tests pin who may call the endpoints and that a refusal
comes back as a decision the UI can act on — a 400 with a code, a 409 on a duplicate
reference — rather than an opaque 500.
"""
import pytest
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db

_counter = iter(range(700001, 799999))


@pytest.fixture
def order_factory():
    """Mirrors apps/shipping/tests/test_services.py::_order — a placed NG order in the
    only state where the freight lifecycle is exercised."""
    def _make():
        ng = Country.objects.get(code="NG")
        number = f"TC-{next(_counter)}"
        return OrderFactory(number=number, country=ng, currency=ng.currency,
                            status="pending_payment", reservation_reference=number)
    return _make


@pytest.fixture
def admin_client(django_user_model):
    staff = django_user_model.objects.create_user(
        email="staff@x.com", password="pw", is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(staff)
    return client


@pytest.fixture
def anon_client():
    return APIClient()


def test_quote_endpoint(admin_client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = admin_client.post(
        f"/api/v1/admin/orders/{order.number}/freight/quote/",
        {"amount": "40.00", "note": "Adex quoted 40"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.json()["status"] == "quoted"


def test_waive_without_quote_returns_400(admin_client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = admin_client.post(
        f"/api/v1/admin/orders/{order.number}/freight/waive/",
        {"note": "goodwill"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "quote_required_before_waive"


def test_duplicate_freight_reference_returns_409(admin_client, order_factory):
    o1, o2 = order_factory(), order_factory()
    for o in (o1, o2):
        ShippingQuote.objects.create(order=o, currency=o.currency)
        admin_client.post(f"/api/v1/admin/orders/{o.number}/freight/quote/",
                          {"amount": "40.00", "note": "Adex"}, format="json")

    body = {"amount_received": "40.00", "bank_reference": "DUP-9", "note": ""}
    first = admin_client.post(f"/api/v1/admin/orders/{o1.number}/freight/receipt/",
                              body, format="json")
    second = admin_client.post(f"/api/v1/admin/orders/{o2.number}/freight/receipt/",
                               body, format="json")

    assert first.status_code == 200, first.data
    assert second.status_code == 409
    assert second.json()["error"] == "duplicate_reference"


def test_endpoints_require_staff(anon_client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = anon_client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                                {"amount": "40.00", "note": "x"}, format="json")

    assert response.status_code in (401, 403)
