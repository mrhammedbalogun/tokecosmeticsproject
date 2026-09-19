"""Combos in the shopper's search — `/api/v1/search/` and `/api/v1/search/suggest/`.

Lives beside the other combo tests rather than in `apps/search/tests/` because the
scaffolding it needs is the combo `conftest` — a market, stock, and a bundle that prices.
What is under test is `apps.search.combos`.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import (
    BrandFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.combos.factories import ComboItemFactory
from apps.core.models import Country

SEARCH = "/api/v1/search/"
SUGGEST = "/api/v1/search/suggest/"


def _names(response):
    return {row["name"] for row in response.data["combos"]}


@pytest.fixture
def client():
    return APIClient()


# ── the feature ──────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_matching_combo_rides_beside_the_products(client, combo):
    combo(name="Glow Kit", slug="glow-kit")
    r = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert _names(r) == {"Glow Kit"}
    # Beside, never inside: `results` and `count` stay products-only.
    assert r.data["results"] == []
    assert r.data["count"] == 0


@pytest.mark.django_db
def test_the_card_carries_what_the_combo_grid_needs(client, combo):
    combo(name="Glow Kit")
    row = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG").data["combos"][0]
    assert set(row) >= {"name", "slug", "pricing", "item_count", "item_images", "in_stock"}
    assert row["pricing"]["amount"] == "1800.00"       # ₦2,000 of parts, 10% off
    assert row["pricing"]["currency"] == "NGN"


@pytest.mark.django_db
def test_a_combo_is_found_by_what_is_inside_it(client, combo, priced_variant):
    """The query a bundle exists to answer: the shopper knows the product, not the box."""
    c = combo(name="Weekend Box")
    shea = priced_variant("900.00")
    shea.product.name = "Raw Shea Butter"
    shea.product.save(update_fields=["name"])
    ComboItemFactory(combo=c, variant=shea, quantity=1)
    r = client.get(SEARCH, {"q": "shea butter"}, HTTP_X_COUNTRY="NG")
    assert _names(r) == {"Weekend Box"}


@pytest.mark.django_db
def test_a_component_is_matched_on_the_words_not_the_exact_string(client, combo, priced_variant):
    """"shea butter" has to find "Shea Whip Body Butter" — a shopper types the thing, not
    the label. The combo NAME gets this from the trigram sort; the components get it from
    the `%` operator, which is the only form an index can serve across the join."""
    c = combo(name="Weekend Box")
    v = priced_variant("900.00")
    v.product.name = "Shea Whip Body Butter"
    v.product.save(update_fields=["name"])
    ComboItemFactory(combo=c, variant=v, quantity=1)
    assert _names(client.get(SEARCH, {"q": "shea butter"}, HTTP_X_COUNTRY="NG")) == {"Weekend Box"}


@pytest.mark.django_db
def test_search_is_typo_tolerant_on_a_combo_name(client, combo):
    combo(name="Moisturizer Bundle")
    r = client.get(SEARCH, {"q": "moistriser"}, HTTP_X_COUNTRY="NG")
    assert _names(r) == {"Moisturizer Bundle"}


@pytest.mark.django_db
def test_a_non_matching_combo_stays_out(client, combo):
    combo(name="Glow Kit")
    r = client.get(SEARCH, {"q": "charcoal"}, HTTP_X_COUNTRY="NG")
    assert r.data["combos"] == []


# ── the edges ────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_draft_combo_is_not_searchable(client, combo):
    combo(name="Secret Kit", status="draft")
    assert client.get(SEARCH, {"q": "secret"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_a_combo_withdrawn_from_this_market_is_not_searchable(client, combo, ng):
    c = combo(name="Lagos Only Kit")
    c.available_countries.add(ng)
    assert _names(client.get(SEARCH, {"q": "lagos"}, HTTP_X_COUNTRY="NG")) == {"Lagos Only Kit"}
    assert Country.objects.filter(code="GB").exists()  # the other market is real
    assert client.get(SEARCH, {"q": "lagos"}, HTTP_X_COUNTRY="GB").data["combos"] == []


@pytest.mark.django_db
def test_a_combo_with_an_unpriceable_component_is_not_searchable(client, combo):
    """Hidden until priced — the same rule the listing page applies, for the same reason:
    a bundle missing a component price is not cheap, it is unpriceable."""
    c = combo(name="Half Priced Kit")
    ComboItemFactory(combo=c, variant=ProductVariantFactory(), quantity=1)  # no Price row
    assert client.get(SEARCH, {"q": "half"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_a_combo_holding_an_archived_product_is_not_searchable(client, combo, priced_variant):
    c = combo(name="Stale Kit")
    dead = priced_variant("300.00")
    dead.product.status = "archived"
    dead.product.save(update_fields=["status"])
    ComboItemFactory(combo=c, variant=dead, quantity=1)
    assert client.get(SEARCH, {"q": "stale"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_a_sold_out_combo_still_shows_unless_the_shopper_filtered(client, combo):
    """A sold-out PRODUCT card shows with a tag rather than vanishing; a bundle must not
    behave oppositely two rows away."""
    c = combo(name="Empty Kit")
    for item in c.items.all():
        item.variant.stock_items.update(quantity=0)
    r = client.get(SEARCH, {"q": "empty"}, HTTP_X_COUNTRY="NG")
    assert _names(r) == {"Empty Kit"}
    assert r.data["combos"][0]["in_stock"] is False
    assert client.get(SEARCH, {"q": "empty", "in_stock": "1"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_price_filters_read_the_box_price_not_the_parts(client, combo):
    """₦2,000 of parts, ₦1,800 in the box. A `price_max` of 1900 must keep it."""
    combo(name="Glow Kit")
    kept = client.get(SEARCH, {"q": "glow", "price_max": "1900"}, HTTP_X_COUNTRY="NG")
    assert _names(kept) == {"Glow Kit"}
    dropped = client.get(SEARCH, {"q": "glow", "price_min": "1900"}, HTTP_X_COUNTRY="NG")
    assert dropped.data["combos"] == []


@pytest.mark.django_db
def test_an_unparseable_price_bound_is_ignored_not_fatal(client, combo):
    combo(name="Glow Kit")
    r = client.get(SEARCH, {"q": "glow", "price_min": "cheap"}, HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert _names(r) == {"Glow Kit"}


@pytest.mark.django_db
def test_a_brand_or_category_facet_drops_combos_entirely(client, combo):
    """A bundle has neither, and keeping it through a brand filter would show a shopper
    who narrowed to one brand somebody else's goods."""
    combo(name="Glow Kit")
    BrandFactory(slug="toke")
    assert client.get(SEARCH, {"q": "glow", "brand": "toke"}, HTTP_X_COUNTRY="NG").data["combos"] == []
    assert client.get(SEARCH, {"q": "glow", "category": "skin"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_combos_appear_on_the_first_page_only(client, combo):
    """They are unpaginated, so repeating them would put the same boxes on every page."""
    combo(name="Glow Kit")
    for i in range(30):
        p = ProductFactory(name=f"Glow Serum {i}")
        PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))
    first = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")
    assert _names(first) == {"Glow Kit"}
    assert client.get(SEARCH, {"q": "glow", "page": "2"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_an_empty_query_returns_no_combos(client, combo):
    combo(name="Glow Kit")
    assert client.get(SEARCH, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_a_combo_matched_twice_over_appears_once(client, combo, priced_variant):
    """Name AND two components matching is one bundle, not three rows."""
    c = combo(name="Glow Kit")
    for _ in range(2):
        v = priced_variant("100.00")
        v.product.name = "Glow Serum"
        v.product.save(update_fields=["name"])
        ComboItemFactory(combo=c, variant=v, quantity=1)
    rows = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG").data["combos"]
    assert [row["name"] for row in rows] == ["Glow Kit"]


@pytest.mark.django_db
def test_sorting_orders_bundles_too(client, combo):
    combo(name="Glow Cheap Kit", discount_percent=50)   # ₦1,000
    combo(name="Glow Rich Kit", discount_percent=0)     # ₦2,000
    asc = client.get(SEARCH, {"q": "glow", "sort": "price_asc"}, HTTP_X_COUNTRY="NG")
    assert [r["name"] for r in asc.data["combos"]] == ["Glow Cheap Kit", "Glow Rich Kit"]
    desc = client.get(SEARCH, {"q": "glow", "sort": "price_desc"}, HTTP_X_COUNTRY="NG")
    assert [r["name"] for r in desc.data["combos"]] == ["Glow Rich Kit", "Glow Cheap Kit"]


@pytest.mark.django_db
def test_newest_sort_puts_an_unpublished_bundle_last(client, combo):
    from django.utils import timezone

    combo(name="Glow New Kit", published_at=timezone.now())
    combo(name="Glow Undated Kit")  # published_at is NULL
    r = client.get(SEARCH, {"q": "glow", "sort": "newest"}, HTTP_X_COUNTRY="NG")
    assert [row["name"] for row in r.data["combos"]] == ["Glow New Kit", "Glow Undated Kit"]


@pytest.mark.django_db
def test_the_result_count_is_capped(client, combo):
    from apps.search.combos import MAX_COMBO_RESULTS

    for i in range(MAX_COMBO_RESULTS + 3):
        combo(name=f"Glow Kit {i}")
    r = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")
    assert len(r.data["combos"]) == MAX_COMBO_RESULTS


# ── suggest ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_suggest_labels_a_combo_so_it_is_not_linked_as_a_product(client, combo):
    combo(name="Glow Kit", slug="glow-kit")
    rows = client.get(SUGGEST, {"q": "glow"}, HTTP_X_COUNTRY="NG").data
    assert {"name": "Glow Kit", "slug": "glow-kit", "type": "combo"} in rows


@pytest.mark.django_db
def test_suggest_puts_bundles_first_and_still_caps_at_six(client, combo):
    combo(name="Glow Kit")
    for i in range(8):
        p = ProductFactory(name=f"Glow Serum {i}")
        PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))
    rows = client.get(SUGGEST, {"q": "glow"}, HTTP_X_COUNTRY="NG").data
    assert len(rows) == 6
    assert rows[0]["type"] == "combo"
    assert sum(1 for r in rows if r["type"] == "combo") == 1


@pytest.mark.django_db
def test_suggest_never_offers_a_bundle_that_cannot_be_bought_here(client, combo, ng):
    c = combo(name="Glow Kit")
    c.available_countries.add(ng)
    assert client.get(SUGGEST, {"q": "glow"}, HTTP_X_COUNTRY="GB").data == []


@pytest.mark.django_db
def test_suggest_caps_bundles_at_two(client, combo):
    for i in range(5):
        combo(name=f"Glow Kit {i}")
    rows = client.get(SUGGEST, {"q": "glow"}, HTTP_X_COUNTRY="NG").data
    assert sum(1 for r in rows if r["type"] == "combo") == 2


# ── the cache ────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_archiving_a_combo_takes_it_out_of_search_at_once(client, combo):
    """The bundle block is cached; the cache is versioned on the catalogue counter.

    Without the bump this would keep selling an archived bundle for the TTL — the case
    archiving exists for is a bundle pulled BECAUSE something about it was wrong.
    """
    c = combo(name="Glow Kit")
    assert _names(client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")) == {"Glow Kit"}
    c.status = "archived"
    c.save(update_fields=["status"])
    assert client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG").data["combos"] == []


@pytest.mark.django_db
def test_repricing_a_component_moves_the_bundle_price_in_search(client, combo):
    c = combo(name="Glow Kit")
    first = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG").data["combos"][0]
    assert first["pricing"]["amount"] == "1800.00"
    price = c.items.first().variant.prices.first()
    price.amount = Decimal("2000.00")
    price.save(update_fields=["amount"])
    again = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG").data["combos"][0]
    assert again["pricing"]["amount"] == "2700.00"   # ₦3,000 of parts, 10% off


@pytest.mark.django_db
def test_two_markets_do_not_share_a_cached_bundle_block(client, combo, ng):
    """One process serves every market; an NG answer handed back for GB is the whole
    reason the country is in the cache key."""
    c = combo(name="Glow Kit")
    c.available_countries.add(ng)
    assert _names(client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")) == {"Glow Kit"}
    assert client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="GB").data["combos"] == []


@pytest.mark.django_db
def test_the_bundle_half_of_a_search_is_bounded_and_then_cached(
    client, combo, django_assert_max_num_queries
):
    """What this pins is the SHAPE, not the number.

    `/search/` has no `CatalogCacheMixin` — the product half is deliberately
    `no-store` — so before the bundle block was cached separately, every keystroke's
    worth of searching paid the full combo price walk. Cold it is bounded by
    `MAX_CANDIDATES` and the six-row cap; warm it is three queries. A regression here
    means the cache went, or the loop stopped exiting early, or `attach_pricing`
    stopped being shared — see `test_query_budget.py` for where the per-combo constant
    goes.
    """
    from apps.search.combos import MAX_COMBO_RESULTS

    for i in range(MAX_COMBO_RESULTS + 4):
        combo(name=f"Glow Kit {i}")
    with django_assert_max_num_queries(120):
        first = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")
    assert len(first.data["combos"]) == MAX_COMBO_RESULTS
    with django_assert_max_num_queries(5):
        again = client.get(SEARCH, {"q": "glow"}, HTTP_X_COUNTRY="NG")
    assert again.data["combos"] == first.data["combos"]
