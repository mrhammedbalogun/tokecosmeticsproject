from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Order(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)  # "TC-100001" or a legacy number
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="orders"
    )  # null ONLY for migrated guest orders / deleted accounts (Decision 7)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=24, default="pending_payment")
    # pending_payment → processing → shipped → delivered → completed
    # + cancelled, expired, refunded, partially_refunded, needs_review, on_hold(migrated)
    # Orthogonal "a human must look at this" carrier — single source of truth for the
    # admin needs-attention filter. Set in EVERY flag path (including when status flips
    # to needs_review). The double-payment case sets this WITHOUT changing status, since
    # an already-`processing` order can't also be `needs_review`. Plan-10's transition()
    # clears it when the flag is resolved.
    review_reason = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    coupon = models.ForeignKey("checkout.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    delivery_option_name = models.CharField(max_length=100, blank=True)
    shipping_address = models.JSONField(default=dict)  # snapshot, not FK
    billing_address = models.JSONField(default=dict)
    customer_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    tracking_carrier = models.CharField(max_length=50, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)

    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    # Attempt-suffixed reservation ledger key (starts == number; "/2" on re-reserve).
    reservation_reference = models.CharField(max_length=24, blank=True)

    source = models.CharField(max_length=20, default="web")  # web|legacy_ng|legacy_intl|admin
    legacy_number = models.CharField(max_length=20, blank=True, db_index=True)
    placed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-placed_at"]

    def __str__(self) -> str:
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, on_delete=models.SET_NULL
    )  # product may be deleted later — snapshots survive
    product_name = models.CharField(max_length=255)
    variant_name = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    image_url = models.URLField(blank=True)
    # {"UK Warehouse": 3, "Lagos HQ": 2} — written by inventory.commit_sale via mark_paid.
    fulfillment_warehouses = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"{self.quantity}× {self.product_name} ({self.order_id})"
