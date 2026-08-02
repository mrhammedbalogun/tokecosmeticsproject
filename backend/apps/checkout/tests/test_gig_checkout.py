"""End-to-end: a Nigerian customer in a GIG-covered LGA checks out with GIG home
delivery, and the order's shipping_total is the live quote — priced server-side
through the same decorated option list the customer saw (Plan-32a slice 3)."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.gig import client as gig_client
from apps.delivery.models import DeliveryOption, GigLga
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.models import BankAccount
from apps.pricing.models import Price

BASE = "https://gig.test"
SETTINGS = dict(
    GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw",
    GIG_SENDER_LATITUDE=6.556, GIG_SENDER_LONGITUDE=3.3888, GIG_VEHICLE_TYPE=1,
)

pytestmark = pytest.mark.django_db


def _quote_envelope(grand_total):
    return {"message": "Success", "apiId": "q-1", "status": 200,
            "data": {"data": {"GrandTotal": grand_total, "SurchargeFee": 1000}}}


def _world():
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos, _ = Region.objects.get_or_create(
        country_code="NG", name="Lagos", parent=None, defaults={"level": "state"}
    )
    ikeja, _ = Region.objects.get_or_create(
        country_code="NG", name="Ikeja", parent=lagos, defaults={"level": "area"}
    )
    Region.objects.filter(pk=ikeja.pk).update(latitude="6.618570", longitude="3.342590")
    ikeja.refresh_from_db()
    GigLga.objects.create(state_name="Lagos", lga_name="Ikeja", gig_state_id=24,
                          is_active=True, home_delivery=True, region=ikeja,
                          synced_at=timezone.now())
    gig_option = DeliveryOption.objects.get(carrier_code="gig")
    gig_option.is_active = True
    gig_option.save(update_fields=["is_active"])
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    return ng, ngn, variant, lagos, ikeja, gig_option


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    cache.set(gig_client.TOKEN_CACHE_KEY, "jwt", 300)
    yield
    cache.clear()


@override_settings(**SETTINGS)
@respx.mock
def test_checkout_with_gig_charges_the_live_quote(django_user_model):
    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(4175.2)))
    ng, ngn, variant, lagos, ikeja, gig_option = _world()
    user = django_user_model.objects.create_user(email="gig@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="12 Allen Ave", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)

    # The option list offers GIG, priced.
    r = api.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
                HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    gig = next(o for o in r.json() if o["carrier_code"] == "gig")
    assert gig["price"] == "4175.20"

    # Placing the order with it charges exactly that.
    r = api.post("/api/v1/checkout/",
                 {"cart_id": str(cart.id), "address_id": addr.id,
                  "delivery_option_id": gig_option.id, "payment_gateway": "bank_transfer"},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="gig-1")
    assert r.status_code in (200, 201), r.content
    order = Order.objects.get(user=user)
    assert order.shipping_total == Decimal("4175.20")
    assert order.delivery_option_name == "Door Delivery (GIG)"


@override_settings(**SETTINGS)
@respx.mock
def test_checkout_survives_gig_dying_between_quote_and_place(django_user_model):
    """The customer saw GIG at 4175.20; GIG dies before they click Place Order.
    The server-side re-match omits GIG, so the chosen id no longer matches and the
    checkout fails with the EXISTING delivery_option_invalid error (409) the
    storefront already renders — never a 500 or a silently different price."""
    route = respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(200, json=_quote_envelope(4175.2))
    )
    ng, ngn, variant, lagos, ikeja, gig_option = _world()
    user = django_user_model.objects.create_user(email="gig2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="12 Allen Ave", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)
    r = api.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
                HTTP_X_COUNTRY="NG")
    assert any(o["carrier_code"] == "gig" for o in r.json())

    cache.clear()  # quote cache gone...
    cache.set(gig_client.TOKEN_CACHE_KEY, "jwt", 300)
    route.side_effect = httpx.ConnectError("down")  # ...and so is GIG

    r = api.post("/api/v1/checkout/",
                 {"cart_id": str(cart.id), "address_id": addr.id,
                  "delivery_option_id": gig_option.id, "payment_gateway": "bank_transfer"},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="gig-2")
    assert r.status_code == 409
    assert r.json()["error"] == "delivery_option_invalid"
    assert Order.objects.filter(user=user).count() == 0
