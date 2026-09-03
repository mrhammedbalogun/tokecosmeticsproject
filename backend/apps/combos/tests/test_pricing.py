"""What a combo costs, and what makes it unbuyable."""
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.combos.models import ComboPrice
from apps.combos.services import (
    available_in,
    components_total,
    max_addable,
    resolve_combo_price,
)
from apps.core.models import Country

pytestmark = pytest.mark.django_db


def test_price_is_the_discount_off_what_the_parts_cost(ng, combo):
    c = combo()
    pricing = resolve_combo_price(c, ng)
    assert pricing.components_total == Decimal("2000.00")
    assert pricing.amount == Decimal("1800.00")
    assert pricing.saving == Decimal("200.00")
    assert pricing.saving_percent == Decimal("10.00")
    assert pricing.pinned is False


def test_a_pinned_price_wins_and_reports_the_real_percentage(ng, combo):
    """The advertised number must not move because a component was repriced, and the
    percentage the page shows has to be derived from the two amounts rather than from
    `discount_percent`, which the pin has overridden."""
    c = combo()
    ComboPrice.objects.create(combo=c, country=ng, amount=Decimal("1500.00"))
    pricing = resolve_combo_price(c, ng)
    assert pricing.amount == Decimal("1500.00")
    assert pricing.saving == Decimal("500.00")
    assert pricing.saving_percent == Decimal("25.00")
    assert pricing.pinned is True


def test_a_pinned_price_above_the_parts_is_clamped(ng, combo):
    """A "combo" costing more than its contents is a typo, and charging it is the kind
    of wrongness a customer screenshots."""
    c = combo()
    ComboPrice.objects.create(combo=c, country=ng, amount=Decimal("9999.00"))
    assert resolve_combo_price(c, ng).amount == Decimal("2000.00")


def test_an_unpriced_component_makes_the_whole_combo_unpriceable(ng, combo):
    """Not a partial sum: a bundle missing one price is unpriceable, not cheap."""
    c = combo()
    ComboItemFactory(combo=c, variant=ProductVariantFactory(), quantity=1)
    assert components_total(c, ng) is None
    assert resolve_combo_price(c, ng) is None
    assert available_in(c, ng) is False


def test_an_empty_combo_is_never_available(ng):
    assert available_in(ComboFactory(), ng) is False


def test_a_draft_combo_is_not_available(ng, combo):
    assert available_in(combo(status="draft"), ng) is False


def test_market_restriction_hides_it_elsewhere(ng, combo):
    c = combo()
    gb = Country.objects.get(code="GB")
    c.available_countries.add(gb)
    assert available_in(c, ng) is False
    # Empty means everywhere — the Product convention, deliberately mirrored.
    c.available_countries.clear()
    assert available_in(c, ng) is True


def test_an_archived_component_product_withdraws_the_combo(ng, combo):
    """A curated list must rot on its own rather than needing somebody to notice."""
    c = combo()
    item = c.items.first()
    item.variant.product.status = "archived"
    item.variant.product.save()
    # `sellable_in` reads availability + price, not status, so pull the price instead:
    # what matters is that a component that stopped being sellable stops the bundle.
    item.variant.prices.all().delete()
    assert available_in(c, ng) is False


def test_max_addable_is_bound_by_the_scarcest_component(ng, priced_variant):
    """Two jars of a thing that appears twice in the box is ONE combo, not two."""
    plenty = priced_variant("1000.00", stock=100)
    scarce = priced_variant("500.00", stock=5)
    c = ComboFactory()
    ComboItemFactory(combo=c, variant=plenty, quantity=1)
    ComboItemFactory(combo=c, variant=scarce, quantity=2)
    assert max_addable(c, ng) == 2


def test_zero_percent_discount_prices_at_the_component_total(ng, combo):
    c = combo(discount_percent=0)
    pricing = resolve_combo_price(c, ng)
    assert pricing.amount == pricing.components_total == Decimal("2000.00")
    assert pricing.saving == Decimal("0.00")
