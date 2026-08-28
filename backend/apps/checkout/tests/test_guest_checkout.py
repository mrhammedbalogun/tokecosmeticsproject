"""Guest checkout (Plan-38): placement, idempotency isolation, Turnstile ordering,
the guest quote/delivery twins, token-scoped verify/pay, and claim-on-login.

The cross-guest idempotency tests exist because the dissent review found the durable
backstop (`Payment.objects.filter(idempotency_key=key, order__user=user)`) renders
`user IS NULL` for guests — one guest replaying another's key would have been handed
the other order's full payment envelope. The cart-UUID-namespaced sha256 key is the
fix; these tests are its tripwire.
"""
import pytest
from decimal import Decimal

import httpx
from django.core import mail
from rest_framework.test import APIClient

from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.orders.tokens import make_guest_order_token, make_tracking_token
from apps.payments.models import BankAccount, Payment
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db

CHECKOUT = "/api/v1/checkout/"


def _world(stock=10):
    # Mirrors test_checkout_flow._world: seeded NG/NGN fetched, not re-created.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    BankAccount.objects.create(country=ng, currency=ngn, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def _guest_cart(ng, ngn, variant, qty=2):
    cart = CartFactory(country=ng, currency=ngn)  # user=None is the factory default
    CartItem.objects.create(cart=cart, variant=variant, quantity=qty,
                            unit_price_snapshot="1000.00")
    return cart


def _address(lagos):
    return {
        "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678",
        "line1": "1 Guest Close", "landmark": "Opposite Ikeja City Mall",
        "country_code": "NG", "state_region": lagos.id,
    }


def _guest_body(cart, lagos, opt, **extra):
    return {
        "cart_id": str(cart.id), "delivery_option_id": opt.id,
        "payment_gateway": "bank_transfer",
        "guest_email": "guest@example.com", "guest_phone": "+2348012345678",
        "address": _address(lagos),
        **extra,
    }


def _post(body, key, client=None):
    return (client or APIClient()).post(
        CHECKOUT, body, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY=key
    )


# --- placement ---------------------------------------------------------------


def test_guest_happy_path_places_a_user_less_order(django_capture_on_commit_callbacks, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)

    with django_capture_on_commit_callbacks(execute=True):
        r = _post(_guest_body(cart, lagos, opt), "guest-key-1")

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.user is None
    assert order.email == "guest@example.com"
    assert order.phone == "+2348012345678"
    assert order.grand_total == Decimal("3500.00")
    # The snapshot came from the UNSAVED inline address; no Address row was written.
    assert order.shipping_address["first_name"] == "Ada"
    assert order.shipping_address["state"] == "Lagos"
    assert order.billing_address == order.shipping_address  # billing = shipping, v1
    from apps.accounts.models import Address as AddressModel

    assert AddressModel.objects.count() == 0
    assert variant.stock_items.get().reserved == 2
    assert Cart.objects.get(id=cart.id).status == "converted"
    # The guest-order token rides the 201 (the BFF turns it into an httpOnly cookie).
    assert r.data["guest_order_token"]
    assert r.data["payment"]["action"] == "bank_details"
    # The order-received mail went to the SUBMITTED address.
    assert any(m.to == ["guest@example.com"] for m in mail.outbox)


def test_guest_email_is_lowercased_and_phone_normalised(settings):
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    body = _guest_body(cart, lagos, opt, guest_email="MiXeD@Example.COM",
                       guest_phone="+234 801 234 5678")
    r = _post(body, "guest-key-norm")
    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.email == "mixed@example.com"
    assert order.phone == "+2348012345678"  # spacing stripped, E.164 kept
    # And a number with NO country code is refused with the same message
    # registration gives — the PhoneField always submits E.164, so this only
    # fires on direct API callers.
    cart2 = _guest_cart(ng, ngn, variant)
    bad = _guest_body(cart2, lagos, opt, guest_phone="08012345678")
    r2 = _post(bad, "guest-key-natl")
    assert r2.status_code == 400
    assert "guest_phone" in r2.data


def test_guest_missing_contact_or_address_is_a_400_field_error():
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    body = _guest_body(cart, lagos, opt)
    del body["guest_email"]
    del body["address"]
    r = _post(body, "guest-key-invalid")
    assert r.status_code == 400
    assert "guest_email" in r.data and "address" in r.data
    # Validation 400s never touch idempotency state: the SAME key with the fixed
    # payload proceeds instead of tripping key-reused/in-progress.
    r2 = _post(_guest_body(cart, lagos, opt), "guest-key-invalid")
    assert r2.status_code == 201, r2.data


def test_guest_cannot_check_out_someone_elses_user_cart(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    owner = django_user_model.objects.create_user(email="owner@x.com", password="pw")
    cart = CartFactory(user=owner, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1,
                            unit_price_snapshot="1000.00")
    r = _post(_guest_body(cart, lagos, opt), "guest-key-theft")
    assert r.status_code == 409
    assert r.data["error"] == "cart_not_active"
    assert Order.objects.count() == 0


# --- idempotency -------------------------------------------------------------


def test_guest_replay_returns_same_order_and_token_without_double_reserving():
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    body = _guest_body(cart, lagos, opt)
    r1 = _post(body, "guest-same")
    r2 = _post(body, "guest-same")
    assert r1.status_code == r2.status_code == 201
    assert r1.data["order_number"] == r2.data["order_number"]
    assert r2.data["guest_order_token"]  # the replay re-delivers the credential
    assert Order.objects.count() == 1
    assert variant.stock_items.get().reserved == 2


def test_same_client_key_from_two_guests_cannot_replay_each_other():
    """THE dissent blocker. Two different guests, byte-identical client key: guest B
    must get their OWN order, never a replay of guest A's envelope."""
    ng, ngn, variant, lagos, opt = _world(stock=10)
    cart_a = _guest_cart(ng, ngn, variant, qty=1)
    cart_b = _guest_cart(ng, ngn, variant, qty=1)

    ra = _post(_guest_body(cart_a, lagos, opt, guest_email="a@example.com"), "shared-key")
    rb = _post(_guest_body(cart_b, lagos, opt, guest_email="b@example.com"), "shared-key")

    assert ra.status_code == 201, ra.data
    assert rb.status_code == 201, rb.data
    assert ra.data["order_number"] != rb.data["order_number"]
    assert Order.objects.get(number=rb.data["order_number"]).email == "b@example.com"
    # And the stored keys really are namespaced — neither is the raw client key.
    assert not Payment.objects.filter(idempotency_key="shared-key").exists()


def test_guest_and_authed_same_key_do_not_collide(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    from apps.accounts.models import Address

    user = django_user_model.objects.create_user(email="au@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos)
    user_cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=user_cart, variant=variant, quantity=1,
                            unit_price_snapshot="1000.00")
    authed = APIClient()
    authed.force_authenticate(user)
    r1 = _post({"cart_id": str(user_cart.id), "address_id": addr.id,
                "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
               "both-key", client=authed)
    guest_cart = _guest_cart(ng, ngn, variant, qty=1)
    r2 = _post(_guest_body(guest_cart, lagos, opt), "both-key")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.data["order_number"] != r2.data["order_number"]


# --- Turnstile ordering -------------------------------------------------------


SECRET = "test-secret"


class _Recorder:
    def __init__(self, response):
        self.calls = []
        self.response = response

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def _siteverify(monkeypatch, *, success=True):
    from apps.accounts.turnstile import SITEVERIFY_URL

    response = httpx.Response(
        200, request=httpx.Request("POST", SITEVERIFY_URL), json={"success": success}
    )
    recorder = _Recorder(response)
    monkeypatch.setattr("apps.accounts.turnstile.httpx.post", recorder)
    return recorder


def test_guest_placement_requires_turnstile_when_gate_is_on(settings, monkeypatch):
    settings.TURNSTILE_SECRET = SECRET
    _siteverify(monkeypatch, success=False)
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    r = _post(_guest_body(cart, lagos, opt, turnstile_token="bad"), "guest-ts-1")
    assert r.status_code == 403
    assert Order.objects.count() == 0


def test_turnstile_failure_releases_the_key_for_an_immediate_retry(settings, monkeypatch):
    """A 403 must clear the inflight marker: the customer's retry carries the SAME
    Idempotency-Key with a FRESH widget token, and it has to run, not 409."""
    settings.TURNSTILE_SECRET = SECRET
    _siteverify(monkeypatch, success=False)
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    body = _guest_body(cart, lagos, opt, turnstile_token="bad")
    assert _post(body, "guest-ts-retry").status_code == 403
    _siteverify(monkeypatch, success=True)
    r = _post(body, "guest-ts-retry")
    assert r.status_code == 201, r.data


def test_replay_answers_without_consuming_a_turnstile_check(settings, monkeypatch):
    """The single-use-token collision from the dissent review: a lost-201 retry
    arrives carrying an ALREADY-CONSUMED token. The replay must answer from the
    store before Turnstile gets a vote — a rejected re-verification would strand a
    real placed order."""
    settings.TURNSTILE_SECRET = SECRET
    recorder = _siteverify(monkeypatch, success=True)
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    body = _guest_body(cart, lagos, opt, turnstile_token="one-shot")
    r1 = _post(body, "guest-ts-replay")
    assert r1.status_code == 201, r1.data
    assert len(recorder.calls) == 1
    _siteverify(monkeypatch, success=False)  # the token is now spent at Cloudflare
    r2 = _post(body, "guest-ts-replay")
    assert r2.status_code == 201
    assert r2.data["order_number"] == r1.data["order_number"]


def test_authed_checkout_is_never_turnstile_gated(settings, monkeypatch, django_user_model):
    settings.TURNSTILE_SECRET = SECRET
    recorder = _siteverify(monkeypatch, success=False)
    ng, ngn, variant, lagos, opt = _world()
    from apps.accounts.models import Address

    user = django_user_model.objects.create_user(email="nt@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG",
                                  state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1,
                            unit_price_snapshot="1000.00")
    client = APIClient()
    client.force_authenticate(user)
    r = _post({"cart_id": str(cart.id), "address_id": addr.id,
               "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
              "authed-no-ts", client=client)
    assert r.status_code == 201, r.data
    assert recorder.calls == []


# --- the guest quote/delivery twins ------------------------------------------


def test_guest_delivery_options_prices_the_inline_address():
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    r = APIClient().post(
        "/api/v1/checkout/guest/delivery-options/",
        {"cart_id": str(cart.id), "address": _address(lagos)},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 200, r.data
    assert any(o["id"] == opt.id for o in r.data)


def test_guest_delivery_options_reports_address_field_errors():
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant)
    address = _address(lagos)
    del address["line1"]
    r = APIClient().post(
        "/api/v1/checkout/guest/delivery-options/",
        {"cart_id": str(cart.id), "address": address},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 400
    assert "line1" in r.data["address"]


def test_guest_delivery_options_demands_a_real_guest_cart(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    # A user-owned cart id gets a 404 — the guest endpoints only serve guest carts.
    owner = django_user_model.objects.create_user(email="dc@x.com", password="pw")
    cart = CartFactory(user=owner, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1,
                            unit_price_snapshot="1000.00")
    r = APIClient().post(
        "/api/v1/checkout/guest/delivery-options/",
        {"cart_id": str(cart.id), "address": _address(lagos)},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 404
    # And an EMPTY guest cart is refused — the plausibility gate for the quote engine.
    empty = CartFactory(country=ng, currency=ngn)
    r = APIClient().post(
        "/api/v1/checkout/guest/delivery-options/",
        {"cart_id": str(empty.id), "address": _address(lagos)},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 400


def test_guest_quote_totals_and_per_email_coupon_limit():
    from apps.checkout.factories import CouponFactory
    from apps.checkout.models import CouponRedemption

    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    coupon = CouponFactory(usage_limit_per_user=1)
    CouponRedemption.objects.create(coupon=coupon, email="guest@example.com")

    r = APIClient().post(
        "/api/v1/checkout/guest/quote/",
        {"cart_id": str(cart.id), "address": _address(lagos),
         "delivery_option_id": opt.id, "coupon_code": coupon.code,
         "guest_email": "guest@example.com"},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r.status_code == 200, r.data
    assert r.data["totals"]["delivery"] == "1500.00"
    # The preview must refuse what place_order would refuse for this email.
    assert r.data["coupon"]["ok"] is False
    # A different email previews fine.
    r2 = APIClient().post(
        "/api/v1/checkout/guest/quote/",
        {"cart_id": str(cart.id), "address": _address(lagos),
         "delivery_option_id": opt.id, "coupon_code": coupon.code,
         "guest_email": "fresh@example.com"},
        format="json", HTTP_X_COUNTRY="NG",
    )
    assert r2.data["coupon"]["ok"] is True


# --- token-scoped verify / pay / detail --------------------------------------


def _placed_guest_order(lagos, opt, ng, ngn, variant):
    cart = _guest_cart(ng, ngn, variant, qty=1)
    r = _post(_guest_body(cart, lagos, opt), f"key-{cart.id}")
    assert r.status_code == 201, r.data
    return Order.objects.get(number=r.data["order_number"]), r.data


def test_guest_verify_with_token_and_the_refusals():
    ng, ngn, variant, lagos, opt = _world()
    order, data = _placed_guest_order(lagos, opt, ng, ngn, variant)
    reference = data["payment"]["reference"]
    token = data["guest_order_token"]

    ok = APIClient().post(f"/api/v1/payments/{reference}/verify/",
                          {"guest_token": token}, format="json")
    assert ok.status_code == 200, ok.data
    assert ok.data["order_number"] == order.number

    # No token → 403; garbage token → 404; a DIFFERENT order's token → 404 (the token
    # names the order, the reference is looked up within it).
    assert APIClient().post(f"/api/v1/payments/{reference}/verify/", {},
                            format="json").status_code == 403
    assert APIClient().post(f"/api/v1/payments/{reference}/verify/",
                            {"guest_token": "junk"}, format="json").status_code == 404
    other = make_guest_order_token("TC-999999")
    assert APIClient().post(f"/api/v1/payments/{reference}/verify/",
                            {"guest_token": other}, format="json").status_code == 404
    # A 90-day TRACKING token must never open verify — different salt, on purpose.
    tracking = make_tracking_token(order.number)
    assert APIClient().post(f"/api/v1/payments/{reference}/verify/",
                            {"guest_token": tracking}, format="json").status_code == 404


def test_guest_pay_retry_with_token_opens_a_new_attempt():
    ng, ngn, variant, lagos, opt = _world()
    order, data = _placed_guest_order(lagos, opt, ng, ngn, variant)
    token = data["guest_order_token"]

    r = APIClient().post(
        f"/api/v1/orders/{order.number}/pay/",
        {"payment_gateway": "bank_transfer", "guest_token": token},
        format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-1",
    )
    assert r.status_code == 200, r.data
    assert order.payments.count() == 2
    # Same key replays the same attempt rather than opening a third.
    r2 = APIClient().post(
        f"/api/v1/orders/{order.number}/pay/",
        {"payment_gateway": "bank_transfer", "guest_token": token},
        format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-1",
    )
    assert r2.status_code == 200
    assert order.payments.count() == 2

    # No token → 403; invalid → 404 (same code as "no such order", no oracle).
    assert APIClient().post(
        f"/api/v1/orders/{order.number}/pay/", {"payment_gateway": "bank_transfer"},
        format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-2",
    ).status_code == 403
    assert APIClient().post(
        f"/api/v1/orders/{order.number}/pay/",
        {"payment_gateway": "bank_transfer", "guest_token": "junk"},
        format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="retry-3",
    ).status_code == 404


def test_guest_order_detail_full_view_via_guest_token():
    ng, ngn, variant, lagos, opt = _world()
    order, data = _placed_guest_order(lagos, opt, ng, ngn, variant)
    token = data["guest_order_token"]

    r = APIClient().get(f"/api/v1/orders/{order.number}/", {"guest_token": token})
    assert r.status_code == 200
    # FULL serializer: the confirmation page needs the gateway and the address, and
    # the pay-again UI needs the ORDER's market for its methods list.
    assert r.data["payment_gateway"] == "bank_transfer"
    assert r.data["shipping_address"]["first_name"] == "Ada"
    assert r.data["country"] == "NG"

    # Tampered/mismatched → 404, indistinguishable from a number that never existed.
    assert APIClient().get(f"/api/v1/orders/{order.number}/",
                           {"guest_token": "junk"}).status_code == 404
    other = make_guest_order_token("TC-999999")
    assert APIClient().get(f"/api/v1/orders/{order.number}/",
                           {"guest_token": other}).status_code == 404
    # The redacted tracking path is unchanged: no payment gateway, no address.
    tr = APIClient().get(f"/api/v1/orders/{order.number}/",
                         {"token": make_tracking_token(order.number)})
    assert tr.status_code == 200
    assert "payment_gateway" not in tr.data
    assert "shipping_address" not in tr.data


# --- claim on login -----------------------------------------------------------


def test_verified_login_claims_matching_guest_orders(django_user_model):
    from django.utils import timezone

    ng, ngn, variant, lagos, opt = _world()
    order, _ = _placed_guest_order(lagos, opt, ng, ngn, variant)
    assert order.email == "guest@example.com"

    user = django_user_model.objects.create_user(
        email="guest@example.com", password="pw12345!x",
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])

    r = APIClient().post("/api/v1/auth/token/",
                         {"email": "guest@example.com", "password": "pw12345!x"},
                         format="json")
    assert r.status_code == 200
    order.refresh_from_db()
    assert order.user == user


def test_unverified_login_claims_nothing(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    order, _ = _placed_guest_order(lagos, opt, ng, ngn, variant)

    user = django_user_model.objects.create_user(
        email="guest@example.com", password="pw12345!x",
    )  # email_verified_at is None: registering a victim's address earns nothing
    r = APIClient().post("/api/v1/auth/token/",
                         {"email": "guest@example.com", "password": "pw12345!x"},
                         format="json")
    assert r.status_code == 200
    order.refresh_from_db()
    assert order.user is None


# --- guest Buy Now ------------------------------------------------------------


def test_guest_buy_now_adds_to_the_guest_cart():
    ng, ngn, variant, lagos, opt = _world()
    cart = CartFactory(country=ng, currency=ngn)
    r = APIClient().post(
        "/api/v1/checkout/buy-now/",
        {"variant_id": variant.id, "quantity": 1},
        format="json", HTTP_X_COUNTRY="NG", HTTP_X_CART_ID=str(cart.id),
    )
    assert r.status_code == 200, r.data
    assert r.data["id"] == str(cart.id)
    assert cart.items.get().variant == variant
