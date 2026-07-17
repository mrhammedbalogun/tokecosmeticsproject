"""Order serializers.

Three audiences, three shapes, and the differences between them are deliberate:

- `OrderSerializer` — the authenticated owner. Everything about their own order.
- `OrderTrackingSerializer` — whoever holds the signed link. **Redacted**: no address, no
  phone, no email. The token is a bearer credential sitting in a forwardable inbox, so it
  answers "where is my parcel?" and nothing that would leak the customer's home address
  to whoever the mail got passed on to.
- `AdminOrderSerializer` — staff. Adds the timeline, the review flag, internal notes.
"""
from rest_framework import serializers

from apps.orders.models import Order, OrderEvent, OrderItem
from apps.payments.money import format_money


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
