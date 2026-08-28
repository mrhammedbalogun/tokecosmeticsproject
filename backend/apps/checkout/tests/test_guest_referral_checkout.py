"""A referred GUEST, end to end over HTTP: preview, placement, and the money.

The unit rules live in `apps/referrals/tests/test_guest_attribution.py`. This file is the
tripwire for the wiring around them — the two places a guest's identity has to reach
`attribution_code_for_order`, which are the guest quote view and `place_order`. Both were
passing `user` alone before 2026-08-28, and `user` is None for a guest.
"""
import pytest
from decimal import Decimal

from rest_framework.test import APIClient

from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.models import Order
from apps.payments.models import BankAccount
from apps.pricing.models import Price
from apps.referrals.services import ensure_profile

pytestmark = pytest.mark.django_db

CHECKOUT = "/api/v1/checkout/"
GUEST_QUOTE = "/api/v1/checkout/guest/quote/"


def _world(stock=10):
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
    cart = CartFactory(country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=qty,
                            unit_price_snapshot="1000.00")
    return cart


def _address(lagos):
    return {
        "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678",
        "line1": "1 Guest Close", "country_code": "NG", "state_region": lagos.id,
    }


def _referrer(django_user_model, email="amina@x.com", **kwargs):
    kwargs.setdefault("password", "pw12345!")
    user = django_user_model.objects.create_user(email=email, **kwargs)
    return user, ensure_profile(user)


def test_a_guests_quote_shows_the_referral_discount(django_user_model):
    """The /cart and review previews. 2 × 1000 = 2000 goods, 5% = 100.00 off."""
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    _, profile = _referrer(django_user_model)

    r = APIClient().post(
        GUEST_QUOTE,
        {"cart_id": str(cart.id), "address": _address(lagos),
         "delivery_option_id": opt.id, "referral_code": profile.code,
         "guest_email": "shopper@example.com", "guest_phone": "+2349011111111"},
        format="json", HTTP_X_COUNTRY="NG",
    )

    assert r.status_code == 200, r.data
    assert r.data["totals"]["referral_discount"] == "100.00"
    assert r.data["totals"]["referral_discount_percent"] == "5.00"
    # 2000 goods − 100 discount + 1500 delivery
    assert r.data["totals"]["grand_total"] == "3400.00"


def test_a_self_referring_guests_quote_shows_nothing(django_user_model):
    """Caught in the PREVIEW, not at the pay button. This is what threading the guest's
    contact details into the quote view buys: without it the review screen would promise
    a discount that `place_order` then refuses, and the shopper's reward for clicking pay
    would be a `cart_changed` error sending them back to the cart."""
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    _, profile = _referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    r = APIClient().post(
        GUEST_QUOTE,
        {"cart_id": str(cart.id), "address": _address(lagos),
         "delivery_option_id": opt.id, "referral_code": profile.code,
         "guest_email": "amina@x.com", "guest_phone": "+2348012345678"},
        format="json", HTTP_X_COUNTRY="NG",
    )

    assert r.status_code == 200, r.data
    assert r.data["totals"]["referral_discount"] == "0.00"
    assert r.data["totals"]["grand_total"] == "3500.00"


def test_a_malformed_guest_phone_in_a_preview_is_not_a_400(django_user_model):
    """A guest mid-typing must not get a validation error out of a price preview."""
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    _, profile = _referrer(django_user_model)

    r = APIClient().post(
        GUEST_QUOTE,
        {"cart_id": str(cart.id), "referral_code": profile.code,
         "guest_email": "shopper@example.com", "guest_phone": "081"},
        format="json", HTTP_X_COUNTRY="NG",
    )

    assert r.status_code == 200, r.data
    assert r.data["totals"]["referral_discount"] == "100.00"


def test_a_guest_order_is_stamped_discounted_and_pays_the_referrer(
    django_capture_on_commit_callbacks, settings, django_user_model
):
    """The whole point, over HTTP: the order carries the code, the guest actually pays
    less, and once the payment succeeds the referrer has a commission."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    ref_user, profile = _referrer(django_user_model)

    with django_capture_on_commit_callbacks(execute=True):
        r = APIClient().post(
            CHECKOUT,
            {"cart_id": str(cart.id), "delivery_option_id": opt.id,
             "payment_gateway": "bank_transfer",
             "guest_email": "shopper@example.com", "guest_phone": "+2349011111111",
             "address": _address(lagos), "referral_code": profile.code},
            format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="guest-ref-1",
        )

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.user is None, "still a guest order"
    assert order.referral_code == profile.code
    assert order.referral_discount_total == Decimal("100.00")
    assert order.grand_total == Decimal("3400.00")

    from apps.referrals.services import accrue_for_order

    commission = accrue_for_order(order)
    assert commission is not None
    assert commission.referrer_id == ref_user.pk
    # The base is the goods AFTER the customer's 5% (the ordering Hammed ruled on
    # 2026-08-27) and NET of the VAT sitting inside a Nigerian price (NG is seeded
    # 7.50% tax-inclusive, and `commission_base` subtracts the embedded slice rather
    # than paying commission on the government's money):
    #   2000 goods − 100 referral discount = 1900.00 gross
    #   1900.00 / 1.075                    = 1767.44 net of VAT
    #   10% of that                        =  176.74
    assert commission.base_amount == Decimal("1767.44")
    assert commission.amount == Decimal("176.74")


def test_a_self_referring_guest_is_refused_at_placement(django_user_model):
    """The guard that stops the obvious dodge: log out, check out as a guest, type your
    own code. Full price, no stamp, nobody paid."""
    ng, ngn, variant, lagos, opt = _world()
    cart = _guest_cart(ng, ngn, variant, qty=2)
    _, profile = _referrer(django_user_model, "amina@x.com", phone="+2348012345678")

    r = APIClient().post(
        CHECKOUT,
        {"cart_id": str(cart.id), "delivery_option_id": opt.id,
         "payment_gateway": "bank_transfer",
         "guest_email": "amina@x.com", "guest_phone": "+2348012345678",
         "address": _address(lagos), "referral_code": profile.code},
        format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="guest-self-ref-1",
    )

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.referral_code == ""
    assert order.referral_discount_total == Decimal("0.00")
    assert order.grand_total == Decimal("3500.00")
