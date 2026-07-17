"""Edge case (Fable 5 battery): a payment gateway 5xx on initiate must return 502 with a
clean error, leave the order pending, and be retryable with the SAME Idempotency-Key —
the retry resumes the existing order and re-attempts initiate, never a duplicate order."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.gateways.paystack import API_BASE
from apps.payments.models import CountryPaymentGateway, Payment
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db

SECRET = "sk_test_secret"


def _world(stock=10):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    # paystack is deactivated at launch, so activate it HERE rather than in the DB the site
    # ships with. What's pinned below is the retry/idempotency seam around a networked
    # initiate() — that has to stay covered while the gateway sits behind its deferred
    # sandbox checkpoint, since a reactivation is exactly when the 502 path runs for real.
    # update_or_create, not create: 0002 already seeded the row and a create() would collide
    # on unique_together(country, gateway).
    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="paystack", defaults={"is_active": True}
    )
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def _body(cart, addr, opt):
    return {"cart_id": str(cart.id), "address_id": addr.id,
            "delivery_option_id": opt.id, "payment_gateway": "paystack"}


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_gateway_5xx_on_initiate_returns_502_then_retry_resumes(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email="g@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    state = {"n": 0}

    def _initialize(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(502)  # gateway down on the first attempt
        return httpx.Response(200, json={
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/xyz",
                     "access_code": "ac", "reference": "TC-ref"},
        })

    respx.post(f"{API_BASE}/transaction/initialize").mock(side_effect=_initialize)

    client = APIClient()
    client.force_authenticate(user)

    # First attempt — gateway 5xx -> 502, order created and left pending.
    r1 = client.post("/api/v1/checkout/", _body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-key")
    assert r1.status_code == 502, r1.data
    assert r1.data["error"] == "gateway_error"
    order = Order.objects.get()
    assert order.status == "pending_payment"
    assert variant.stock_items.get().reserved == 2  # reservation held
    payment = Payment.objects.get(order=order)
    assert payment.gateway_reference == ""  # initiate never completed

    # Retry with the SAME key — resumes the same order, initiate now succeeds.
    r2 = client.post("/api/v1/checkout/", _body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-key")
    assert r2.status_code == 201, r2.data
    assert r2.data["payment"]["action"] == "redirect"
    assert Order.objects.count() == 1  # NO duplicate order
    assert variant.stock_items.get().reserved == 2  # NOT double-reserved
    payment.refresh_from_db()
    assert payment.gateway_reference == "TC-ref"
