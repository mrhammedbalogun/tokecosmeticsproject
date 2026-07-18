from rest_framework import serializers

from apps.catalog.api_serializers import ProductListSerializer
from apps.catalog.models import Product
from apps.catalog.services import annotate_min_price
from apps.wishlist.models import WishlistItem


class WishlistItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="variant.sku", read_only=True)
    product = serializers.SerializerMethodField()

    class Meta:
        model = WishlistItem
        fields = ["sku", "product", "created_at"]

    def get_product(self, obj):
        # Resolve the product card in the request's country, exactly like listings do.
        country = self.context["request"].country
        qs = annotate_min_price(
            Product.objects.filter(pk=obj.variant.product_id), country
        ).select_related("brand").prefetch_related("images")
        product = qs.first()
        if product is None:
            return None
        return ProductListSerializer(product, context=self.context).data
