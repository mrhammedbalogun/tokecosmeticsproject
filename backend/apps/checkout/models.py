from django.conf import settings
from django.db import models
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel


class Coupon(TimeStampedModel):
    TYPE_CHOICES = [
        ("percent", "Percentage off"),
        ("fixed", "Fixed amount off"),
        ("free_shipping", "Free shipping"),
    ]

    code = models.CharField(max_length=40)  # stored uppercased; CI-unique via constraint below
    type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # % or amount
    currency = models.ForeignKey(
        "core.Currency", null=True, blank=True, on_delete=models.PROTECT
    )  # required for fixed; null for percent/free_shipping
    min_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)  # total, null = unlimited
    usage_limit_per_user = models.PositiveIntegerField(null=True, blank=True)
    applies_to_products = models.ManyToManyField("catalog.Product", blank=True)
    applies_to_categories = models.ManyToManyField("catalog.Category", blank=True)
    is_active = models.BooleanField(default=True)
    legacy_source = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Upper("code"), name="uniq_coupon_code_ci"),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class CouponRedemption(TimeStampedModel):
    """Usage ledger. `order_number` is a soft reference (not an FK) so this app stays
    independent of apps.orders (built in 08d); 08d writes a row per successful order."""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    email = models.EmailField(blank=True)
    order_number = models.CharField(max_length=20, blank=True, db_index=True)

    def __str__(self) -> str:
        return f"{self.coupon.code} by {self.email or self.user_id} ({self.order_number})"
