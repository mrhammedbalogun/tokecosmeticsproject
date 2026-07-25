"""The checkout 201 body must carry payment.reference (= gateway_reference) so the
storefront's PaymentLauncher and the Flutterwave return page have the value the verify
endpoint keys on. Mirrors the setup in test_gateway_initiate_failure.py."""
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
from apps.payments.gateways.paystack import API_BASE
from apps.payments.models import CountryPaymentGateway
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


@override_settings(PAYSTACK_SECRET_KEY="sk_test_secret")
@respx.mock
def test_checkout_201_includes_payment_reference(django_user_model):
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    CountryPaymentGateway.objects.update_or_create(
        country=ng, gateway="paystack", defaults={"is_active": True})
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)

    respx.post(f"{API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(200, json={
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/xyz",
                     "access_code": "ac_123", "reference": "TC-ref-1"},
        })
    )

    user = django_user_model.objects.create_user(email="p@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    resp = client.post("/api/v1/checkout/",
                       {"cart_id": str(cart.id), "address_id": addr.id,
                        "delivery_option_id": opt.id, "payment_gateway": "paystack"},
                       format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k1")

    assert resp.status_code == 201, resp.data
    assert resp.data["payment"]["reference"] == "TC-ref-1"
    assert resp.data["payment"]["data"]["access_code"] == "ac_123"
