"""Bump the catalog cache version whenever catalog/price data changes, so cached
list/detail responses are invalidated at once (see services.catalog_cache_key)."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    Product,
    ProductImage,
    ProductVariant,
)
from apps.catalog.services import bump_catalog_cache
from apps.pricing.models import Price

_WATCHED = {Product, ProductVariant, ProductImage, Category, Brand, Collection, Price}


@receiver(post_save)
@receiver(post_delete)
def _invalidate_catalog_cache(sender, **kwargs):
    if sender in _WATCHED:
        bump_catalog_cache()
