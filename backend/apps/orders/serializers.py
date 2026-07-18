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
from apps.payments.money import format_money

# A refund can only be taken against money we actually collected; mirrors
# refunds._REFUNDABLE_PAYMENT_STATES.
_REFUNDABLE_PAYMENT_STATES = ("succeeded", "partially_refunded")


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price_display = serializers.SerializerMethodField()
    line_total_display = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("product_name", "variant_name", "sku", "quantity", "unit_price",
                  "line_total", "unit_price_display", "line_total_display", "image_url")

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
    class Meta:
        model = Order
        fields = ("number", "status", "placed_at", "email", "phone", "currency",
                  "subtotal", "discount_total", "shipping_total", "tax_total",
                  "grand_total", "grand_total_display", "delivery_option_name",
                  "shipping_address", "billing_address", "customer_note",
                  "tracking_carrier", "tracking_number", "items")


class OrderTrackingSerializer(_BaseOrderSerializer):
    """The redacted, bearer-token view. Every field here is one we're content to have
    forwarded — deliberately no address, phone or email."""

    class Meta:
        model = Order
        fields = ("number", "status", "placed_at", "currency", "grand_total",
                  "grand_total_display", "delivery_option_name",
                  "tracking_carrier", "tracking_number", "items")


class AdminOrderSerializer(_BaseOrderSerializer):
    events = OrderEventSerializer(many=True, read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True, default="")

    class Meta:
        model = Order
        fields = ("number", "status", "review_reason", "placed_at", "email", "phone",
                  "user_email", "country", "currency", "subtotal", "discount_total",
                  "shipping_total", "tax_total", "grand_total", "grand_total_display",
                  "delivery_option_name", "shipping_address", "billing_address",
                  "customer_note", "admin_note", "tracking_carrier", "tracking_number",
                  "source", "legacy_number", "items", "events")


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
