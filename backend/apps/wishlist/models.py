from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class WishlistItem(TimeStampedModel):
    """One saved variant for one user. Variant-level (not product-level) so a customer
    can save a specific size; the API resolves the product card per country on read."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="wishlisted_by"
    )

    class Meta:
        unique_together = [("user", "variant")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} ♥ {self.variant_id}"
