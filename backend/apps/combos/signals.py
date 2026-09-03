"""Combos ride the catalogue cache version.

A combo's price is derived from catalogue prices, and the storefront caches its combo
responses under the same `catalog:` key prefix (`apps.catalog.services.catalog_cache_key`).
Editing a combo therefore has to bump the same counter a product edit does — one version,
one flush, no second scheme to keep in step.
"""
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from apps.catalog.services import bump_catalog_cache
from apps.combos.models import Combo, ComboItem, ComboPrice

_WATCHED = {Combo, ComboItem, ComboPrice}


@receiver(post_save)
@receiver(post_delete)
def _invalidate_on_write(sender, **kwargs):
    if sender in _WATCHED:
        bump_catalog_cache()


@receiver(m2m_changed, sender=Combo.available_countries.through)
def _invalidate_on_market_change(sender, **kwargs):
    # `available_countries` decides visibility and fires no post_save of its own, so
    # without this a combo withdrawn from a market stays listed there for the TTL.
    if kwargs.get("action") in ("post_add", "post_remove", "post_clear"):
        bump_catalog_cache()
