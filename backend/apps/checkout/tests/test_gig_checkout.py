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
    gig_option = DeliveryOption.objects.get(carrier_code="gig", carrier_service="home")
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

    # Slice 4: the shipment is born quoted, in the same transaction, with the
    # checkout-time snapshot fulfilment and reconciliation will read.
    shipment = order.gig_shipment
    assert shipment.status == "quoted"
    assert shipment.charged == Decimal("4175.20")
    assert shipment.quote["breakdown"]["GrandTotal"] == 4175.2
    assert shipment.quote["api_id"] == "q-1"
    assert shipment.cost is None  # nothing debited until capture


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


# --- Centre pickup placement (32b slice 4) ---

def _pickup_world():
    """_world() plus: the dark pickup option activated and two centres, one near
    Ikeja (Oregun) and one far (Victoria Island) — distance must not matter to
    placement, the CUSTOMER's choice does (ruling 3)."""
    from apps.delivery.models import GigCentre

    world = _world()
    pickup = DeliveryOption.objects.get(carrier_code="gig", carrier_service="pickup")
    pickup.is_active = True
    pickup.save(update_fields=["is_active"])
    near = GigCentre.objects.create(
        gig_centre_id=101, gig_station_id=4, name="GIG Oregun",
        address="52 Oregun Rd, Ikeja", latitude="6.617000", longitude="3.365000",
        is_active=True, synced_at=timezone.now(),
    )
    far = GigCentre.objects.create(
        gig_centre_id=202, gig_station_id=4, name="GIG Victoria Island",
        address="1 Adeola Odeku, VI", latitude="6.428000", longitude="3.421000",
        is_active=True, synced_at=timezone.now(),
    )
    return (*world, pickup, near, far)


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_placement_requotes_the_chosen_centre_and_snapshots_it(django_user_model):
    """The list priced pickup to the NEAREST centre; the customer chose the FAR
    one. Placement re-quotes the chosen centre (different price), charges that,
    and snapshots the centre onto the shipment (rulings 3 + 4)."""
    def price_by_receiver(request):
        import json as jsonlib

        body = jsonlib.loads(request.content)
        lat = body["ReceiverLocation"]["Latitude"]
        total = 3899.27 if abs(lat - 6.617) < 0.01 else 5150.00  # near vs far centre
        return httpx.Response(200, json=_quote_envelope(total))

    respx.post(f"{BASE}/price/v3").mock(side_effect=price_by_receiver)
    ng, ngn, variant, lagos, ikeja, gig_option, pickup, near, far = _pickup_world()
    user = django_user_model.objects.create_user(email="pick@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="12 Allen Ave", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)

    # The centre list the picker shows — nearest first.
    r = api.get(f"/api/v1/checkout/gig-centres/?address_id={addr.id}", HTTP_X_COUNTRY="NG")
    assert [c["id"] for c in r.json()] == [near.gig_centre_id, far.gig_centre_id]

    r = api.post("/api/v1/checkout/",
                 {"cart_id": str(cart.id), "address_id": addr.id,
                  "delivery_option_id": pickup.id, "payment_gateway": "bank_transfer",
                  "gig_centre_id": far.gig_centre_id},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pick-1")
    assert r.status_code in (200, 201), r.content
    order = Order.objects.get(user=user)
    assert order.shipping_total == Decimal("5150.00")  # the CHOSEN centre's price
    shipment = order.gig_shipment
    assert shipment.centre == {"id": 202, "station_id": 4, "name": "GIG Victoria Island",
                               "address": "1 Adeola Odeku, VI"}
    assert shipment.quote["breakdown"]["GrandTotal"] == 5150.00

    # The customer surface names the centre from the snapshot, waybill or not.
    r = api.get(f"/api/v1/orders/{order.number}/", HTTP_X_COUNTRY="NG")
    assert r.json()["pickup_centre"]["name"] == "GIG Victoria Island"


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_without_a_centre_or_with_a_dead_centre_is_refused(django_user_model):
    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(3899.27)))
    ng, ngn, variant, lagos, ikeja, gig_option, pickup, near, far = _pickup_world()
    user = django_user_model.objects.create_user(email="pick2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="12 Allen Ave", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)
    base = {"cart_id": str(cart.id), "address_id": addr.id,
            "delivery_option_id": pickup.id, "payment_gateway": "bank_transfer"}

    r = api.post("/api/v1/checkout/", base, format="json",
                 HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pick-2")
    assert r.status_code == 409
    assert r.json()["error"] == "centre_required"

    far.is_active = False
    far.save(update_fields=["is_active"])
    r = api.post("/api/v1/checkout/", {**base, "gig_centre_id": far.gig_centre_id},
                 format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pick-3")
    assert r.status_code == 409
    assert r.json()["error"] == "centre_invalid"
    assert Order.objects.filter(user=user).count() == 0


@override_settings(**SETTINGS)
@respx.mock
def test_pickup_confirmation_email_says_collect_from(django_user_model, django_capture_on_commit_callbacks):
    from django.core import mail

    respx.post(f"{BASE}/price/v3").mock(return_value=httpx.Response(200, json=_quote_envelope(3899.27)))
    ng, ngn, variant, lagos, ikeja, gig_option, pickup, near, far = _pickup_world()
    user = django_user_model.objects.create_user(email="pick3@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="12 Allen Ave", country_code="NG",
                                  state_region=lagos, area_region=ikeja)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    api = APIClient()
    api.force_authenticate(user)
    with django_capture_on_commit_callbacks(execute=True):
        r = api.post("/api/v1/checkout/",
                     {"cart_id": str(cart.id), "address_id": addr.id,
                      "delivery_option_id": pickup.id, "payment_gateway": "bank_transfer",
                      "gig_centre_id": near.gig_centre_id},
                     format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="pick-4")
    assert r.status_code in (200, 201), r.content
    order = Order.objects.get(user=user)

    # Bank transfer: placement sends order_received (no address block); the
    # CONFIRMATION fires on the paid->processing move — force it and check.
    from apps.orders.state import transition
    with django_capture_on_commit_callbacks(execute=True):
        transition(Order.objects.select_for_update().get(pk=order.pk), "processing",
                   message="test payment")
    confirmations = [m for m in mail.outbox if "getting it ready" in m.body]
    assert confirmations, [m.subject for m in mail.outbox]
    confirmation = confirmations[0]
    assert "Collect from" in confirmation.body
    assert "GIG Oregun" in confirmation.body
    assert "photo ID" in confirmation.body
    assert "Delivering to" not in confirmation.body
