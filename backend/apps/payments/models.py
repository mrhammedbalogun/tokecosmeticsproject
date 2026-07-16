from django.db import models


class Payment(models.Model):
    STATUSES = [
        ("initiated", "Initiated"), ("pending", "Pending"), ("succeeded", "Succeeded"),
        ("failed", "Failed"), ("cancelled", "Cancelled"),
        ("refunded", "Refunded"), ("partially_refunded", "Partially refunded"),
    ]

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    gateway = models.CharField(max_length=20)  # paystack|flutterwave|stripe|paypal|bank_transfer
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="initiated", choices=STATUSES)
    gateway_reference = models.CharField(max_length=128, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.gateway} {self.amount} ({self.status}) for {self.order_id}"


class CountryPaymentGateway(models.Model):
    """Which gateways are offered per country — admin-managed data, not config."""

    country = models.ForeignKey("core.Country", on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("country", "gateway")]
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return f"{self.country_id}:{self.gateway} ({'on' if self.is_active else 'off'})"
