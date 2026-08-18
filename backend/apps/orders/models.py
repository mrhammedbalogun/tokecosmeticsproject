from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper
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
    # + cancelled, expired, refunded, on_hold(migrated). See orders/state.py for the
    # authoritative vocabulary and the allowed moves between them.
    #
    # Deliberately NOT statuses:
    #   needs_review       — orthogonal, see review_reason below.
    #   partially_refunded — refund progress is a payment-ledger fact (payment.status +
    #                        the Refund rows), not a place in the order's life. A shipped
    #                        order can be partially refunded and still needs delivering.

    # Orthogonal "a human must look at this" carrier, and the single source of truth for
    # the admin needs-attention filter (`review_reason != ""`). Independent of status by
    # design: a processing order can need review (double payment) and so can an expired
    # one, so flagging never overwrites what actually happened.
    # Cleared ONLY by an explicit admin resolve action, never by a status transition —
    # otherwise shipping a flagged order would silently erase an unresolved double
    # payment and the customer would never be refunded.
    review_reason = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # The slice of `tax_total` attributable to delivery (0 unless the market has
    # `tax_applies_to_delivery`). Stored so referral commissions can subtract the
    # ITEM tax only — see apps/referrals/services.commission_base.
    delivery_tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
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

    # The referral code this order was attributed to at PLACEMENT, or "". A plain string
    # rather than an FK to referrals.ReferralProfile, for the same reason
    # `checkout.CouponRedemption.order_number` is a soft reference: this is the order's
    # own record of what the customer arrived with, and it must survive the referrer's
    # profile being deleted with the answer intact.
    #
    # Stamped here — not resolved later — because the only place the attribution cookie
    # exists is the checkout request. Payment confirmation runs off a gateway webhook
    # with no browser and no cookie behind it, so a commission worked out at that point
    # would have nothing to work from. See referrals/services.accrue_for_order.
    referral_code = models.CharField(max_length=32, blank=True)

    source = models.CharField(max_length=20, default="web")  # web|legacy_ng|legacy_intl|admin
    legacy_number = models.CharField(max_length=20, blank=True, db_index=True)
    placed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-placed_at"]
        indexes = [
            # The expiry task sweeps on (status, reservation_expires_at) every few
            # minutes, and every admin order list filters on status.
            models.Index(fields=["status", "reservation_expires_at"]),
            models.Index(fields=["status", "-placed_at"]),
            # Trigram indexes for the admin search box and the order queue's `search`
            # filter, both of which do `icontains` on these three columns. On `UPPER(col)`
            # rather than the bare column because that is what Django's `icontains`
            # compiles to on PostgreSQL — measured at 200k orders (Plan-16 Task 6): 63ms
            # unindexed, 0.24ms with these. `number` already has a UNIQUE btree and
            # `legacy_number` a plain btree, and NEITHER helps: both patterns are
            # unanchored `%term%`, which no btree can serve.
            GinIndex(OpClass(Upper("number"), name="gin_trgm_ops"), name="order_number_trgm"),
            GinIndex(
                OpClass(Upper("legacy_number"), name="gin_trgm_ops"),
                name="order_legacy_num_trgm",
            ),
            GinIndex(OpClass(Upper("email"), name="gin_trgm_ops"), name="order_email_trgm"),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def is_shippable(self) -> bool:
        """False while freight is unresolved OR was declined. Deliberately a derived
        property and NOT an Order.status value: a new status would touch every transition
        table, serializer, admin filter and status test in the codebase — the largest
        blast radius in this design — to say something entirely derivable.

        Only `paid` (freight collected) and `waived` (merchant absorbed it) clear shipping.
        A `cancelled` quote is settled for the service guards (is_settled) but the customer
        DECLINED freight, so the order must never ship — hence this checks the status set
        directly rather than reusing ShippingQuote.is_settled.

        The accepted tradeoff: a ship queue written later could forget to filter on this.
        Anything that dispatches goods MUST check it.
        """
        quote = getattr(self, "shipping_quote", None)
        return quote is None or quote.status in ("paid", "waived")


class OrderEvent(models.Model):
    """Append-only timeline: what happened to this order, when, and who did it.

    This is the record that settles disputes, so it outlives the people in it —
    `actor` is SET_NULL, never CASCADE. `actor` is null for machine-driven changes
    (webhooks, Celery tasks), which is exactly why `message` must carry provenance;
    "status changed to processing, by nobody, for no reason" helps no one.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=40)  # "status:shipped", "placed", "review_resolved"
    message = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]  # oldest first; pk breaks ties within a transaction
        indexes = [models.Index(fields=["order", "created_at"])]

    def __str__(self) -> str:
        return f"{self.order_id}: {self.type}"


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
    # The STORAGE KEY of the line's picture, snapshotted at checkout — not a URL.
    #
    # Was `image_url = URLField(blank=True)`, i.e. varchar(200), and nothing ever wrote it
    # from orders/0001 until now. Two reasons it changed shape rather than being filled
    # in as it stood: a catalogue image path may be 500 characters (`IMAGE_PATH_MAX`), so
    # a CDN URL built from one raises DataError from Postgres — inside checkout's locked
    # transaction, which is a 500 at the till; and a stored URL freezes today's CDN
    # hostname into this table forever, breaking every historical order's picture the next
    # time media hosting moves. `apps/catalog/images.py` has the full argument.
    #
    # The API still exposes `image_url`: `OrderItemSerializer` derives it from this key.
    image_path = models.CharField(max_length=500, blank=True)
    # {"UK Warehouse": 3, "Lagos HQ": 2} — written by inventory.commit_sale via mark_paid.
    fulfillment_warehouses = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"{self.quantity}× {self.product_name} ({self.order_id})"
