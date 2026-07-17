from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Payment(models.Model):
    STATUSES = [
        ("initiated", "Initiated"), ("pending", "Pending"), ("succeeded", "Succeeded"),
        ("failed", "Failed"), ("cancelled", "Cancelled"),
        ("refunded", "Refunded"), ("partially_refunded", "Partially refunded"),
    ]

    PURPOSES = [("goods", "Goods"), ("freight", "Freight")]

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    gateway = models.CharField(max_length=20)  # paystack|flutterwave|stripe|paypal|bank_transfer
    # What this money is FOR. Default "goods" is load-bearing: every pre-existing row and
    # every .payments read that was not updated keeps its original meaning, so a missed
    # call site fails safe rather than silently mixing freight into goods maths.
    # A freight row is created ONLY by shipping.services.record_freight_receipt (next task),
    # which never calls confirm_manual_receipt — the amount-match, accept_discrepancy and
    # duplicate-reference controls live in that SERVICE, not in this model, so freight
    # cannot reach them.
    purpose = models.CharField(max_length=10, default="goods", choices=PURPOSES)
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
    # How the adapter classified this event, so the async processor routes it to the
    # payment pipeline or the refund pipeline without re-parsing.
    kind = models.CharField(max_length=10, default="payment")  # payment|refund|other
    refund_reference = models.CharField(max_length=128, blank=True)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("gateway", "event_id")]

    def __str__(self) -> str:
        return f"{self.gateway}:{self.event_type}:{self.event_id}"


class BankAccount(models.Model):
    """The merchant's bank account for one market. Bank transfer is the only live payment
    method at launch, so this row IS the payment page for that country — an absent or
    inactive row must make initiate() fail loudly rather than render blanks."""

    country = models.OneToOneField(
        "core.Country", on_delete=models.PROTECT, related_name="bank_account"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=64)  # or IBAN
    # Per-market shape: sort_code (GB), routing_number (US), IBAN/SWIFT (intl wires).
    # A JSON blob rather than columns — every market wants a different subset and this is
    # display-only data the customer copies into their banking app. Keys BECOME the labels
    # the customer reads (see gateways.bank_transfer._label): an all-lowercase key is
    # prettified, so `sort_code` renders as "Sort code", while a key with any capital in it
    # is left exactly as typed — write `IBAN` or `SWIFT BIC` and that is what is sent.
    extra = models.JSONField(default=dict, blank=True)
    instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.country_id}: {self.bank_name} {self.account_number}"

    def clean(self):
        if self.currency_id and self.country_id and self.currency_id != self.country.currency_id:
            raise ValidationError(
                {"currency": f"must be {self.country.currency_id} to match {self.country_id}"}
            )
