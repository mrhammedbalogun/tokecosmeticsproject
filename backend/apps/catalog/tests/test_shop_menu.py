"""The Shop by Category rework (2026-09-10): heading rows, subtree filtering, and the
three computed "Shop By Edit" listings.

Each test here pins a decision that is invisible in the code and expensive to rediscover:
that a group page shows its children's products, that "best selling" counts money-taking
orders inside a window, and that Promo needs a STRICT reduction because the WordPress
import left `compare_at == amount` all over the catalogue.
"""
import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.factories import (
    CategoryFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.catalog.management.commands.rebuild_shop_menu import MENU
from apps.catalog.models import Category, Product
from apps.catalog.services import category_subtree_slugs
from apps.core.models import Country
from apps.orders.models import Order, OrderItem


def _priced(slug, categories=(), amount="5000.00", compare_at=None, published=None):
    product = ProductFactory(slug=slug, name=slug.replace("-", " ").title())
    if published is not None:
        product.published_at = published
        product.save(update_fields=["published_at"])
    if categories:
        product.categories.set(categories)
    variant = ProductVariantFactory(product=product)
    PriceFactory(
        variant=variant,
        amount=Decimal(amount),
        compare_at_amount=None if compare_at is None else Decimal(compare_at),
    )
    return product


def _slugs(response):
    return [row["slug"] for row in response.data["results"]]


# ── headings and the subtree filter ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_group_page_lists_its_childrens_products():
    """Clicking "Shop By Skin Concerns" must not land on an empty page.

    The grouping row holds no products by design (`is_assignable=False`), so an
    exact-slug filter would return nothing at all from a link in the main nav.
    """
    group = CategoryFactory(slug="shop-by-skin-concerns", is_assignable=False)
    acne = CategoryFactory(slug="acne", parent=group)
    oily = CategoryFactory(slug="oily-skin", parent=group)
    _priced("acne-wash", categories=[acne])
    _priced("oil-control-gel", categories=[oily])
    _priced("unrelated-shampoo", categories=[CategoryFactory(slug="hair-care")])

    r = APIClient().get("/api/v1/products/?category=shop-by-skin-concerns")
    assert r.status_code == 200
    assert set(_slugs(r)) == {"acne-wash", "oil-control-gel"}


@pytest.mark.django_db
def test_a_child_page_lists_only_its_own():
    group = CategoryFactory(slug="shop-by-skin-concerns", is_assignable=False)
    acne = CategoryFactory(slug="acne", parent=group)
    CategoryFactory(slug="oily-skin", parent=group)
    _priced("acne-wash", categories=[acne])
    _priced("oil-control-gel", categories=[CategoryFactory(slug="oily-skin-2")])

    r = APIClient().get("/api/v1/products/?category=acne")
    assert _slugs(r) == ["acne-wash"]


@pytest.mark.django_db
def test_a_product_in_two_categories_is_not_listed_twice():
    """A product may be filed under several categories — the union must not duplicate it,
    or the grid shows the same card twice and `count` lies to the pager."""
    group = CategoryFactory(slug="shop-by-skin-concerns", is_assignable=False)
    acne = CategoryFactory(slug="acne", parent=group)
    oily = CategoryFactory(slug="oily-skin", parent=group)
    _priced("does-both", categories=[acne, oily])

    r = APIClient().get("/api/v1/products/?category=shop-by-skin-concerns")
    assert _slugs(r) == ["does-both"]
    assert r.data["count"] == 1


@pytest.mark.django_db
def test_an_inactive_child_is_not_swept_in_by_its_parent():
    """Hiding a category has to hide its products from the group page too — otherwise
    "hidden" means hidden from the menu but still shoppable one click up."""
    group = CategoryFactory(slug="shop-by-skin-concerns", is_assignable=False)
    hidden = CategoryFactory(slug="acne", parent=group, is_active=False)
    _priced("acne-wash", categories=[hidden])

    r = APIClient().get("/api/v1/products/?category=shop-by-skin-concerns")
    assert _slugs(r) == []


@pytest.mark.django_db
def test_subtree_of_an_unknown_slug_is_just_that_slug():
    assert category_subtree_slugs("no-such-category") == ["no-such-category"]


@pytest.mark.django_db
def test_subtree_survives_a_parent_cycle():
    """A cycle written straight into the table must yield a short list, not hang a
    worker. `CategoryAdminSerializer` refuses to create one; the database does not."""
    a = CategoryFactory(slug="a")
    b = CategoryFactory(slug="b", parent=a)
    Category.objects.filter(pk=a.pk).update(parent=b)

    assert category_subtree_slugs("a") == ["a", "b"]


@pytest.mark.django_db
def test_the_tree_endpoint_marks_headings():
    """The storefront menu needs `is_assignable` to render a group label instead of one
    more shoppable link."""
    group = CategoryFactory(slug="shop-by-skin-tone", is_assignable=False)
    CategoryFactory(slug="fair-skin", parent=group)

    r = APIClient().get("/api/v1/categories/")
    row = [c for c in r.data if c["slug"] == "shop-by-skin-tone"][0]
    assert row["is_assignable"] is False
    assert row["children"][0]["is_assignable"] is True


# ── Shop By Edit: Best Sellers ──────────────────────────────────────────────────────────


_ORDER_NUMBER = itertools.count(900001)


def _sold(product, quantity, days_ago=1, status="completed"):
    ng = Country.objects.get(code="NG")
    order = Order.objects.create(
        number=f"TC-{next(_ORDER_NUMBER)}",
        email="shopper@example.com",
        status=status,
        country=ng,
        currency=ng.currency,
        placed_at=timezone.now() - timedelta(days=days_ago),
        grand_total=Decimal("5000.00") * quantity,
    )
    OrderItem.objects.create(
        order=order,
        variant=product.variants.first(),
        product_name=product.name,
        unit_price=Decimal("5000.00"),
        line_total=Decimal("5000.00") * quantity,
        quantity=quantity,
    )
    return order


@pytest.mark.django_db
def test_best_selling_ranks_by_units_actually_sold():
    quiet = _priced("quiet-product")
    popular = _priced("popular-product")
    middling = _priced("middling-product")
    _sold(popular, 40)
    _sold(middling, 5)

    r = APIClient().get("/api/v1/products/?ordering=best_selling")
    assert _slugs(r)[:2] == ["popular-product", "middling-product"]
    assert "quiet-product" in _slugs(r)  # unsold products still appear, at the back
    assert quiet.slug in _slugs(r)


@pytest.mark.django_db
def test_best_selling_ignores_orders_that_never_took_money():
    """Production holds 2,488 expired and 671 cancelled orders against 1,310 completed
    ones. Counting them would rank abandoned baskets as best sellers."""
    abandoned = _priced("abandoned-product")
    real = _priced("real-product")
    _sold(abandoned, 100, status="expired")
    _sold(abandoned, 100, status="cancelled")
    _sold(real, 1)

    r = APIClient().get("/api/v1/products/?ordering=best_selling")
    assert _slugs(r)[0] == "real-product"


@pytest.mark.django_db
def test_best_selling_ignores_sales_older_than_the_window():
    stale = _priced("last-years-hit")
    current = _priced("this-quarters-hit")
    _sold(stale, 500, days_ago=400)
    _sold(current, 3, days_ago=2)

    r = APIClient().get("/api/v1/products/?ordering=best_selling")
    assert _slugs(r)[0] == "this-quarters-hit"


# ── Shop By Edit: Promo ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_promo_needs_a_strict_reduction():
    """`compare_at == amount` is NOT a promotion. The WordPress importer wrote the regular
    price into `compare_at_amount` on every variant it touched, so treating non-null as
    "on sale" would have put the entire catalogue on the Promo page."""
    _priced("really-reduced", amount="4000.00", compare_at="6000.00")
    _priced("import-artifact", amount="5000.00", compare_at="5000.00")
    _priced("plain-priced", amount="5000.00")

    r = APIClient().get("/api/v1/products/?on_sale=1")
    assert _slugs(r) == ["really-reduced"]


@pytest.mark.django_db
def test_promo_excludes_a_sale_that_has_not_started_or_has_ended():
    now = timezone.now()
    future = _priced("starts-tomorrow", amount="4000.00")
    past = _priced("ended-yesterday", amount="4000.00")
    live = _priced("on-sale-now", amount="4000.00", compare_at="6000.00")
    for product, starts, ends in (
        (future, now + timedelta(days=1), None),
        (past, now - timedelta(days=9), now - timedelta(days=1)),
    ):
        PriceFactory(
            variant=product.variants.first(),
            amount=Decimal("3000.00"),
            compare_at_amount=Decimal("6000.00"),
            starts_at=starts,
            ends_at=ends,
        )

    r = APIClient().get("/api/v1/products/?on_sale=1")
    assert _slugs(r) == [live.slug]


@pytest.mark.django_db
def test_the_card_carries_the_was_price_only_when_it_is_real():
    _priced("really-reduced", amount="4000.00", compare_at="6000.00")
    _priced("import-artifact", amount="5000.00", compare_at="5000.00")

    r = APIClient().get("/api/v1/products/")
    cards = {row["slug"]: row for row in r.data["results"]}
    assert cards["really-reduced"]["compare_at"] == "6000.00"
    assert cards["import-artifact"]["compare_at"] is None


@pytest.mark.django_db
def test_the_was_price_belongs_to_the_variant_the_from_price_came_from():
    """Two variants, and only the DEARER one is reduced: pairing its "was" with the
    cheaper variant's "now" would invent a discount that is not on offer."""
    product = ProductFactory(slug="two-sizes")
    small = ProductVariantFactory(product=product, sku="SMALL")
    large = ProductVariantFactory(product=product, sku="LARGE")
    PriceFactory(variant=small, amount=Decimal("4000.00"))
    PriceFactory(variant=large, amount=Decimal("9000.00"), compare_at_amount=Decimal("12000.00"))

    r = APIClient().get("/api/v1/products/")
    card = [row for row in r.data["results"] if row["slug"] == "two-sizes"][0]
    assert card["from_price"] == "4000.00"
    assert card["compare_at"] is None


# ── the rebuild command ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_rebuild_is_a_dry_run_unless_asked():
    from django.core.management import call_command

    call_command("rebuild_shop_menu", verbosity=0)
    assert not Category.objects.filter(slug="baby-kids-care").exists()


@pytest.mark.django_db
def test_rebuild_adopts_a_legacy_row_and_keeps_its_products():
    """The whole reason the command reuses rows: production's "Hair Care" holds 18
    products, and rebuilding from scratch would have unfiled every one of them."""
    from django.core.management import call_command

    legacy = CategoryFactory(slug="hair-care", name="Hair Care")
    product = _priced("shea-shampoo", categories=[legacy])

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    legacy.refresh_from_db()
    assert legacy.slug == "hair-care"
    assert legacy.parent_id is None
    assert legacy.is_active
    assert list(product.categories.values_list("slug", flat=True)) == ["hair-care"]


@pytest.mark.django_db
def test_rebuild_merges_duplicates_and_retires_the_rest():
    from django.core.management import call_command

    keep = CategoryFactory(slug="skin-care", name="Skin Care")
    duplicate = CategoryFactory(slug="skin-care-2", name="Skin Care")
    unwanted = CategoryFactory(slug="men-care", name="Men Care")
    only_in_duplicate = _priced("night-cream", categories=[duplicate])
    only_in_unwanted = _priced("beard-oil", categories=[unwanted])

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    assert set(only_in_duplicate.categories.values_list("slug", flat=True)) >= {
        "skin-care", "skin-care-2",
    }
    assert keep.products.filter(pk=only_in_duplicate.pk).exists()
    duplicate.refresh_from_db()
    unwanted.refresh_from_db()
    assert not duplicate.is_active
    assert not unwanted.is_active
    # Nothing is deleted: the retired row still knows what was in it, so a wrong call
    # here is undone with a checkbox rather than a re-import.
    assert unwanted.products.filter(pk=only_in_unwanted.pk).exists()


@pytest.mark.django_db
def test_rebuild_clears_products_filed_on_a_heading():
    """Once a heading is non-assignable the admin's editor stops offering it, so anything
    left filed there would be stuck: on the group page, with no checkbox to remove it."""
    from django.core.management import call_command

    heading = CategoryFactory(slug="shop-by-skin-concern", name="Shop By Skin Concern")
    product = _priced("stuck-product", categories=[heading])

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    heading.refresh_from_db()
    assert heading.slug == "shop-by-skin-concerns"
    assert not heading.is_assignable
    assert not heading.products.exists()
    assert not product.categories.filter(pk=heading.pk).exists()


@pytest.mark.django_db
def test_rebuild_prefers_the_row_that_already_holds_the_target_slug():
    """`facial-care` is the target slug and `facials` is the legacy row to fall back on.
    A row already sitting on the target is ADOPTED — renamed in place — because that keeps
    an indexed URL working and needs no redirect. The legacy row is then just another
    duplicate to retire."""
    from django.core.management import call_command

    incumbent = CategoryFactory(slug="facial-care", name="Something Else")
    legacy = CategoryFactory(slug="facials", name="Facials")

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    incumbent.refresh_from_db()
    legacy.refresh_from_db()
    assert (incumbent.name, incumbent.slug, incumbent.is_active) == (
        "Facial Care", "facial-care", True,
    )
    assert not legacy.is_active


@pytest.mark.django_db
def test_free_slug_moves_an_unadopted_holder_out_of_the_way():
    """The UNIQUE-constraint guard, tested directly because the shipped mapping cannot
    reach it: every node tries its own target slug first, so a row holding that slug is
    adopted rather than dispossessed. Edit the mapping so two nodes want one row and this
    is the difference between a clear rename and an IntegrityError halfway through a
    production rebuild."""
    from apps.catalog.management.commands.rebuild_shop_menu import Command

    holder = CategoryFactory(slug="skin-care", name="Old Skin Care")
    keeper = CategoryFactory(slug="skin-care-2", name="Skin Care")

    command = Command()
    command.log = []
    command._free_slug("skin-care", keeper)

    holder.refresh_from_db()
    assert holder.slug == "skin-care-legacy"
    # …and again, without colliding with the name it just took.
    third = CategoryFactory(slug="skin-care", name="Another")
    command._free_slug("skin-care", keeper)
    third.refresh_from_db()
    assert third.slug == "skin-care-legacy-2"


@pytest.mark.django_db
def test_rebuild_is_idempotent():
    from django.core.management import call_command

    call_command("rebuild_shop_menu", "--apply", verbosity=0)
    first = list(
        Category.objects.filter(is_active=True)
        .order_by("sort_order", "name")
        .values_list("slug", "name", "parent_id", "sort_order", "is_assignable")
    )
    call_command("rebuild_shop_menu", "--apply", verbosity=0)
    second = list(
        Category.objects.filter(is_active=True)
        .order_by("sort_order", "name")
        .values_list("slug", "name", "parent_id", "sort_order", "is_assignable")
    )
    assert first == second


@pytest.mark.django_db
def test_rebuild_produces_the_menu_in_order():
    from django.core.management import call_command

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    roots = list(
        Category.objects.filter(is_active=True, parent__isnull=True)
        .order_by("sort_order")
        .values_list("name", flat=True)
    )
    assert roots == [node.name for node in MENU]
    concerns = Category.objects.get(slug="shop-by-skin-concerns")
    assert list(
        concerns.children.filter(is_active=True).order_by("sort_order")
        .values_list("name", flat=True)
    ) == ["Acne", "Dry Skin", "Hyperpigmentation", "Oily Skin"]


@pytest.mark.django_db
def test_rebuild_repoints_a_homepage_tile_whose_category_moved():
    """The four "Shop by category" tiles hold a literal URL, and two of production's point
    at slugs this rebuild renames. The redirect table would catch them, but the most-clicked
    links on the site should not need catching."""
    from django.core.management import call_command

    from apps.cms.models import Banner

    CategoryFactory(slug="skin-care-2", name="Skin Care")
    CategoryFactory(slug="skin-care", name="Skin Care")
    moved = Banner.objects.create(
        placement="category", title="SKIN", cta_url="/category/skin-care-2",
    )
    untouched = Banner.objects.create(
        placement="category", title="BABIES", cta_url="/",
    )
    unrelated = Banner.objects.create(
        placement="hero", title="Hero", cta_url="/category/hair-care",
    )
    CategoryFactory(slug="hair-care", name="Hair Care")

    call_command("rebuild_shop_menu", "--apply", verbosity=0)

    moved.refresh_from_db()
    untouched.refresh_from_db()
    unrelated.refresh_from_db()
    assert moved.cta_url == "/category/skin-care"
    # Left alone: a tile pointing somewhere odd for its own reasons is a decision about
    # the tile, not a consequence of renaming a category.
    assert untouched.cta_url == "/"
    # And a slug that did NOT move is not rewritten, whatever the placement.
    assert unrelated.cta_url == "/category/hair-care"


# ── purging the links the rebuild deliberately left behind ──────────────────────────────


@pytest.mark.django_db
def test_purge_is_a_dry_run_unless_asked():
    from django.core.management import call_command

    retired = CategoryFactory(slug="men-care", is_active=False)
    product = _priced("beard-oil", categories=[retired])

    call_command("purge_retired_category_links", verbosity=0)

    assert product.categories.filter(pk=retired.pk).exists()


@pytest.mark.django_db
def test_purge_drops_retired_and_heading_links_only():
    """The rebuild leaves these on purpose (a wrong call is then undone with a checkbox),
    and production showed the cost: all 69 products carried at least one, some sixteen,
    none of them actionable in the admin."""
    from django.core.management import call_command

    retired = CategoryFactory(slug="men-care", is_active=False)
    heading = CategoryFactory(slug="shop-by-skin-tone", is_assignable=False)
    shelf = CategoryFactory(slug="hair-care")
    product = _priced("shea-shampoo", categories=[retired, heading, shelf])

    call_command("purge_retired_category_links", "--apply", verbosity=0)

    assert list(product.categories.values_list("slug", flat=True)) == ["hair-care"]


@pytest.mark.django_db
def test_purge_leaves_a_product_with_no_menu_category_alone_rather_than_inventing_one():
    """It still appears in All Products and in search — it is simply on no shelf, which is
    a filing job for a person, not something to paper over here."""
    from django.core.management import call_command

    retired = CategoryFactory(slug="uncategorized", is_active=False)
    product = _priced("orphan-product", categories=[retired])

    call_command("purge_retired_category_links", "--apply", verbosity=0)

    assert product.categories.count() == 0
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.django_db
def test_purge_prints_a_restorable_record_of_what_it_removed():
    from io import StringIO

    from django.core.management import call_command

    retired = CategoryFactory(slug="men-care", is_active=False)
    _priced("beard-oil", categories=[retired])

    out = StringIO()
    call_command("purge_retired_category_links", "--apply", stdout=out)

    # The run's own output is the backup — the docstring's restore snippet reads these.
    assert "LINK beard-oil men-care" in out.getvalue()


@pytest.mark.django_db
def test_purge_is_idempotent():
    from django.core.management import call_command

    retired = CategoryFactory(slug="men-care", is_active=False)
    product = _priced("beard-oil", categories=[retired, CategoryFactory(slug="hair-care")])

    call_command("purge_retired_category_links", "--apply", verbosity=0)
    call_command("purge_retired_category_links", "--apply", verbosity=0)

    assert list(product.categories.values_list("slug", flat=True)) == ["hair-care"]
