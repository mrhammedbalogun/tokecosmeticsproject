from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class Review(TimeStampedModel):
    """A verified-purchase product review. Born `pending`; only an approval (admin now,
    API in Plan-18) makes it public and feeds the product's denormalised rating."""

    STATUSES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="reviews"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    # The order that made this a verified purchase (audit trail; SET_NULL so deleting a
    # migrated order never deletes the review).
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=140, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, default="pending", choices=STATUSES)

    class Meta:
        # One review per customer per product — re-review edits the existing row (Plan-18).
        unique_together = [("product", "user")]
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["product", "status"])]

    def __str__(self) -> str:
        return f"{self.rating}★ {self.product_id} by {self.user_id} ({self.status})"
