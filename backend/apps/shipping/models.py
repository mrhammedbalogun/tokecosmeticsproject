from django.db import models

from apps.core.models import TimeStampedModel


class ShippingQuote(TimeStampedModel):
    """The freight OBLIGATION for one order — a negotiated promise, not money.

    Deliberately NOT a Payment row. The cash the customer eventually transfers for
    freight IS a Payment (purpose="freight"); this is what we ASKED for. Keeping the
    two apart is what makes `amount` (quoted) and `payment.amount` (actually landed)
    structurally different numbers, which they are: an international wire quoted at
    €40 delivers ~€32 after correspondent fees. A single-amount design would have
    nowhere to put that gap and would silently under-report cash.

    A `quoted` status also has no business in Payment.STATUSES: when the four
    networked gateways reactivate, that enum is gateway-shaped (initiated/succeeded/
    failed), and a row meaning "quoted, no money has moved" would pollute it forever.
    """

    STATUSES = [
        ("awaiting_quote", "Awaiting quote"),   # created at order placement
        ("quoted", "Quoted"),                   # customer has been told the figure
        ("paid", "Paid"),                       # freight cash recorded
        ("waived", "Waived"),                   # merchant absorbed it — requires a prior quote
        ("cancelled", "Cancelled"),             # declined OR never answered — same handling
    ]
    # Nothing further happens to the order on these; is_shippable stops blocking.
    SETTLED = frozenset({"paid", "waived", "cancelled"})

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="shipping_quote"
    )
    # null until quoted — the whole point of awaiting_quote is that no figure exists yet.
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="awaiting_quote", choices=STATUSES)
    quoted_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    # APPEND-ONLY. Re-quoting ("can you try someone cheaper?") overwrites `amount`, so
    # the note is the only trail of what was previously promised. Never assign to it —
    # always append. Same erasure class as an earlier payments bug where a flag was
    # assigned over an earlier flag and money was lost.
    note = models.TextField(blank=True)

    class Meta:
        indexes = [
            # The work queue: "orders I have not quoted yet" and "quoted, awaiting money".
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"freight {self.amount or '—'} {self.currency_id} ({self.status}) for {self.order_id}"

    @property
    def is_settled(self) -> bool:
        return self.status in self.SETTLED
