import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Cart(TimeStampedModel):
    KIND_CHOICES = [("standard", "Standard"), ("express", "Express (Buy Now)")]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("converted", "Converted"),
        ("abandoned", "Abandoned"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="carts",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="standard")
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # At most one active cart per (user, kind). Guests (user NULL) are exempt
            # — their identity is the cart UUID itself, so they can hold many.
            models.UniqueConstraint(
                fields=["user", "kind"],
                condition=Q(status="active", user__isnull=False),
                name="uniq_active_cart_per_user_kind",
            )
        ]

    def __str__(self) -> str:
        who = self.user_id or "guest"
        return f"Cart {self.id} ({who}/{self.kind}/{self.status})"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    # Snapshot of the resolved price when the item was last added/updated.
    # For drift display only — checkout recomputes. Never the charge basis.
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    added_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("cart", "variant")]

    def __str__(self) -> str:
        return f"{self.quantity}× {self.variant.sku} in {self.cart_id}"
