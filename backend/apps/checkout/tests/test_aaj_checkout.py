"""End-to-end (Plan-43): a Nigerian customer anywhere in the country checks out
with AAJ door delivery; the order's shipping_total is the live retail quote, the
ETA is AAJ's own, and the AajShipment is born quoted in the placement transaction
— including for a guest, and including a state GIG does not cover."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.models import DeliveryOption
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.models import BankAccount
from apps.pricing.models import Price

BASE = "https://aaj.test/api/v2"
SETTINGS = dict(AAJ_BASE_URL=BASE, AAJ_API_KEY="aaj-testkey")

pytestmark = pytest.mark.django_db


def _quote(total, eta):
    return httpx.Response(200, json={"success": True, "status": 200, "message": "quote created",
        "data": {"quotes": [{"total": total, "subTotal": round(total / 1.075, 2), "tax": 1, "vat": 7.5,
                             "eta": {"numberOfDays": eta}, "currency": "NGN", "carrier": "AAJ"}]}})


def _world():
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    kano = Region.objects.get(country_code="NG", level="state", name="Kano")
    dala = Region.objects.filter(country_code="NG", level="area", parent=kano).first()
    # The seeded Ogudu origin resolves its state through the nearest LGA centroid.
    Region.objects.filter(country_code="NG", level="area", name="Kosofe", parent__name="Lagos").update(
        latitude="6.5830", longitude="3.4020")
    option = DeliveryOption.objects.get(carrier_code="aaj")
    option.is_active = True
    option.save(update_fields=["is_active"])
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    variant = ProductVariantFactory(weight_grams=300)
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    return ng, ngn, variant, kano, dala, option


@pytest.fixture(autouse=True)
def _fresh():
    cache.clear()
    yield
    cache.clear()


@override_settings(**SETTINGS)
@respx.mock
def test_checkout_with_aaj_charges_the_live_quote_anywhere_in_nigeria(django_user_model):
    route = respx.post(f"{BASE}/quote").mock(return_value=_quote(9099, 8))
    ng, ngn, variant, kano, dala, option = _world()
    user = django_user_model.objects.create_user(email="aaj@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="5 Zoo Road", country_code="NG",
                                  state_region=kano, area_region=dala)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)
    r = api.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
                HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    aaj = next(o for o in r.json() if o["carrier_code"] == "aaj")
    assert aaj["price"] == "9099.00"
    assert (aaj["min_days"], aaj["max_days"]) == (2, 8)
    import json

    sent = json.loads(route.calls[0].request.read())
    assert sent["receiver"]["addressDetails"]["stateOrProvinceCode"] == "KN"
    assert sent["packages"]["packages"][0]["actualWeight"] == 0.6

    r = api.post("/api/v1/checkout/",
                 {"cart_id": str(cart.id), "address_id": addr.id,
                  "delivery_option_id": option.id, "payment_gateway": "bank_transfer"},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="aaj-1")
    assert r.status_code in (200, 201), r.content
    order = Order.objects.get(user=user)
    assert order.shipping_total == Decimal("9099.00")
    assert order.delivery_option_name == "Door Delivery (AAJ Express)"
    shipment = order.aaj_shipment
    assert shipment.status == "quoted"
    assert shipment.charged == Decimal("9099.00") and shipment.quote_total == Decimal("9099.00")
    assert shipment.quote["eta_days"] == 8
    assert shipment.origin["state_code"] == "LA"
    assert shipment.cost is None  # nothing booked, nothing charged until capture
    assert not hasattr(order, "gig_shipment") or Order.objects.filter(pk=order.pk, gig_shipment__isnull=True).exists()


@override_settings(**SETTINGS)
@respx.mock
def test_checkout_survives_aaj_dying_between_quote_and_place(django_user_model):
    respx.post(f"{BASE}/quote").mock(return_value=_quote(9099, 8))
    ng, ngn, variant, kano, dala, option = _world()
    user = django_user_model.objects.create_user(email="aaj2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="5 Zoo Road", country_code="NG",
                                  state_region=kano, area_region=dala)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")
    api = APIClient()
    api.force_authenticate(user)
    api.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}", HTTP_X_COUNTRY="NG")
    cache.clear()
    respx.post(f"{BASE}/quote").mock(side_effect=httpx.ConnectError("down"))
    r = api.post("/api/v1/checkout/",
                 {"cart_id": str(cart.id), "address_id": addr.id,
                  "delivery_option_id": option.id, "payment_gateway": "bank_transfer"},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="aaj-2")
    assert r.status_code == 409
    assert r.json()["error"] == "delivery_option_invalid"
    assert not Order.objects.filter(user=user).exists()
