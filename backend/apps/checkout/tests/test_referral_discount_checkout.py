"""`place_order` end to end with a referral code (2026-08-27).

The unit tests either side of this one are green even if the wiring is wrong: totals can
apply a discount it is handed, and `commission_base` can subtract a column somebody else
filled in. What only an integration test catches is the ORDERING — attribution used to be
resolved nine lines AFTER `compute_totals`, and a discount worked out from a code that had
not been resolved yet is silently always zero.
"""
from decimal import Decimal

import pytest

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.checkout.services.checkout import place_order
from apps.core.models import BusinessDecisions, Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price
from apps.referrals.services import ensure_profile

pytestmark = pytest.mark.django_db


def _world():
    ng = Country.objects.get(code="NG")
    warehouse = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    warehouse.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    option = DeliveryOptionFactory(currency=ng.currency, name="Lagos Flat", price="1500.00")
    option.regions.add(lagos)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ng.currency, amount=Decimal("10000.00"))
    StockItemFactory(variant=variant, warehouse=warehouse, quantity=50)
    return ng, variant, lagos, option


def _buy(user, ng, variant, lagos, option, *, key, referral_code="", quantity=1,
         expected_total=None):
    address = Address.objects.create(
        user=user, line1="1 Awolowo Rd", country_code="NG", state_region=lagos
    )
    # A customer may hold only one ACTIVE standard cart (`uniq_active_cart_per_user_kind`),
    # so a second buy for the same person reuses the one already there. That is also what
    # really happens: a refused checkout leaves the cart active and the shopper tries again
    # with the same bag, which is exactly the sequence the expected_total test needs.
    cart = Cart.objects.filter(user=user, kind="standard", status="active").first()
    if cart is None:
        cart = CartFactory(user=user, country=ng, currency=ng.currency)
    cart.items.all().delete()
    CartItem.objects.create(cart=cart, variant=variant, quantity=quantity,
                            unit_price_snapshot="10000.00")
    return place_order(
        user=user, country=ng, key=key, cart_id=cart.id, address_id=address.id,
        delivery_option_id=option.id, payment_gateway="bank_transfer",
        referral_code=referral_code, expected_total=expected_total,
    )


@pytest.fixture(autouse=True)
def _bank_account():
    """bank_transfer refuses to be offered without a configured account, and that refusal
    fires before anything is reserved."""
    from apps.payments.models import BankAccount

    ng = Country.objects.get(code="NG")
    BankAccount.objects.get_or_create(
        country=ng,
        defaults={
            "currency": ng.currency,
            "bank_name": "Test Bank",
            "account_name": "Toke",
            "account_number": "0011223344",
        },
    )


def test_place_order_applies_the_discount_and_stamps_the_rate(django_user_model):
    """The whole feature, in one order: 10,000 of goods, 5% off, 1,500 delivery."""
    ng, variant, lagos, option = _world()
    buyer = django_user_model.objects.create_user(email="buyer@x.com", password="pw12345!")
    referrer = django_user_model.objects.create_user(email="ref@x.com", password="pw12345!")
    code = ensure_profile(referrer).code

    order = _buy(buyer, ng, variant, lagos, option, key="ref-1", referral_code=code).order
    order.refresh_from_db()

    assert order.referral_code == code
    assert order.subtotal == Decimal("10000.00")
    assert order.referral_discount_total == Decimal("500.00")
    assert order.referral_discount_percent == Decimal("5.00")
    # 10,000 − 500 + 1,500 delivery. If attribution were still resolved after the totals,
    # this would read 11,500 and every assertion above would still pass on a later write.
    assert order.grand_total == Decimal("11000.00")


def test_an_order_with_no_code_is_untouched(django_user_model):
    ng, variant, lagos, option = _world()
    buyer = django_user_model.objects.create_user(email="plain@x.com", password="pw12345!")

    order = _buy(buyer, ng, variant, lagos, option, key="plain-1").order

    assert order.referral_discount_total == Decimal("0.00")
    assert order.referral_discount_percent == Decimal("0.00")
    assert order.grand_total == Decimal("11500.00")


def test_a_self_referral_is_charged_full_price(django_user_model):
    """The refusal that stops the programme becoming a permanent 5%-off sale. The order is
    placed — it is a perfectly good order — it simply earns nobody anything."""
    ng, variant, lagos, option = _world()
    buyer = django_user_model.objects.create_user(email="self@x.com", password="pw12345!")
    code = ensure_profile(buyer).code

    order = _buy(buyer, ng, variant, lagos, option, key="self-1", referral_code=code).order

    assert order.referral_code == ""
    assert order.referral_discount_total == Decimal("0.00")
    assert order.grand_total == Decimal("11500.00")


def test_the_expected_total_guard_sees_the_discounted_number(django_user_model):
    """The storefront sends back the total its quote showed. Both sides now read the same
    referral code and the same `BusinessDecisions` row, so a referred order must place
    against the DISCOUNTED total — and must be refused against the undiscounted one."""
    from apps.checkout.services.checkout import CheckoutError

    ng, variant, lagos, option = _world()
    buyer = django_user_model.objects.create_user(email="guard@x.com", password="pw12345!")
    referrer = django_user_model.objects.create_user(email="ref2@x.com", password="pw12345!")
    code = ensure_profile(referrer).code

    with pytest.raises(CheckoutError) as exc:
        _buy(buyer, ng, variant, lagos, option, key="guard-1", referral_code=code,
             expected_total=Decimal("11500.00"))
    assert exc.value.code == "cart_changed"
    # The refusal hands back the real numbers so the summary can redraw with the row it
    # was missing, rather than showing totals that do not add up.
    assert exc.value.extra["totals"]["referral_discount"] == "500.00"

    assert _buy(buyer, ng, variant, lagos, option, key="guard-2", referral_code=code,
                expected_total=Decimal("11000.00")).order.number


def test_turning_the_discount_off_leaves_the_commission_side_working(django_user_model):
    """0% is an off switch, not a broken state: the order still carries its referral code,
    so the referrer is still paid."""
    row = BusinessDecisions.load()
    row.customer_discount_percent = Decimal("0.00")
    row.save()

    ng, variant, lagos, option = _world()
    buyer = django_user_model.objects.create_user(email="off@x.com", password="pw12345!")
    referrer = django_user_model.objects.create_user(email="ref3@x.com", password="pw12345!")
    code = ensure_profile(referrer).code

    order = _buy(buyer, ng, variant, lagos, option, key="off-1", referral_code=code).order

    assert order.referral_code == code
    assert order.referral_discount_total == Decimal("0.00")
    assert order.grand_total == Decimal("11500.00")
