"""Denormalised product-rating recompute. The ONLY writer of Product.rating_avg /
rating_count. Aggregates APPROVED reviews only; saving the product fires the catalog
cache-bump signal (apps.catalog.signals) so cached cards re-render with the new stars.

Meilisearch document sync is Plan-07b's job (no index exists yet — see the plan's D2).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count


def recompute_product_rating(product) -> None:
    from apps.reviews.models import Review

    agg = Review.objects.filter(product=product, status="approved").aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    count = agg["count"] or 0
    avg = agg["avg"]
    product.rating_count = count
    product.rating_avg = (
        Decimal(str(avg)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if avg is not None
        else Decimal("0.00")
    )
    product.save(update_fields=["rating_avg", "rating_count", "updated_at"])
