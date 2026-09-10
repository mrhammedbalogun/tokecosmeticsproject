"""Catalog domain services: sellability + price annotation used by the read APIs."""
from __future__ import annotations

from django.core.cache import cache
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from apps.pricing.services import resolve_price

_CACHE_VERSION_KEY = "catalog:cache_version"
CATALOG_CACHE_TTL = 60  # seconds


def catalog_cache_version() -> int:
    return cache.get_or_set(_CACHE_VERSION_KEY, 1, None)


def bump_catalog_cache() -> None:
    try:
        cache.incr(_CACHE_VERSION_KEY)
    except ValueError:
        cache.set(_CACHE_VERSION_KEY, 1, None)


def catalog_cache_key(request) -> str:
    country = request.country.code
    qs = request.META.get("QUERY_STRING", "")
    return f"catalog:{catalog_cache_version()}:{country}:{request.path}?{qs}"


def sellable_in(product, country) -> bool:
    """A product is visible/sellable in a country iff:
    (a) available_countries is empty OR contains the country, AND
    (b) at least one active variant resolves to a price in that country.
    ("hide until priced" — Hammed approved.)
    """
    allowed = product.available_countries.all()
    if allowed.exists() and country not in allowed:
        return False
    for variant in product.variants.filter(is_active=True):
        if resolve_price(variant, country) is not None:
            return True
    return False


def annotate_min_price(queryset, country):
    """Annotate each product with `min_price`: the lowest active-window Price
    amount for the country's currency where country matches OR is NULL.

    Used for price sort/filter in the list API. See the plan's design note —
    this is monotonic, not a full precedence replica; the displayed price comes
    from resolve_price. Products with no price get min_price=None.

    Also annotates `min_price_compare_at`, the "was" price OF THAT SAME ROW, for the
    struck-through price on a card (2026-09-10, needed by the Promo listing). It is a
    second subquery rather than a value carried out of the first, so the two must agree
    about WHICH row is cheapest: hence `order_by("amount", "id")` in both — plain
    `order_by("amount")` leaves ties to the database, and two ties resolved differently
    would print one row's discount against another row's price.
    """
    from apps.pricing.models import Price

    now = timezone.now()
    active = (Q(starts_at__isnull=True) | Q(starts_at__lte=now)) & (
        Q(ends_at__isnull=True) | Q(ends_at__gte=now)
    )
    cheapest = (
        Price.objects.filter(
            active,
            variant__product=OuterRef("pk"),
            variant__is_active=True,
            currency=country.currency,
        )
        .filter(Q(country=country) | Q(country__isnull=True))
        .order_by("amount", "id")
    )
    return queryset.annotate(
        min_price=Subquery(cheapest.values("amount")[:1]),
        min_price_compare_at=Subquery(cheapest.values("compare_at_amount")[:1]),
    )


def annotate_priced_variant_count(queryset, country):
    """Annotate `priced_variant_count`: how many active variants the shopper can
    actually buy in this country — i.e. how many options they have to choose between.

    The storefront card uses it to decide between "Add to Cart" (one option, nothing to
    choose) and "Choose Option" (several — send them to the PDP to pick), so it has to
    agree with `resolve_price`: a variant is purchasable there iff ANY price row exists
    for the currency scoped to this country or to no country. No time window is applied,
    deliberately — resolve_price's last two fallbacks ignore windows too, so a variant
    whose sale window has closed still resolves to its plain price and is still an
    option. Filtering by window here would undercount exactly those.
    """
    from django.db.models import Count

    return queryset.annotate(
        priced_variant_count=Count(
            "variants",
            filter=Q(variants__is_active=True)
            & Q(variants__prices__currency=country.currency)
            & (
                Q(variants__prices__country=country)
                | Q(variants__prices__country__isnull=True)
            ),
            distinct=True,
        )
    )


def annotate_in_stock(queryset, country):
    """Annotate `has_stock`: does any active variant have positive availability in
    this country? One stock row with quantity > reserved is equivalent to
    available_for_country() > 0 because reserved <= quantity is DB-enforced per row
    (stock_reserved_lte_quantity), so per-row availability can never be negative.
    """
    from django.db.models import Exists, F

    from apps.inventory.models import StockItem

    positive = StockItem.objects.filter(
        variant__product=OuterRef("pk"),
        variant__is_active=True,
        warehouse__is_active=True,
        warehouse__serves_countries=country,
        quantity__gt=F("reserved"),
    )
    return queryset.annotate(has_stock=Exists(positive))


def category_subtree_slugs(slug: str) -> list[str]:
    """`slug` plus every slug beneath it, so ?category= means "and everything under it".

    WHY THE FILTER IS NOT AN EXACT MATCH (2026-09-10, the Shop by Category rework).
    The menu now has grouping rows — "Shop By Skin Concerns" over Acne / Dry Skin /
    Oily Skin / Hyperpigmentation. An exact-slug filter makes that group's own page show
    whatever was filed on the GROUPING (nothing, once headings stop being assignable),
    i.e. an empty page reachable from the main nav. Matching the subtree makes it show
    every concern product instead, which is what a shopper clicking a group expects.

    Walks DOWN in whole levels rather than recursing per node: the tree is 40-ish rows
    three levels deep, so this is 2-3 queries regardless of shape, and it does not need
    the recursive-CTE support that `django-mptt`/`ltree` would buy us at real cost.

    CYCLE-SAFE for the same reason `get_ancestors` is: `seen` bounds the walk, so a bad
    `parent` written straight into the table yields a short list instead of hanging a web
    worker. Returns `[slug]` for an unknown slug — the caller's filter then matches
    nothing, which is the same 404-ish empty page an unknown slug produced before.
    """
    from apps.catalog.models import Category

    ids = list(
        Category.objects.filter(slug=slug, is_active=True).values_list("id", flat=True)
    )
    if not ids:
        return [slug]

    slugs = {slug}
    seen = set(ids)
    frontier = ids
    while frontier:
        rows = list(
            Category.objects.filter(parent_id__in=frontier, is_active=True)
            .exclude(id__in=seen)
            .values_list("id", "slug")
        )
        if not rows:
            break
        frontier = [row[0] for row in rows]
        seen.update(frontier)
        slugs.update(row[1] for row in rows)
    return sorted(slugs)


def annotate_units_sold(queryset, since=None):
    """Annotate `units_sold`: quantity of this product actually bought, for real
    best-seller ordering.

    Counted from `OrderItem.quantity` on orders in `REVENUE_STATUSES` — the same
    definition the admin's Top products report uses, so the storefront's "Best sellers"
    and the report staff read cannot disagree about what sold. Cancelled, expired and
    pending-payment orders are excluded; production holds 2,488 expired and 671 cancelled
    orders against 1,310 completed ones, so counting them would rank abandoned baskets.

    `since` bounds it to a recent window (`BEST_SELLER_WINDOW_DAYS`). A window is the
    point of the feature: an all-time count is a monument to whatever sold in 2024 and
    stops responding to what is selling now.

    Products with no sales get 0, NOT NULL, so `-units_sold` never sorts them ahead of
    sold ones on a NULLS-FIRST database.

    Grouped on the `variant → product` FK, unlike the Top products report, which groups on
    the sku SNAPSHOT. The report has to: `OrderItem.variant` is nullable and the Plan-23
    international import wrote items with no variant, and a report that dropped them would
    not reconcile with the revenue report. Here the FK is the only option — an item with no
    variant names no product to rank — so those units go uncounted. That understates a few
    products' sales; it cannot rank a product that never sold.
    """
    from django.db.models import IntegerField, OuterRef, Subquery, Sum
    from django.db.models.functions import Coalesce

    from apps.analytics.queries import REVENUE_STATUSES
    from apps.orders.models import OrderItem

    items = OrderItem.objects.filter(
        order__status__in=REVENUE_STATUSES,
        variant__product=OuterRef("pk"),
    )
    if since is not None:
        items = items.filter(order__placed_at__gte=since)
    sold = (
        items.values("variant__product")
        .annotate(total=Sum("quantity"))
        .values("total")[:1]
    )
    return queryset.annotate(
        units_sold=Coalesce(Subquery(sold, output_field=IntegerField()), 0),
    )


def filter_on_sale(queryset, country):
    """Keep only products with a live REDUCED price in this country — the Promo listing.

    "Reduced" is `compare_at_amount > amount`, STRICTLY. The WordPress importer wrote
    `compare_at_amount = regular` on every variant it touched, sale or not
    (`migration_wp/importers/variants.py`), so `compare_at IS NOT NULL` would have
    advertised the whole catalogue as discounted at the exact moment the page went live.

    Scoped the way `annotate_min_price` is scoped — this currency, this country or
    country-NULL, inside its window — so a sale that has not started or has finished does
    not appear. That the row is winning under `resolve_price`'s precedence is NOT checked
    here (a country override could shadow it); production has 0 overrides and 0 scheduled
    rows, and the cost of the gap is a product on the Promo page whose PDP shows no
    strikethrough, not a wrong price at the till.
    """
    from django.db.models import Exists, F

    from apps.pricing.models import Price

    now = timezone.now()
    reduced = Price.objects.filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
        Q(country=country) | Q(country__isnull=True),
        variant__product=OuterRef("pk"),
        variant__is_active=True,
        currency=country.currency,
        compare_at_amount__gt=F("amount"),
    )
    return queryset.filter(Exists(reduced))
