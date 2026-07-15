"""The ONE way any code resolves a price for a variant in a country context.

Resolution order (first match wins):
  1. active-window price for (currency, exact country)
  2. active-window price for (currency, country=NULL)
  3. non-windowed price for (currency, exact country)
  4. non-windowed price for (currency, country=NULL)
Returns None if the variant is not sellable in this country (storefront hides it).

The Price import is deferred into the function body so this module is importable
even while the pricing app is not yet in INSTALLED_APPS (Plan-04). Full DB tests
land at the start of Plan-05.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ResolvedPrice:
    amount: Decimal
    compare_at: Decimal | None
    currency: str
    tax_rate: Decimal
    prices_include_tax: bool


def resolve_price(variant, country, at=None):
    from django.db.models import F, Q
    from django.utils import timezone

    from apps.pricing.models import Price

    at = at or timezone.now()
    currency = country.currency

    active_window = Q(starts_at__isnull=True) | Q(starts_at__lte=at)
    active_window &= Q(ends_at__isnull=True) | Q(ends_at__gte=at)

    base = Price.objects.filter(variant=variant, currency=currency)

    for scope in (
        base.filter(active_window, country=country),
        base.filter(active_window, country__isnull=True),
        base.filter(country=country),
        base.filter(country__isnull=True),
    ):
        # An explicit sale window (starts_at set) beats a plain price; among windows,
        # the most recently started wins. nulls_last makes this deterministic across
        # databases (Postgres sorts NULLs first in DESC by default; SQLite sorts them last).
        price = scope.order_by(F("starts_at").desc(nulls_last=True)).first()
        if price:
            return ResolvedPrice(
                amount=price.amount,
                compare_at=price.compare_at_amount,
                currency=currency.code,
                tax_rate=country.tax_rate_percent,
                prices_include_tax=country.prices_include_tax,
            )
    return None
