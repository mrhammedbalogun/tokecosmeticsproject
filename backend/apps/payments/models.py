from django.conf import settings
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

    class Meta:
        constraints = [
            # A gateway_reference is only unique WITHIN a gateway (two gateways can
            # coincidentally mint the same reference). Webhook processing matches a
            # Payment by (gateway, gateway_reference), so a duplicate would make that
            # lookup ambiguous at the worst moment. Empty references (pre-initiate) are
            # exempt — many Payments legitimately have "" until the gateway assigns one.
            models.UniqueConstraint(
                fields=["gateway", "gateway_reference"],
                condition=~models.Q(gateway_reference=""),
                name="uniq_payment_gateway_reference",
            ),
        ]

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


class Refund(models.Model):
    """A staff-initiated (or gateway-completion-driven) refund against a Payment.
    Async on some gateways (Flutterwave/PayPal can return `pending`), so status
    advances pending -> succeeded/failed, the latter via a refund-completion webhook."""

    STATUSES = [("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")]

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending", choices=STATUSES)
    gateway_reference = models.CharField(max_length=128, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"refund {self.amount} ({self.status}) of payment {self.payment_id}"


class WebhookEvent(models.Model):
    """Idempotency ledger for inbound gateway webhooks. The unique (gateway, event_id)
    row IS the dedupe: a duplicate delivery hits the constraint and is ignored. Stores
    the raw payload for audit and to reprocess if a bug is fixed later."""

    gateway = models.CharField(max_length=20)
    event_id = models.CharField(max_length=128)  # gateway's id, or a derived deterministic id
    event_type = models.CharField(max_length=64)
    # Captured from the signature-verified ParsedEvent so the async processor can match a
    # Payment WITHOUT re-parsing (re-parsing needs the live request to check the signature).
    gateway_reference = models.CharField(max_length=128, blank=True, db_index=True)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("gateway", "event_id")]

    def __str__(self) -> str:
        return f"{self.gateway}:{self.event_type}:{self.event_id}"
