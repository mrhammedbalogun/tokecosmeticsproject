"""Price rows for product variants.

NOTE: this app is intentionally NOT in INSTALLED_APPS during Plan-04 — its FK
targets catalog.ProductVariant, which is created in Plan-05. Plan-05 Task 0
registers the app, generates the migration, and adds the DB-backed resolve_price
tests. Do not import this module from installed code until then.
"""
from django.db import models


class Price(models.Model):
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="prices"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    country = models.ForeignKey(
        "core.Country", null=True, blank=True, on_delete=models.CASCADE
    )  # NULL = all countries using this currency
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["variant", "currency", "country", "starts_at"],
                name="uniq_price_scope",
            )
        ]
