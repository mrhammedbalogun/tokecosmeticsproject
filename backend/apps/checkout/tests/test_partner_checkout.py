"""Plan-39: placing an order on a BrandnPack per-LCDA option ("pz:{id}")."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.models import GigShipment, PartnerZone
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.models import BankAccount
from apps.pricing.models import Price
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db


def _world():
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos", parent=None)
    ikorodu = Region.objects.get(country_code="NG", level="area", parent=lagos, name="Ikorodu")
    return ng, ngn, variant, lagos, ikorodu


def _cart(user, ng, ngn, variant):
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")
    return cart


def test_an_order_lands_on_a_partner_option(django_user_model):
    ng, ngn, variant, lagos, ikorodu = _world()
    user = django_user_model.objects.create_user(email="pz@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos, area_region=ikorodu)
    cart = _cart(user, ng, ngn, variant)
    zone = PartnerZone.objects.get(lcda_name="Ikorodu Central")  # seeded, ₦3,000

    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": f"pz:{zone.id}", "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pz-key-1")

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    # The composed name is the whole order-side record of the choice (no FK).
    assert order.delivery_option_name == "Door Delivery - Ikorodu Central (BrandnPack)"
    assert order.shipping_total == Decimal("3000.00")
    # kind="partner" trips neither carrier hook: fulfilment is manual, and there is
    # no freight quote owed.
    assert not GigShipment.objects.filter(order=order).exists()
    assert not ShippingQuote.objects.filter(order=order).exists()


def test_a_zone_outside_the_address_lga_is_refused(django_user_model):
    """The server-side re-match is the fence: an Ikeja customer replaying an Ikorodu
    option id (cheaper) must get delivery_option_invalid, not the Ikorodu price."""
    ng, ngn, variant, lagos, _ = _world()
    ikeja = Region.objects.get(country_code="NG", level="area", parent=lagos, name="Ikeja")
    user = django_user_model.objects.create_user(email="pz2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = _cart(user, ng, ngn, variant)
    ikorodu_zone = PartnerZone.objects.get(lcda_name="Ikorodu Central")

    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": f"pz:{ikorodu_zone.id}", "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pz-key-2")

    assert r.status_code == 409
    assert r.data["error"] == "delivery_option_invalid"


def test_the_quote_preview_prices_a_partner_option(django_user_model):
    ng, ngn, variant, lagos, ikorodu = _world()
    user = django_user_model.objects.create_user(email="pz3@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos, area_region=ikorodu)
    cart = _cart(user, ng, ngn, variant)
    zone = PartnerZone.objects.get(lcda_name="Ikorodu Central")

    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/quote/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": f"pz:{zone.id}",
    }, format="json", HTTP_X_COUNTRY="NG")

    assert r.status_code == 200, r.data
    assert r.data["totals"]["delivery"] == "3000.00"
