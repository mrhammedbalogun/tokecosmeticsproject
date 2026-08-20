"""Plan-40: customer pickup at a Toke store — the zero-fee "store_pickup" option.

Matching is BY STATE (the ruling: every opted-in Lagos store shows to every Lagos
customer, whatever the LGA), gated to NG + NGN, and only rows with
`customer_pickup=True` ever surface. Placement snapshots the chosen store onto
`Order.pickup_store`; the `shipped` move then mails "ready for pickup" instead of
"on its way".
"""
from decimal import Decimal

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.models import GigShipment, SenderLocation
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.orders.state import transition_by_id
from apps.payments.models import BankAccount
from apps.pricing.models import Price
from apps.shipping.models import ShippingQuote

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _locmem(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


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
    ikeja = Region.objects.get(country_code="NG", level="area", parent=lagos, name="Ikeja")
    return ng, ngn, variant, lagos, ikeja


def _store(state_region, name="Ogudu Mall (Lagos)", **kw):
    return SenderLocation.objects.create(**{
        "name": name, "phone": "+2347074800702",
        "address": "Shop No 1, Ogudu Mall, Kosofe, Ogudu, Lagos",
        "locality": "Ogudu", "latitude": "6.576522", "longitude": "3.389387",
        "customer_pickup": True, "state_region": state_region, **kw,
    })


def _cart(user, ng, ngn, variant):
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=2, unit_price_snapshot="1000.00")
    return cart


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _address(user, lagos, ikeja):
    return Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos, area_region=ikeja)


def test_the_option_lists_for_a_same_state_address_with_the_stores_inside(django_user_model):
    ng, ngn, variant, lagos, ikeja = _world()
    store = _store(lagos)
    # An LGA far from the store's own — state is the match, the LGA must not matter.
    user = django_user_model.objects.create_user(email="sp@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).get(
        f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
        HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 200, r.data
    option = next(o for o in r.data if o["id"] == "store_pickup")
    assert option["name"] == "Pickup at Toke Cosmetics Store"
    assert option["kind"] == "store"
    assert option["price"] == "0.00"
    # The picker's whole dataset rides the option: full address AND the counter phone.
    assert option["stores"] == [{
        "id": store.id, "name": store.name, "address": store.address,
        "phone": store.phone,
    }]


def test_a_gig_only_origin_and_another_state_never_surface(django_user_model):
    ng, ngn, variant, lagos, ikeja = _world()
    # Opted OUT: a plain GIG collection origin (the default) must stay staff-only.
    _store(lagos, name="Warehouse", customer_pickup=False)
    # Opted in, but in another state.
    fct = Region.objects.get(country_code="NG", level="state", name="Federal Capital Territory", parent=None)
    _store(fct, name="Kubwa (Abuja)")
    user = django_user_model.objects.create_user(email="sp2@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).get(
        f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
        HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 200, r.data
    assert not any(o["id"] == "store_pickup" for o in r.data)


def test_an_order_lands_on_store_pickup_at_zero_fee(django_user_model):
    ng, ngn, variant, lagos, ikeja = _world()
    store = _store(lagos)
    user = django_user_model.objects.create_user(email="sp3@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": "store_pickup", "pickup_store_id": store.id,
        "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="sp-key-1")

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.delivery_option_name == "Pickup at Toke Cosmetics Store"
    assert order.shipping_total == Decimal("0.00")
    # The snapshot is the order's whole record of WHERE — it must survive store edits.
    assert order.pickup_store == {
        "id": store.id, "name": store.name, "address": store.address,
        "phone": store.phone, "state": "Lagos",
    }
    # kind="store" trips neither carrier hook: no courier, no freight quote.
    assert not GigShipment.objects.filter(order=order).exists()
    assert not ShippingQuote.objects.filter(order=order).exists()


def test_the_store_is_not_optional(django_user_model):
    ng, ngn, variant, lagos, ikeja = _world()
    _store(lagos)
    user = django_user_model.objects.create_user(email="sp4@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": "store_pickup",
        "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="sp-key-2")

    assert r.status_code == 409
    assert r.data["error"] == "store_required"


def test_a_store_outside_the_address_state_is_refused(django_user_model):
    """The server-side re-check is the fence: a Lagos customer submitting an Abuja
    store id must get store_invalid, never an order the Abuja counter can't hand over."""
    ng, ngn, variant, lagos, ikeja = _world()
    _store(lagos)
    fct = Region.objects.get(country_code="NG", level="state", name="Federal Capital Territory", parent=None)
    abuja = _store(fct, name="Kubwa (Abuja)")
    user = django_user_model.objects.create_user(email="sp5@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": "store_pickup", "pickup_store_id": abuja.id,
        "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="sp-key-3")

    assert r.status_code == 409
    assert r.data["error"] == "store_invalid"


def test_shipped_mails_ready_for_pickup_not_on_its_way(
    django_user_model, django_capture_on_commit_callbacks
):
    """Same status button, different truth: a store-pickup order's `shipped` move
    tells the customer to come and collect — with the store's address and phone."""
    ng, ngn, variant, lagos, ikeja = _world()
    store = _store(lagos)
    user = django_user_model.objects.create_user(email="sp6@x.com", password="pw")
    addr = _address(user, lagos, ikeja)
    cart = _cart(user, ng, ngn, variant)

    r = _client(user).post("/api/v1/checkout/", {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": "store_pickup", "pickup_store_id": store.id,
        "payment_gateway": "bank_transfer",
    }, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="sp-key-4")
    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "processing", effects=())
    with django_capture_on_commit_callbacks(execute=True):
        transition_by_id(order.pk, "shipped")

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "ready for pickup" in msg.subject
    assert store.address in msg.body
    assert store.phone in msg.body
