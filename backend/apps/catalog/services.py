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
        .order_by("amount")
        .values("amount")[:1]
    )
    return queryset.annotate(min_price=Subquery(cheapest))
