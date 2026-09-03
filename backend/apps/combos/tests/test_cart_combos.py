"""A combo in the bag: what it adds, what it must not disturb, and what it saves."""
from decimal import Decimal

import pytest

from apps.carts.factories import CartFactory
from apps.carts.models import CartComboGroup, CartItem
from apps.carts.serializers import serialize_cart
from apps.carts.services import (
    add_combo,
    add_item,
    remove_combo,
    remove_item,
    set_combo_quantity,
    set_quantity,
)
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.combos.services import cart_combo_discount

pytestmark = pytest.mark.django_db


@pytest.fixture
def cart(ng):
    return CartFactory(country=ng, currency=ng.currency)


def test_adding_a_combo_creates_one_line_per_component(ng, cart, combo):
    c = combo()
    group, added = add_combo(cart, c, 1, ng)
    assert added is True
    lines = {line.variant.sku: line.quantity for line in group.items.all()}
    assert sorted(lines.values()) == [1, 2]
    assert CartItem.objects.filter(cart=cart, combo_group__isnull=True).count() == 0


def test_component_quantities_are_the_combo_quantity_times_the_recipe(ng, cart, combo):
    c = combo()
    group, _ = add_combo(cart, c, 3, ng)
    assert sorted(line.quantity for line in group.items.all()) == [3, 6]


def test_adding_the_same_combo_again_raises_the_one_group(ng, cart, combo):
    """Two identical cards the shopper then has to reconcile is not a bag."""
    c = combo()
    add_combo(cart, c, 1, ng)
    add_combo(cart, c, 2, ng)
    assert CartComboGroup.objects.filter(cart=cart).count() == 1
    assert CartComboGroup.objects.get(cart=cart).quantity == 3


def test_the_same_variant_can_sit_standalone_and_inside_a_combo(ng, cart, combo):
    """The partial-unique split in CartItem.Meta exists for exactly this."""
    c = combo()
    shared = c.items.first().variant
    add_item(cart, shared, 2, ng)
    add_combo(cart, c, 1, ng)
    rows = CartItem.objects.filter(cart=cart, variant=shared)
    assert rows.count() == 2
    assert rows.filter(combo_group__isnull=True).get().quantity == 2


def test_editing_a_standalone_line_never_touches_the_combos_copy(ng, cart, combo):
    """`PATCH /cart/items/{variant}` must not silently resize a bundle."""
    c = combo()
    shared = c.items.first().variant
    add_item(cart, shared, 2, ng)
    add_combo(cart, c, 1, ng)

    set_quantity(cart, shared, 5, ng)
    assert CartItem.objects.get(cart=cart, variant=shared, combo_group__isnull=True).quantity == 5
    assert CartItem.objects.get(cart=cart, variant=shared, combo_group__isnull=False).quantity == 1

    remove_item(cart, shared, ng)
    assert CartItem.objects.filter(cart=cart, variant=shared).count() == 1


def test_resizing_a_group_rewrites_every_component_line(ng, cart, combo):
    c = combo()
    group, _ = add_combo(cart, c, 1, ng)
    set_combo_quantity(cart, group, 4, ng)
    assert sorted(line.quantity for line in group.items.all()) == [4, 8]


def test_setting_a_group_to_zero_removes_it_and_its_lines(ng, cart, combo):
    c = combo()
    group, _ = add_combo(cart, c, 2, ng)
    set_combo_quantity(cart, group, 0, ng)
    assert not CartComboGroup.objects.filter(cart=cart).exists()
    assert not CartItem.objects.filter(cart=cart).exists()


def test_removing_a_group_takes_its_lines_with_it(ng, cart, combo):
    c = combo()
    group, _ = add_combo(cart, c, 1, ng)
    remove_combo(cart, group)
    assert not CartItem.objects.filter(cart=cart).exists()


def test_a_combo_is_capped_at_the_scarcest_component(ng, cart, priced_variant):
    scarce = priced_variant("500.00", stock=3)
    c = ComboFactory()
    ComboItemFactory(combo=c, variant=priced_variant("1000.00", stock=100), quantity=1)
    ComboItemFactory(combo=c, variant=scarce, quantity=2)

    group, added = add_combo(cart, c, 5, ng)
    assert added is True
    assert group.quantity == 1  # 3 // 2

    _, added_again = add_combo(cart, c, 1, ng)
    assert added_again is False  # the cap ate the whole request


def test_editing_the_combo_prunes_a_dropped_component_from_live_carts(ng, cart, combo):
    """The group is priced as the combo is defined TODAY, so it must contain what the
    combo says today."""
    c = combo()
    group, _ = add_combo(cart, c, 1, ng)
    dropped = c.items.first()
    dropped_variant = dropped.variant
    dropped.delete()

    set_combo_quantity(cart, group, 2, ng)
    assert not group.items.filter(variant=dropped_variant).exists()


def test_the_cart_reports_the_saving_and_a_total_net_of_it(ng, cart, combo):
    c = combo()
    add_combo(cart, c, 2, ng)
    assert cart_combo_discount(cart, ng) == Decimal("400.00")

    payload = serialize_cart(cart, ng)
    assert payload["subtotal"] == "4000.00"
    assert payload["combo_discount"] == "400.00"
    assert payload["total"] == "3600.00"
    # Components are nested in the combo, never doubled into `items`.
    assert payload["items"] == []
    assert payload["combos"][0]["quantity"] == 2
    assert payload["combos"][0]["line_total"] == "3600.00"
    assert len(payload["combos"][0]["items"]) == 2


def test_standalone_and_combo_money_add_up_together(ng, cart, combo, priced_variant):
    c = combo()
    add_combo(cart, c, 1, ng)
    add_item(cart, priced_variant("250.00"), 2, ng)
    payload = serialize_cart(cart, ng)
    assert payload["subtotal"] == "2500.00"      # 2000 combo parts + 500 standalone
    assert payload["combo_discount"] == "200.00"
    assert payload["total"] == "2300.00"


def test_a_combo_that_stopped_pricing_falls_back_to_full_price_goods(ng, cart, combo):
    """The goods are real; only the deal has lapsed. It must not become free."""
    c = combo()
    add_combo(cart, c, 1, ng)
    c.items.first().variant.prices.all().delete()

    assert cart_combo_discount(cart, ng) == Decimal("0.00")
    payload = serialize_cart(cart, ng)
    assert payload["combos"][0]["unavailable"] is True
    assert payload["has_unavailable"] is True


def test_archiving_a_combo_withdraws_the_deal_from_baskets_holding_it(ng, cart, combo):
    """Archiving is what a merchant reaches for when the price was WRONG. If baskets
    already holding the bundle kept charging it, archiving would not do the one job it is
    reached for. The goods stay — only the deal ends."""
    c = combo()
    add_combo(cart, c, 1, ng)
    assert cart_combo_discount(cart, ng) == Decimal("200.00")

    c.status = "archived"
    c.save(update_fields=["status"])

    assert cart_combo_discount(cart, ng) == Decimal("0.00")
    payload = serialize_cart(cart, ng)
    group = payload["combos"][0]
    # `ended`, not `unavailable`: the DEAL is off, the goods are not.
    assert group["ended"] is True
    assert group["unavailable"] is False
    assert group["saving"] == "0.00"
    # The components are still in the bag at their own prices — the shopper has not been
    # emptied out, they have simply stopped getting a discount. If this said 0.00 the
    # cart would show as free goods the till charges ₦2,000 for.
    assert payload["subtotal"] == "2000.00"
    assert payload["combo_discount"] == "0.00"
    assert payload["total"] == "2000.00"


def test_withdrawing_a_combo_from_a_market_does_the_same(ng, cart, combo):
    from apps.core.models import Country

    c = combo()
    add_combo(cart, c, 1, ng)
    c.available_countries.add(Country.objects.get(code="GB"))

    assert cart_combo_discount(cart, ng) == Decimal("0.00")
    payload = serialize_cart(cart, ng)
    assert payload["combos"][0]["ended"] is True
    assert payload["total"] == "2000.00"
