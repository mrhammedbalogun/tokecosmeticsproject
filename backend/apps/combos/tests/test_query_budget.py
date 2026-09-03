"""The public combo list must not grow a quadratic.

WHY A BUDGET AND NOT A TARGET. The list is cached for 60s and holds a curated handful, so
the absolute number matters less than the SHAPE: what this pins is that adding a combo
adds a bounded amount of work, and that the three separate "what does this cost" questions
the read path asks (`available_in`, the serializer's `pricing`, the stock check) keep
sharing one answer via `attach_pricing`.

Measured on the dev catalogue before that sharing existed: 3 combos cost 59 queries, 29 of
them price lookups, because `resolve_combo_price` ran three times per combo. A regression
here means somebody removed the sharing, not that they added a field.

`conftest` clears the cache before each test, so this measures the DB path.
"""
from decimal import Decimal

import pytest

from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.combos.factories import ComboFactory, ComboItemFactory
from apps.inventory.factories import StockItemFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db

# Per combo, for a three-item bundle of DISTINCT products. Set from the measured cost
# with headroom for a field or two, not from wishful thinking.
#
# WHERE THE 20 GOES, so the next person knows whether a rise is a regression or a
# feature: per item it is one stock SUM (`available_for_country`), one variants lookup
# (`sellable_in`, which uses `.filter()` and so cannot be prefetch-served), and up to
# FOUR price lookups — `apps.pricing.services.resolve_price` walks its resolution order
# one query at a time until a scope matches, and a variant priced only at the
# currency level misses three before it hits.
#
# That last one is the whole constant, it is shared pricing code, and the catalogue
# sidesteps it on ITS list with `annotate_min_price` rather than by fixing it. A combo
# has no equivalent annotation (the sum runs over items, each with its own resolution
# order), so the constant stays. It is affordable because this endpoint is cached for
# 60s and holds a curated handful — what would NOT be affordable is it going quadratic,
# which is what the second test below actually guards.
PER_COMBO = 20
FIXED = 10


def _combo(ng, warehouse, items=3):
    combo = ComboFactory(status="active")
    for i in range(items):
        variant = ProductVariantFactory()
        Price.objects.create(
            variant=variant, currency=ng.currency, amount=Decimal("1000.00")
        )
        StockItemFactory(variant=variant, warehouse=warehouse, quantity=50)
        ComboItemFactory(combo=combo, variant=variant, quantity=1, position=i)
    return combo


def test_the_combo_list_cost_is_bounded(ng, warehouse, django_assert_max_num_queries):
    for _ in range(6):
        _combo(ng, warehouse)

    client = APIClient()
    with django_assert_max_num_queries(FIXED + 6 * PER_COMBO):
        r = client.get("/api/v1/combos/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert len(r.data) == 6


def test_a_second_combo_does_not_cost_more_than_the_first(
    ng, warehouse, django_assert_max_num_queries
):
    """The property that actually matters: linear, not quadratic. A `visible_combos`
    that lost its prefetches, or an `attach_pricing` that stopped being called, shows up
    here as the second combo costing several times the first."""
    from django.db import connection
    from django.core.cache import cache
    from django.test.utils import CaptureQueriesContext

    client = APIClient()

    _combo(ng, warehouse)
    cache.clear()
    with CaptureQueriesContext(connection) as one:
        client.get("/api/v1/combos/", HTTP_X_COUNTRY="NG")

    for _ in range(4):
        _combo(ng, warehouse)
    cache.clear()
    with CaptureQueriesContext(connection) as five:
        client.get("/api/v1/combos/", HTTP_X_COUNTRY="NG")

    marginal = (len(five.captured_queries) - len(one.captured_queries)) / 4
    assert marginal <= PER_COMBO, (
        f"each extra combo costs {marginal:.1f} queries, budget {PER_COMBO}. "
        "Check that ComboListView still calls attach_pricing and that "
        "visible_combos still prefetches."
    )
