"""Combos in the shopper's search results.

WHY SEARCH MISSED THEM ENTIRELY. `PostgresSearchBackend` searches `Product`, the view
serialises with `ProductListSerializer`, and a combo is deliberately NOT a product — no
SKU, no stock row, no variant of its own (see `apps.combos.models`). So a shopper typing
the name of a bundle got nothing, and there was no bug to find: the rows were never
consulted.

WHY A SECOND PASS AND NOT A UNION. The two cannot be one queryset. A combo's price is
resolved, not stored — `resolve_combo_price` walks the components through the pricing
engine — and whether it is buyable here at all is a Python question for the same reason
`ComboListView` filters in Python rather than SQL. A UNION would have to sort by a column
that does not exist. So SQL narrows the candidates by text, and the pricing engine decides
the rest, exactly as the combos listing already does.

The result rides on the search response as its own `combos` key rather than mixed into
`results`: the two have different shapes, different cards and different links, and a
client that cannot tell them apart sends a shopper to `/product/<combo-slug>`, which 404s.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q

from apps.combos.services import (
    attach_pricing,
    available_in,
    max_addable,
    resolve_combo_price,
    visible_combos,
)

# How many bundles a search may show. Small on purpose, and not only for the layout:
# `in_stock` on a combo card costs one stock query per COMPONENT
# (`available_for_country` is per-variant). `SearchView._combos` caches the serialised
# block so a repeated search does not pay that again, but the FIRST search for any given
# phrase does. Six bundles is the budget; the shop has a curated handful of them, not a
# catalogue.
MAX_COMBO_RESULTS = 6

# How many text matches the pricing engine will look at before giving up, and it is a
# COST CEILING rather than a page size. Availability is not expressible as a filter, so
# candidates have to be priced one by one to find out — and a combo costs about twenty
# queries to price and stock-check (see `apps/combos/tests/test_query_budget.py`, which
# explains where they go). Twelve is the headroom that lets a few unbuyable bundles at
# the top of the match list not cost the buyable ones their place, while holding the
# cold-cache worst case of this endpoint — uncached, throttled at 30/min/IP — to
# something a bot walking unique query strings cannot turn into a database problem.
MAX_CANDIDATES = 12

# Same threshold as the product search, so "combo" and "combos" behave alike on both.
_TRGM_THRESHOLD = 0.2

_TRUE = ("1", "true", "True")


def _combos_whose_contents_match(q: str, fuzzy: bool):
    """A SUBQUERY of combo ids whose CONTENTS match `q`, not a join.

    THE COMPONENTS ARE SEARCHABLE TOO, and that is the point of the feature rather than a
    flourish. A bundle is bought for what is in it, so a shopper typing "shea butter"
    should be shown the box that contains the shea butter even when the box is called
    "Glow Kit" — the one query where a bundle is the better answer is the one where the
    shopper never knew the bundle existed.

    WHY A SUBQUERY. The obvious spelling — `items__variant__product__name` on the combo
    queryset — is a join, and a trigram similarity annotated across a join lands in the
    SELECT list with one value per item, which is exactly what `.distinct()` cannot then
    collapse: a three-item bundle would come back three times. Pushing the whole question
    into `ComboItem` gives one `id IN (...)` condition, no fanout, and lets the component
    match use the SAME 0.2 threshold the product search uses — so a product a shopper can
    find on its own can also find the box it is in, which was not true of the `%`-operator
    spelling this replaced (pg_trgm's own threshold is 0.3, and "lip balm" against "Mango
    Lip + Cheek Balm" falls between the two).

    Short queries stay anchored (`istartswith`), matching the product backend: two letters
    `icontains` matches the middle of half the shelf.
    """
    from apps.combos.models import ComboItem

    items = ComboItem.objects.filter(combo__status="active")
    if fuzzy:
        items = items.annotate(
            sim=TrigramSimilarity("variant__product__name", q)
        ).filter(
            Q(sim__gt=_TRGM_THRESHOLD)
            | Q(variant__product__name__icontains=q)
            | Q(variant__product__brand__name__icontains=q)
        )
    else:
        items = items.filter(variant__product__name__istartswith=q)
    return items.values("combo_id")


def _text_match(q: str, fuzzy: bool) -> Q:
    """What counts as a bundle matching `q`: its own words, or its contents."""
    inside = Q(id__in=_combos_whose_contents_match(q, fuzzy))
    if not fuzzy:
        return Q(name__istartswith=q) | inside
    return Q(name__icontains=q) | Q(short_description__icontains=q) | inside


def _amount(combo, country) -> Decimal | None:
    pricing = resolve_combo_price(combo, country)
    return pricing.amount if pricing else None


def _within_price_bounds(combo, params, country) -> bool:
    """`price_min` / `price_max` against what the BOX costs, not its parts.

    The strike-through component total is the higher number, so filtering on it would put
    a ₦1,800 bundle outside a `price_max=2000` search on the strength of a price nobody
    is being asked to pay.
    """
    amount = None
    for key, keep in (
        ("price_min", lambda a, bound: a >= bound),
        ("price_max", lambda a, bound: a <= bound),
    ):
        raw = params.get(key)
        if not raw:
            continue
        try:
            bound = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            continue  # unparseable price: ignored, exactly as the product backend does
        if amount is None:
            amount = _amount(combo, country)
        if amount is None or not keep(amount, bound):
            return False
    return True


def _sorted(combos, sort, country):
    """The three sorts the search UI offers. Anything else keeps relevance order.

    `newest` puts an unpublished combo LAST rather than first. `published_at` is nullable
    and `None` is not comparable to a datetime, so it needs an answer either way; a
    bundle with no publication date is not the newest thing in the shop.
    """
    if sort == "price_asc":
        return sorted(combos, key=lambda c: _amount(c, country) or Decimal("0"))
    if sort == "price_desc":
        return sorted(combos, key=lambda c: _amount(c, country) or Decimal("0"), reverse=True)
    if sort == "newest":
        return sorted(
            combos,
            key=lambda c: (c.published_at is not None, c.published_at),
            reverse=True,
        )
    return combos


def search_combos(params, country, limit=MAX_COMBO_RESULTS) -> list:
    """The bundles matching this search, ready to serialise. `[]` when none do.

    Returns priced instances (`attach_pricing` has run), so `ComboListSerializer` resolves
    nothing a second time.

    A CATEGORY OR BRAND FACET DROPS COMBOS ALTOGETHER, deliberately. Those filters are
    product questions — a combo has neither, and a bundle holding one Toke product and two
    of somebody else's is not "a Toke product". Silently keeping bundles through a brand
    filter would mean a shopper who narrowed to one brand is shown another's goods; the
    honest answer to "bundles in this category" is that the shop does not file them that
    way.
    """
    q = (params.get("q") or "").strip()
    if not q or params.get("category") or params.get("brand"):
        return []

    qs = visible_combos(country)
    fuzzy = len(q) >= 3
    if fuzzy:
        # Annotated BEFORE the filter so `sim` is in the SELECT list — `visible_combos`
        # is `.distinct()` (its `available_countries` join duplicates rows), and Postgres
        # refuses to order a SELECT DISTINCT by an expression it does not select. The
        # similarity is on the combo's OWN column, so it adds no fanout of its own; the
        # component half of the match is a subquery for exactly that reason.
        qs = qs.annotate(sim=TrigramSimilarity("name", q)).filter(
            Q(sim__gt=_TRGM_THRESHOLD) | _text_match(q, fuzzy=True)
        )
        ordering = ("-sim", "position", "name")
    else:
        qs = qs.filter(_text_match(q, fuzzy=False))
        ordering = ("position", "name")

    wants_stock = params.get("in_stock") in _TRUE
    rows = []
    # ONE AT A TIME, STOPPING AT `limit`. Pricing a bundle is the expensive half and the
    # list is short, so the loop pays for exactly the bundles it shows rather than for
    # every candidate the text search turned up.
    for combo in list(qs.order_by(*ordering)[:MAX_CANDIDATES]):
        attach_pricing([combo], country)
        if not available_in(combo, country):
            continue
        if not _within_price_bounds(combo, params, country):
            continue
        # Stock is asked about ONLY when the shopper asked. A sold-out bundle is
        # otherwise KEPT and shown with its Sold Out pill, exactly as a sold-out product
        # card is — and a combo goes out of stock far more readily than a product,
        # because one empty component empties the whole box.
        if wants_stock and max_addable(combo, country) <= 0:
            continue
        rows.append(combo)
        if len(rows) == limit:
            break
    # Sorted AFTER the cut, so what a sort reorders is the bundles this search found
    # rather than the whole catalogue of them. With a curated handful in the shop and a
    # six-row cap that is the same set either way; it is written down because the day
    # there are fifty bundles it stops being.
    return _sorted(rows, params.get("sort", ""), country)


def suggest_combos(q: str, country, limit=2) -> list[dict]:
    """Bundle suggestions for the header's autocomplete: closest name first.

    Capped hard at two. The dropdown holds six rows and products are what most searches
    are for; two is enough for a bundle to be discoverable without a curated handful of
    combos crowding out the shelf.

    NAMES ONLY — no component match, unlike `search_combos`. A dropdown row is one line
    of text with nowhere to say WHY it is there, so "Weekend Box" appearing under "shea
    butter" reads as a mistake. The results page has room to explain itself (a Bundles
    heading, the component thumbnails on every card), so that is where the wider match
    belongs.
    """
    q = (q or "").strip()
    if not q:
        return []
    qs = visible_combos(country)
    if len(q) >= 3:
        qs = qs.annotate(sim=TrigramSimilarity("name", q)).filter(
            Q(sim__gt=_TRGM_THRESHOLD) | Q(name__icontains=q)
        ).order_by("-sim", "position", "name")
    else:
        qs = qs.filter(name__istartswith=q).order_by("position", "name")
    out = []
    for combo in list(qs[:MAX_CANDIDATES]):
        attach_pricing([combo], country)
        if not available_in(combo, country):
            continue
        out.append({"name": combo.name, "slug": combo.slug, "type": "combo"})
        if len(out) == limit:
            break
    return out
