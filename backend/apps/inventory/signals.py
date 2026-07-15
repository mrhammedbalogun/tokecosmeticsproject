"""Stock changes affect the storefront's `in_stock`, so they must invalidate the
catalog read cache — same version-bump mechanism catalog writes use."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.catalog.services import bump_catalog_cache
from apps.inventory.models import StockItem


@receiver(post_save, sender=StockItem)
@receiver(post_delete, sender=StockItem)
def _bump_catalog_on_stock_change(sender, **kwargs):
    bump_catalog_cache()
