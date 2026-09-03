"""The public shape of a combo: what it is, what is in the box, what it costs.

PRICES ARE RESOLVED, NEVER STORED IN THE PAYLOAD'S SHAPE. Both the bundle price and the
strike-through "bought separately" figure come from `resolve_combo_price` at read time,
so a component repriced this morning cannot leave a stale saving on the page — the one
place a discount claim being wrong is worse than it being absent.
"""
from rest_framework import serializers

from apps.catalog.images import storage_url, variant_image_path
from apps.combos.models import Combo
from apps.combos.services import max_addable, resolve_combo_price


class ComboItemSerializer(serializers.Serializer):
    """One thing in the box, as the customer sees it: which product, which options, how
    many, what it would cost alone, and a link back to its own page."""

    def to_representation(self, item):
        country = self.context["request"].country
        variant = item.variant
        product = variant.product
        from apps.pricing.services import resolve_price

        resolved = resolve_price(variant, country)
        images = list(product.images.all())
        return {
            "product_name": product.name,
            "product_slug": product.slug,
            "variant_name": variant.name,
            "sku": variant.sku,
            # The picked options, verbatim — {"Size": "500g", "Pricing option": "Pieces"}.
            # A dict rather than a joined string so the page can lay them out as chips and
            # the customer can see at a glance that the 500g is the one in the box.
            "option_values": variant.option_values or {},
            "quantity": item.quantity,
            "unit_price": str(resolved.amount) if resolved else None,
            "line_total": str(resolved.amount * item.quantity) if resolved else None,
            "image": storage_url(variant_image_path(variant)) or None,
            "hover_image": (
                storage_url(images[1].image.name) if len(images) > 1 else None
            ),
            "short_description": product.short_description,
        }


class _ComboPricingMixin:
    def _pricing(self, combo):
        country = self.context["request"].country
        p = resolve_combo_price(combo, country)
        if p is None:
            return None
        return {
            "amount": str(p.amount),
            "components_total": str(p.components_total),
            "saving": str(p.saving),
            "saving_percent": str(p.saving_percent),
            "currency": p.currency,
        }


class ComboListSerializer(_ComboPricingMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()
    # The first few pictures in the box, for the card's stacked thumbnails — a bundle
    # card that shows only its own hero photograph tells a shopper nothing about what is
    # in it, which is the one question a bundle has to answer before it is clicked.
    item_images = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Combo
        fields = ["name", "slug", "short_description", "image", "is_featured",
                  "pricing", "item_count", "item_images", "in_stock"]

    def get_image(self, obj) -> str | None:
        return storage_url(obj.image.name) if obj.image else None

    def get_pricing(self, obj):
        return self._pricing(obj)

    def get_item_count(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())

    def get_item_images(self, obj) -> list[str]:
        urls = [storage_url(variant_image_path(i.variant)) for i in obj.items.all()[:4]]
        return [u for u in urls if u]

    def get_in_stock(self, obj) -> bool:
        return max_addable(obj, self.context["request"].country) > 0


class ComboDetailSerializer(_ComboPricingMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    max_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Combo
        fields = ["name", "slug", "description", "short_description", "image",
                  "is_featured", "seo_title", "seo_description", "pricing", "items",
                  "in_stock", "max_quantity"]

    def get_image(self, obj) -> str | None:
        return storage_url(obj.image.name) if obj.image else None

    def get_pricing(self, obj):
        return self._pricing(obj)

    def get_items(self, obj):
        return ComboItemSerializer(obj.items.all(), many=True, context=self.context).data

    def get_max_quantity(self, obj) -> int:
        """How many whole bundles the shelves can fill right now.

        Exposed so the quantity stepper can stop where the stock does instead of letting
        a shopper pick five and be told at the till. Capped for display: an unbounded
        number invites nobody and reveals the shop's stock levels for free.
        """
        return min(max_addable(obj, self.context["request"].country), 10)

    def get_in_stock(self, obj) -> bool:
        return max_addable(obj, self.context["request"].country) > 0
