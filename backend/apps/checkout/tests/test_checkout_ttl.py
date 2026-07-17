"""How long checkout holds stock depends on WHO confirms the money. A card resolves in
seconds; a bank transfer waits on staff reading a bank statement during working hours.
One global TTL cannot serve both: short enough for cards expires every transfer order
before the money can land, long enough for transfers lets abandoned card carts sit on
stock for a day."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings
from django.utils import timezone
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
from apps.payments.models import BankAccount, CountryPaymentGateway
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db

SECRET = "sk_test_secret"


def _world(stock=10):
    # NG/NGN come from the core seed migration — fetch, never create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    # This test needs one gateway per confirmation mode, and paystack is deactivated at
    # launch — so activate it HERE rather than in the DB the site ships with. The TTL split
    # is a property of the auto/manual seam, not of which gateways happen to be live, and it
    # must stay pinned for the day a networked gateway passes its sandbox checkpoint.
    # update_or_create, not create: 0002/0007 already seeded both rows for NG and a create()
    # would collide on unique_together.
    for gw in ("bank_transfer", "paystack"):
        CountryPaymentGateway.objects.update_or_create(
            country=ng, gateway=gw, defaults={"is_active": True}
        )
    # The account is what makes the manual one usable: checkout refuses a manual gateway
    # with nowhere to transfer to.
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def _place(django_user_model, email, gateway, key):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email=email, password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": opt.id, "payment_gateway": gateway,
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY=key)
    assert r.status_code == 201, r.data
    return Order.objects.get(number=r.data["order_number"])


def test_bank_transfer_order_holds_stock_for_24_hours(django_user_model):
    # 30 minutes (the card default) would expire this order before the money could land.
    order = _place(django_user_model, "bt@x.com", "bank_transfer", "key-ttl-bt")
    held = (order.reservation_expires_at - timezone.now()).total_seconds()
    assert 23.5 * 3600 < held < 24.5 * 3600


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
@respx.mock
def test_card_order_still_holds_stock_for_30_minutes(django_user_model):
    respx.post(f"{API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(200, json={
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/xyz",
                     "access_code": "ac", "reference": "TC-ref"},
        })
    )
    order = _place(django_user_model, "card@x.com", "paystack", "key-ttl-card")
    held = (order.reservation_expires_at - timezone.now()).total_seconds()
    assert 25 * 60 < held < 35 * 60
