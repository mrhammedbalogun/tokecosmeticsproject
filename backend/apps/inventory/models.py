from django.db import models

from apps.core.models import TimeStampedModel


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=100)
    location_country = models.CharField(max_length=2)  # ISO code where it physically is
    serves_countries = models.ManyToManyField("core.Country", related_name="warehouses")
    priority = models.PositiveSmallIntegerField(default=100)  # lower = tried first when reserving
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.name


class StockItem(TimeStampedModel):
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="stock_items"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_items")
    quantity = models.IntegerField(default=0)  # on-hand
    reserved = models.IntegerField(default=0)  # held by pending checkouts
    low_stock_threshold = models.IntegerField(default=5)

    class Meta:
        unique_together = [("variant", "warehouse")]
        constraints = [
            # Can't-oversell backstop, independent of application logic.
            models.CheckConstraint(check=models.Q(quantity__gte=0), name="stock_quantity_nonneg"),
            models.CheckConstraint(check=models.Q(reserved__gte=0), name="stock_reserved_nonneg"),
            models.CheckConstraint(
                check=models.Q(reserved__lte=models.F("quantity")),
                name="stock_reserved_lte_quantity",
            ),
        ]

    @property
    def available(self) -> int:
        return self.quantity - self.reserved

    def __str__(self) -> str:
        return f"{self.variant.sku} @ {self.warehouse.name}: {self.available} avail"


class StockMovement(TimeStampedModel):
    """Append-only audit trail. The ledger is the source of truth for reservations."""

    REASONS = [
        ("sale", "Sale"),
        ("reservation", "Reservation"),
        ("release", "Release"),
        ("restock", "Restock"),
        ("adjustment", "Adjustment"),
        ("damaged", "Damaged"),
        ("returned", "Returned"),
        ("migration", "Migration"),
    ]

    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    delta_quantity = models.IntegerField(default=0)  # change to on-hand
    delta_reserved = models.IntegerField(default=0)  # change to reserved
    reason = models.CharField(max_length=30, choices=REASONS)
    reference = models.CharField(max_length=64, blank=True, db_index=True)  # order number etc.
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.reason} q{self.delta_quantity:+d} r{self.delta_reserved:+d} ({self.reference})"
