"""Buying a combo: the money on the order, the stock actually held, and the labels the
receipt needs."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.services import add_combo, add_item
from apps.catalog.factories import ProductVariantFactory
from apps.checkout.services.totals import compute_totals
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem
from apps.orders.models import Order
from apps.payments.models import BankAccount
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    """NG, a warehouse, a flat Lagos delivery option and a bank account to pay into."""
    ng = Country.objects.get(code="NG")
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ng.currency, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    BankAccount.objects.create(country=ng, currency=ng.currency, bank_name="GTBank",
                               account_name="Toke Cosmetics Ltd", account_number="0123456789")
    return ng, wh, lagos, opt


def _variant(ng, wh, amount, stock):
    v = ProductVariantFactory()
    Price.objects.create(variant=v, currency=ng.currency, amount=Decimal(amount))
    StockItemFactory(variant=v, warehouse=wh, quantity=stock)
    return v


def _place(user, cart, addr, opt, key="k1", country="NG"):
    client = APIClient()
    client.force_authenticate(user)
    return client.post(
        "/api/v1/checkout/",
        {"cart_id": str(cart.id), "address_id": addr.id,
         "delivery_option_id": opt.id, "payment_gateway": "bank_transfer"},
        format="json", HTTP_X_COUNTRY=country, HTTP_IDEMPOTENCY_KEY=key,
    )


def test_the_combo_saving_lands_on_the_order_as_its_own_line(django_user_model, world):
    ng, wh, lagos, opt = world
    a = _variant(ng, wh, "1000.00", 50)
    b = _variant(ng, wh, "500.00", 50)
    combo = ComboFactory(discount_percent=10)
    ComboItemFactory(combo=combo, variant=a, quantity=1)
    ComboItemFactory(combo=combo, variant=b, quantity=2)

    user = django_user_model.objects.create_user(email="c@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ng.currency)
    add_combo(cart, combo, 2, ng)

    r = _place(user, cart, addr, opt)
    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.subtotal == Decimal("4000.00")            # list price of the parts
    assert order.combo_discount_total == Decimal("400.00")  # 10% of 4,000
    # goods 3,600 + delivery 1,500; NG prices are tax-inclusive so the total does not move
    assert order.grand_total == Decimal("5100.00")


def test_order_items_are_real_variants_labelled_with_their_bundle(django_user_model, world):
    """Fulfilment sees the goods, not a phantom combo SKU — which is the whole reason a
    combo has no variant of its own."""
    ng, wh, lagos, opt = world
    a = _variant(ng, wh, "1000.00", 50)
    b = _variant(ng, wh, "500.00", 50)
    combo = ComboFactory(name="Glow Kit")
    ComboItemFactory(combo=combo, variant=a, quantity=1)
    ComboItemFactory(combo=combo, variant=b, quantity=2)

    user = django_user_model.objects.create_user(email="c2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ng.currency)
    add_combo(cart, combo, 1, ng)

    order = Order.objects.get(number=_place(user, cart, addr, opt).data["order_number"])
    items = {i.sku: i for i in order.items.all()}
    assert {i.combo_name for i in items.values()} == {"Glow Kit"}
    assert {i.combo_group for i in items.values()} == {1}
    # Line prices stay the components' own; the saving is one number on the order.
    assert items[a.sku].unit_price == Decimal("1000.00")
    assert items[b.sku].quantity == 2


def test_a_variant_bought_both_ways_reserves_the_full_quantity(django_user_model, world):
    """THE BUG THIS PINS: `inventory.reserve` is idempotent per reference, so a second
    call under the same order number is a no-op. Reserving line by line would hold the
    standalone 2 and silently skip the combo's 3 — an oversell of exactly the bundle."""
    ng, wh, lagos, opt = world
    shared = _variant(ng, wh, "1000.00", 20)
    other = _variant(ng, wh, "500.00", 20)
    combo = ComboFactory()
    ComboItemFactory(combo=combo, variant=shared, quantity=3)
    ComboItemFactory(combo=combo, variant=other, quantity=1)

    user = django_user_model.objects.create_user(email="c3@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ng.currency)
    add_item(cart, shared, 2, ng)
    add_combo(cart, combo, 1, ng)

    assert _place(user, cart, addr, opt).status_code == 201
    assert StockItem.objects.get(variant=shared, warehouse=wh).reserved == 5
    assert StockItem.objects.get(variant=other, warehouse=wh).reserved == 1


def test_a_coupon_discounts_the_bundle_price_not_the_list_price(world):
    """Otherwise a combo plus a coupon can pay the customer to shop."""
    ng, wh, _, _ = world
    from apps.checkout.factories import CouponFactory

    v = _variant(ng, wh, "1000.00", 50)
    coupon = CouponFactory(type="percent", value="50", currency=ng.currency)
    totals = compute_totals(
        [(v, 4)], ng, coupon=coupon, combo_discount=Decimal("400.00")
    )
    assert totals.subtotal == Decimal("4000.00")
    assert totals.combo_discount == Decimal("400.00")
    assert totals.discount == Decimal("1800.00")   # 50% of 3,600, not of 4,000
    assert totals.grand_total == Decimal("1800.00")


def test_the_combo_saving_leaves_the_referral_commission_base(django_user_model, world):
    """A referrer earns their cut of what the customer paid for the goods, not of a list
    price nobody paid — the rule coupons and the customer discount already follow."""
    from apps.referrals.services import commission_base

    ng, wh, lagos, opt = world
    a = _variant(ng, wh, "1000.00", 50)
    combo = ComboFactory(discount_percent=10)
    ComboItemFactory(combo=combo, variant=a, quantity=2)

    user = django_user_model.objects.create_user(email="c4@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ng.currency)
    add_combo(cart, combo, 1, ng)

    order = Order.objects.get(number=_place(user, cart, addr, opt).data["order_number"])
    assert order.subtotal == Decimal("2000.00")
    assert order.combo_discount_total == Decimal("200.00")
    # NG prices include 7.5% VAT, so the item tax comes out too: 1,800 - 1,800*(7.5/107.5)
    expected = Decimal("1800.00") - (order.tax_total - order.delivery_tax_total)
    assert commission_base(order) == expected


def test_combo_free_lines_are_untouched_by_the_new_argument(world):
    """The default path has to stay byte-identical for every order that has no bundle."""
    ng, wh, _, _ = world
    v = _variant(ng, wh, "1000.00", 50)
    assert compute_totals([(v, 2)], ng) == compute_totals(
        [(v, 2)], ng, combo_discount=Decimal("0.00")
    )


def test_two_different_combos_sharing_a_component(django_user_model, world):
    """The reservation aggregation is per VARIANT across the whole cart, not per group —
    so two bundles that both contain the shea butter must reserve the sum. And the two
    boxes must stay tellable apart on the packing slip even though they share a line."""
    ng, wh, lagos, opt = world
    shared = _variant(ng, wh, "500.00", 50)
    only_a = _variant(ng, wh, "1000.00", 50)
    only_b = _variant(ng, wh, "2000.00", 50)

    a = ComboFactory(name="Kit A", slug="kit-a", discount_percent=10)
    ComboItemFactory(combo=a, variant=only_a, quantity=1)
    ComboItemFactory(combo=a, variant=shared, quantity=2)

    b = ComboFactory(name="Kit B", slug="kit-b", discount_percent=10)
    ComboItemFactory(combo=b, variant=only_b, quantity=1)
    ComboItemFactory(combo=b, variant=shared, quantity=3)

    user = django_user_model.objects.create_user(email="c5@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = CartFactory(user=user, country=ng, currency=ng.currency)
    add_combo(cart, a, 1, ng)
    add_combo(cart, b, 2, ng)

    r = _place(user, cart, addr, opt)
    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])

    # 2 (from A) + 3x2 (from B) = 8 of the shared variant, held once.
    assert StockItem.objects.get(variant=shared, warehouse=wh).reserved == 8

    # Two bundles, two group numbers — a packer can fill two boxes from one order.
    groups = {i.combo_name: i.combo_group for i in order.items.all()}
    assert set(groups) == {"Kit A", "Kit B"}
    assert sorted(groups.values()) == [1, 2]

    # Money: A is 2,000 of parts (-200), B is 2x3,500 (-700).
    assert order.subtotal == Decimal("9000.00")
    assert order.combo_discount_total == Decimal("900.00")
