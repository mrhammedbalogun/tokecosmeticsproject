from rest_framework import serializers

from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    Product,
    ProductImage,
    ProductVariant,
    ProductVideo,
    Tag,
)


class ProductAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "categories", "tags", "description",
            "short_description", "status", "is_featured", "ingredients", "directions",
            "warnings", "specs", "faqs", "related", "available_countries",
            "seo_title", "seo_description", "published_at", "legacy_source", "legacy_wp_id",
        ]
