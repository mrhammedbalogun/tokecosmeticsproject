"""Order serializers.

Three audiences, three shapes, and the differences between them are deliberate:

- `OrderSerializer` — the authenticated owner. Everything about their own order.
- `OrderTrackingSerializer` — whoever holds the signed link. **Redacted**: no address, no
  phone, no email. The token is a bearer credential sitting in a forwardable inbox, so it
  answers "where is my parcel?" and nothing that would leak the customer's home address
  to whoever the mail got passed on to.
- `AdminOrderSerializer` — staff. Adds the timeline, the review flag, internal notes.
"""
from decimal import Decimal

from rest_framework import serializers

from apps.orders.models import Order, OrderEvent, OrderItem
from apps.orders.state import (
    ALLOWED_TRANSITIONS,
    ELEVATED_STATUSES,
    MACHINE_OWNED_STATUSES,
)
from apps.payments.models import Payment, Refund
from apps.catalog.images import storage_url, variant_image_path
from apps.payments.money import format_money
from apps.payments.refunds import refundable_amount

# A refund can only be taken against money we actually collected; mirrors
# refunds._REFUNDABLE_PAYMENT_STATES.
_REFUNDABLE_PAYMENT_STATES = ("succeeded", "partially_refunded")


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price_display = serializers.SerializerMethodField()
    line_total_display = serializers.SerializerMethodField()
    # THE API CONTRACT IS UNCHANGED — still `image_url`, still an absolute URL — while the
    # model now stores a storage KEY (`OrderItem.image_path`). Deriving it here is what
    # lets the CDN hostname move without rewriting the orders table, and it means this
    # field finally has a value: it was declared in orders/0001, exposed here, and never
    # written by anything, so every order page has been rendering an empty string since
    # launch.
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("product_name", "variant_name", "sku", "quantity", "unit_price",
                  "line_total", "unit_price_display", "line_total_display", "image_url")

    def get_image_url(self, item) -> str:
        # Snapshot first, live fallback for orders placed before the snapshot existed —
        # the same order of preference the emails use, so a customer's order page and
        # their confirmation email cannot disagree about the picture.
        return storage_url(item.image_path) or storage_url(
            variant_image_path(item.variant)
        )

    def get_unit_price_display(self, item) -> str:
        return format_money(item.unit_price, item.order.currency)

    def get_line_total_display(self, item) -> str:
        return format_money(item.line_total, item.order.currency)


class OrderEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = OrderEvent
        fields = ("type", "message", "actor_name", "created_at")

    def get_actor_name(self, event) -> str:
        # Null actor means machine-driven (webhook, Celery). Say so rather than showing
        # a blank, or the timeline reads like someone forgot to sign their work.
        return event.actor.get_full_name() or event.actor.email if event.actor else "system"


class _BaseOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    currency = serializers.CharField(source="currency_id", read_only=True)
    # The market's name for its tax line ("VAT", "Sales Tax"). Read live off the
    # country rather than snapshotted: renaming the line should rename it on old
    # order pages too — the AMOUNT is the snapshot, the caption is presentation.
    tax_label = serializers.CharField(source="country.tax_label", read_only=True)
    grand_total_display = serializers.SerializerMethodField()

    def get_grand_total_display(self, order) -> str:
        return format_money(order.grand_total, order.currency)


class OrderListSerializer(_BaseOrderSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("number", "status", "placed_at", "currency", "grand_total",
                  "grand_total_display", "item_count", "items")

    def get_item_count(self, order) -> int:
        return sum(item.quantity for item in order.items.all())


class OrderSerializer(_BaseOrderSerializer):
    payment_gateway = serializers.SerializerMethodField()
    gig_tracking = serializers.SerializerMethodField()
    pickup_centre = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("number", "status", "placed_at", "email", "phone", "currency",
                  "subtotal", "discount_total", "shipping_total", "tax_total",
                  "tax_label", "grand_total", "grand_total_display", "delivery_option_name",
                  "shipping_address", "billing_address", "customer_note",
                  "tracking_carrier", "tracking_number", "payment_gateway",
                  "gig_tracking", "pickup_centre", "items")

    def get_pickup_centre(self, order):
        """The placement-time centre snapshot for pickup orders (32b ruling 4) —
        known from placement, so it renders before any waybill exists. None for
        door delivery, so the page can simply not render the block."""
        return getattr(getattr(order, "gig_shipment", None), "centre", None) or None

    def get_gig_tracking(self, order):
        """The parcel's latest GIG scan, verbatim, for the account order page.

        Verbatim because GIG's status vocabulary is unpublished — rendering the
        raw scan is truthful even while our status map is behind (Plan-32a
        ruling 5). None for non-GIG orders and for shipments with no waybill
        yet, so the page can simply not render the block. Absent from
        OrderTrackingSerializer on purpose: that is the redacted bearer-token
        view and adds nothing it doesn't already say via tracking_number."""
        shipment = getattr(order, "gig_shipment", None)
        if shipment is None or not shipment.waybill:
            return None
        return {
            "status": shipment.status,
            "last_scan": shipment.last_scan,
            "last_tracked_at": shipment.last_tracked_at,
        }

    def get_payment_gateway(self, order) -> str:
        """How this order was paid — the gateway of its most recent payment attempt.

        The confirmation page needs it and cannot infer it: `status` conflates "bank
        transfer awaiting funds" with "card payment failed" (both pending_payment), so
        without this the page assumed bank transfer and instructed a customer who had
        just paid by card to go and make a transfer.

        Most RECENT, not first: after a method switch (POST /orders/{n}/pay/) the live
        attempt is the last one, and that is the one the customer is looking at. "" when
        there is no payment at all — legacy imported orders have none.

        Deliberately absent from OrderTrackingSerializer: how someone paid is not part of
        "where is my parcel", and that view goes to whoever the mail was forwarded to.
        """
        payment = max(order.payments.all(), key=lambda p: p.pk, default=None)
        return payment.gateway if payment else ""


class OrderTrackingSerializer(_BaseOrderSerializer):
    """The redacted, bearer-token view. Every field here is one we're content to have
    forwarded — deliberately no address, phone or email."""

    class Meta:
        model = Order
        fields = ("number", "status", "placed_at", "currency", "grand_total",
                  "grand_total_display", "delivery_option_name",
                  "tracking_carrier", "tracking_number", "items")


class AdminRefundSerializer(serializers.ModelSerializer):
    """One refund against one payment, for the admin payment panel."""

    created_by_email = serializers.CharField(
        source="created_by.email", read_only=True, default=""
    )

    class Meta:
        model = Refund
        fields = ("id", "amount", "status", "reason", "gateway_reference",
                  "created_by_email", "created_at")


class AdminPaymentSerializer(serializers.ModelSerializer):
    """One payment, its refunds, and what is left to refund against it.

    ADDED IN PLAN-18a because `AdminOrderSerializer` carried no money detail at all — no
    gateway, no payment status, no refunds — and all three payments admin routes are
    POST-only. The payment panel had nothing to render, and the refund modal could only
    learn the remaining balance from the RESPONSE to a refund, i.e. after moving money.
    """

    refunds = AdminRefundSerializer(many=True, read_only=True)
    refundable = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ("id", "gateway", "purpose", "amount", "currency", "status",
                  "gateway_reference", "created_at", "refunds", "refundable")

    def get_refundable(self, payment) -> str:
        """Delegated to `refunds.refundable_amount`, never recomputed here.

        That function is what the refund endpoint enforces against, and it counts PENDING
        refunds as already spent. A second implementation would eventually disagree with
        it, and the direction it would disagree in is offering an operator more headroom
        than the endpoint will allow.
        """
        return str(refundable_amount(payment))


class AdminOrderSerializer(_BaseOrderSerializer):
    events = OrderEventSerializer(many=True, read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True, default="")
    payments = AdminPaymentSerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("number", "status", "review_reason", "placed_at", "email", "phone",
                  "user_email", "country", "currency", "subtotal", "discount_total",
                  "shipping_total", "tax_total", "tax_label", "grand_total", "grand_total_display",
                  "delivery_option_name", "shipping_address", "billing_address",
                  "customer_note", "admin_note", "tracking_carrier", "tracking_number",
                  "source", "legacy_number", "items", "events",
                  "payments", "allowed_transitions")

    def get_allowed_transitions(self, order) -> list[dict]:
        """The moves a PERSON may make from here, each with the scope it needs.

        NOT `ALLOWED_TRANSITIONS[order.status]`, which is a superset of what this endpoint
        accepts. Publishing the raw constant would have a UI render:

          * `refunded` — refused since backend-v0.5.2 for any order still holding captured
            money, and never a bare status flip in any case (the refund machinery owns it);
          * `expired` — the sweep's move, not an operator's;
          * `cancelled` — legal in the machine, but gated on `orders.manage` inside the
            view, so Support would get a button that 403s.

        The scope travels WITH each entry rather than the UI keeping its own copy of the
        rule. A client-side table of who-may-do-what is a second source of truth, and this
        one guards money.
        """
        return [
            {"status": status, "requires_scope": ELEVATED_STATUSES.get(status)}
            for status in sorted(ALLOWED_TRANSITIONS.get(order.status, set()))
            if status not in MACHINE_OWNED_STATUSES
        ]


class AdminOrderListSerializer(_BaseOrderSerializer):
    class Meta:
        model = Order
        fields = ("number", "status", "review_reason", "placed_at", "email",
                  "country", "currency", "grand_total", "grand_total_display", "source")


class RefundOwedSerializer(serializers.ModelSerializer):
    """One row of the refunds-owed worklist. The amounts are the whole point of the
    screen, so they are computed here from the payment ledger, never from a cached field.

    Read the money rules before trusting `goods_amount`: on an accepted-discrepancy order
    `payment.amount` is the ORDER TOTAL, not the cash that actually landed (correspondent
    fees shave an intl wire in flight — see docs/architecture.md § Manual payments). So
    `goods_amount`/`outstanding` are the NOMINAL figures; the operator refunds what the
    customer really paid, read off the bank statement, via record_manual_refund. This queue
    answers "who is owed a refund and roughly how much", not "send exactly this".
    """

    goods_amount = serializers.SerializerMethodField()
    refunded = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    outstanding_display = serializers.SerializerMethodField()
    cancel_note = serializers.SerializerMethodField()
    cancelled_at = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ("number", "placed_at", "email", "currency", "goods_amount",
                  "refunded", "outstanding", "outstanding_display", "cancelled_at",
                  "cancel_note")

    def _goods_amount(self, order) -> Decimal:
        # Sum over goods payments still carrying a balance. `.all()` reads the prefetch,
        # so this is one query for the whole page, not one per row.
        return sum(
            (p.amount for p in order.payments.all()
             if p.purpose == "goods" and p.status in _REFUNDABLE_PAYMENT_STATES),
            Decimal("0"),
        )

    def _refunded(self, order) -> Decimal:
        return sum(
            (r.amount for p in order.payments.all() if p.purpose == "goods"
             for r in p.refunds.all() if r.status == "succeeded"),
            Decimal("0"),
        )

    def get_goods_amount(self, order) -> str:
        return f"{self._goods_amount(order):.2f}"

    def get_refunded(self, order) -> str:
        return f"{self._refunded(order):.2f}"

    def get_outstanding(self, order) -> str:
        return f"{self._goods_amount(order) - self._refunded(order):.2f}"

    def get_outstanding_display(self, order) -> str:
        return format_money(self._goods_amount(order) - self._refunded(order), order.currency)

    def get_cancel_note(self, order) -> str:
        quote = getattr(order, "shipping_quote", None)
        return quote.note if quote else ""

    def get_cancelled_at(self, order):
        quote = getattr(order, "shipping_quote", None)
        return quote.settled_at if quote else None
