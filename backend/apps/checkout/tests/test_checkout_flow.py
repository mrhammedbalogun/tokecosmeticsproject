import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockMovement
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _world(stock=10):
    # Seed migration already created NG + NGN with tax_rate_percent=7.50 and
    # prices_include_tax=True — fetch, don't re-create (a create() collides on the PK,
    # and the seeded tax settings already yield the totals this test asserts).
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    # Seeded payments 0002 already marks bank_transfer ACTIVE for NG, so no CPG row is
    # created here (a create() would collide on unique_together).
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def _user_cart(user, ng, ngn, variant, qty=2):
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=qty, unit_price_snapshot="1000.00")
    return cart


def _checkout_body(cart, addr, opt):
    return {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": opt.id, "payment_gateway": "bank_transfer",
    }


def test_checkout_happy_path_creates_order_and_reservation(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)

    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                    HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="key-1")

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.status == "pending_payment"
    assert order.user == user
    # 2000 subtotal (incl tax) + 1500 delivery = 3500 grand.
    assert order.grand_total == Decimal("3500.00")
    assert order.reservation_reference == order.number
    assert order.reservation_expires_at is not None
    assert OrderItem.objects.filter(order=order).count() == 1
    # stock reserved, cart converted, payment initiated, bank details returned.
    assert variant.stock_items.get().reserved == 2
    assert Cart.objects.get(id=cart.id).status == "converted"
    assert Payment.objects.get(order=order).status == "initiated"
    assert r.data["payment"]["action"] == "bank_details"


def test_idempotent_replay_returns_same_order_without_double_reserving(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email="u2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)
    client = APIClient()
    client.force_authenticate(user)

    r1 = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="same")
    r2 = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="same")
    assert r1.data["order_number"] == r2.data["order_number"]
    assert Order.objects.count() == 1
    assert variant.stock_items.get().reserved == 2  # not 4


def test_insufficient_stock_rolls_back_everything(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=1)  # only 1 in stock
    user = django_user_model.objects.create_user(email="u3@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)  # wants 2
    client = APIClient()
    client.force_authenticate(user)

    # Bypass the cart stock-cap by writing the line directly (already done above via qty=2
    # vs stock=1). Force the row to 2 in case add_item capped it:
    CartItem.objects.filter(cart=cart).update(quantity=2)

    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                    HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k")
    assert r.status_code == 409
    assert Order.objects.count() == 0
    assert Payment.objects.count() == 0
    assert StockMovement.objects.count() == 0  # nothing reserved
    assert variant.stock_items.get().reserved == 0
    assert Cart.objects.get(id=cart.id).status == "active"  # not converted


def test_missing_idempotency_key_is_400(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    user = django_user_model.objects.create_user(email="u4@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant)
    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 400


def test_expected_total_mismatch_returns_409(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    user = django_user_model.objects.create_user(email="u5@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant)
    body = _checkout_body(cart, addr, opt)
    body["expected_total"] = "1.00"
    client = APIClient()
    client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", body, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k")
    assert r.status_code == 409
    assert r.data["error"] == "cart_changed"
